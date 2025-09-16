from typing import List
import os

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.error import BadRequest

from bot.auth import require_auth, get_display_for_uid
from bot.config import USE_SHEETS, CSV_DEFAULT, CSV_HEADERS, IDX
from bot.services.roles import get_admin_ids, get_admins_map, get_allowed_map
from bot.services.lista import read_lista_any, set_lista_any, filter_by_status, _pad_row
from bot.services.exports import gen_contacts_any, gen_vcard_any
from bot.utils.pagination import _chunk_rows, _format_persona
from bot.handlers.edit import show_editable_list, release_reservation


def _current_user_label(update: Update) -> str:
    uid = update.effective_user.id if update.effective_user else None
    if uid is None:
        return "Sin usuario"
    uid_str = str(uid)
    display = get_display_for_uid(uid, update) or ""
    return f"{uid_str} ({display})" if display and display != uid_str else uid_str


def _row_key(row):
    padded = _pad_row(row, len(CSV_HEADERS))
    return {"tel": padded[IDX["Teléfono"]].strip(), "dni": padded[IDX["DNI"]].strip()}


def _matches_key(row, key) -> bool:
    if not key:
        return False
    padded = _pad_row(row, len(CSV_HEADERS))
    tel = padded[IDX["Teléfono"]].strip()
    dni = padded[IDX["DNI"]].strip()
    key_tel = (key.get("tel") or "").strip()
    key_dni = (key.get("dni") or "").strip()
    if key_tel and tel == key_tel:
        return True
    if key_dni and dni == key_dni:
        return True
    return False


def _pending_positions(all_rows: List[List[str]]):
    positions = []
    for idx, row in enumerate(all_rows):
        padded = _pad_row(row, len(CSV_HEADERS))
        if padded[IDX["Estado"]] == "Pendiente":
            positions.append((idx, padded))
    return positions


def _reserve_pendientes_for_user(update: Update, context: ContextTypes.DEFAULT_TYPE, limit: int = 5) -> List[List[str]]:
    preferred_indices = context.user_data.get("pending_preview_indices") or []
    preferred_keys = context.user_data.get("pending_preview_keys") or []
    all_rows = read_lista_any()
    pending_positions = _pending_positions(all_rows)
    if not pending_positions:
        return []
    max_items = min(limit, len(pending_positions)) if limit else len(pending_positions)
    selected_indices: List[int] = []
    used = set()

    def try_add_index(abs_idx: int) -> bool:
        if abs_idx in used or not (0 <= abs_idx < len(all_rows)):
            return False
        padded = _pad_row(all_rows[abs_idx], len(CSV_HEADERS))
        if padded[IDX["Estado"]] != "Pendiente":
            return False
        used.add(abs_idx)
        selected_indices.append(abs_idx)
        return True

    for abs_idx in preferred_indices:
        if len(selected_indices) >= max_items:
            break
        try_add_index(abs_idx)

    if len(selected_indices) < max_items and preferred_keys:
        for key in preferred_keys:
            if len(selected_indices) >= max_items:
                break
            for abs_idx, row in pending_positions:
                if abs_idx in used:
                    continue
                if _matches_key(row, key) and try_add_index(abs_idx):
                    break

    if len(selected_indices) < max_items:
        for abs_idx, _ in pending_positions:
            if len(selected_indices) >= max_items:
                break
            try_add_index(abs_idx)

    if not selected_indices:
        return []

    who = _current_user_label(update)
    context.user_data["reserved_owner"] = who
    selected_rows: List[List[str]] = []
    for abs_idx in selected_indices:
        padded = _pad_row(all_rows[abs_idx], len(CSV_HEADERS))
        padded[IDX["Estado"]] = f"En contacto - {who}"
        padded[IDX["Observación"]] = ""
        all_rows[abs_idx] = padded
        selected_rows.append(padded)

    set_lista_any(all_rows)
    context.user_data["reserved_rows"] = selected_rows
    context.user_data["reserved_indices"] = selected_indices
    context.user_data.pop("pending_preview_keys", None)
    context.user_data.pop("pending_preview_limit", None)
    context.user_data.pop("pending_preview_indices", None)
    return selected_rows


@require_auth
async def cmd_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # al volver al menú, devolvemos reservas sin procesar
    release_reservation(context)
    backend = "Google Sheets" if USE_SHEETS else f"CSV ({CSV_DEFAULT})"

    kb = [
        [InlineKeyboardButton("📋 Ver lista", callback_data="MENU:LISTA")],
        [
            InlineKeyboardButton("🟡 Pendientes", callback_data="MENU:FILTRO:Pendiente"),
            InlineKeyboardButton("🟢 Aceptados", callback_data="MENU:FILTRO:Aceptado"),
            InlineKeyboardButton("🔴 Rechazados", callback_data="MENU:FILTRO:Rechazado"),
        ],
        [InlineKeyboardButton("➕ Agregar Nuevo Contacto", callback_data="MENU:ADD")],    ]

    # Panel admin solo para admins
    if update.effective_user and update.effective_user.id in get_admin_ids():
        kb.append([InlineKeyboardButton("🔐 Administración", callback_data="MENU:ADMIN")])

    text = f"Bienvenido!!"
    markup = InlineKeyboardMarkup(kb)
    if getattr(update, "callback_query", None):
        await update.callback_query.edit_message_text(text, reply_markup=markup, parse_mode="Markdown")
    elif getattr(update, "message", None):
        await update.message.reply_text(text, reply_markup=markup, parse_mode="Markdown")

@require_auth
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await cmd_menu(update, context)

@require_auth
async def on_menu_home(update: Update, context: ContextTypes.DEFAULT_TYPE):
    release_reservation(context)
    return await cmd_menu(update, context)

@require_auth
async def on_page_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    _, page_str = q.data.split(":", 1)
    page = int(page_str)
    rows = context.user_data.get("list_rows", [])
    title = context.user_data.get("list_title", "Resultados")
    size = context.user_data.get("list_page_size", 10)
    if not rows:
        return await q.edit_message_text("No hay datos para paginar.")
    return await show_rows_with_pagination(
        q, context, rows, title, page, size, allow_edit=context.user_data.get("list_allow_edit", True)
    )

async def start_list_pagination(q, context, rows: List[List[str]], title: str, page_size=10, page=0, allow_edit=True):
    context.user_data["list_rows"] = rows
    context.user_data["list_title"] = title
    context.user_data["list_page_size"] = page_size
    context.user_data["list_allow_edit"] = allow_edit
    return await show_rows_with_pagination(q, context, rows, title, page, page_size, allow_edit=allow_edit)

async def show_rows_with_pagination(q, context, rows: List[List[str]], title="Resultados", page=0, page_size=10, allow_edit=True):
    if not rows:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menú", callback_data="MENU:HOME")]])
        return await q.edit_message_text(f"Sin resultados en *{title}*.", reply_markup=kb, parse_mode="Markdown")
    pages = list(_chunk_rows(rows, page_size))
    page = max(0, min(page, len(pages)-1))
    body = [_format_persona(r) for r in pages[page]]
    kb = []
    if page > 0:
        kb.append(InlineKeyboardButton("⬅️ Anterior", callback_data=f"PAGE:{page-1}"))
    if page < len(pages)-1:
        kb.append(InlineKeyboardButton("Siguiente ➡️", callback_data=f"PAGE:{page+1}"))
    nav = [kb] if kb else []
    if allow_edit:
        # Botón para editar un contacto puntual de la lista actual
        nav.append([InlineKeyboardButton("✏️ Editar estado de un contacto", callback_data=f"LISTEDIT:{page}")])
    nav.append([InlineKeyboardButton("🏠 Menú", callback_data="MENU:HOME")])
    text = f"*{title}* (página {page+1}/{len(pages)}):\n\n" + "\n".join(body)
    try:
        return await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(nav), parse_mode="Markdown")
    except BadRequest as exc:
        if "Message is not modified" in str(exc):
            return None
        raise

@require_auth
async def on_list_edit_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    try:
        _, page_str = q.data.split(":", 1)
        page = int(page_str)
    except Exception:
        page = 0
    rows = context.user_data.get("list_rows", [])
    title = context.user_data.get("list_title", "Resultados")
    if not context.user_data.get("list_allow_edit", True):
        kb = [[InlineKeyboardButton("Volver al menu", callback_data="MENU:HOME")]]
        return await q.edit_message_text("Esta lista es solo de lectura.", reply_markup=InlineKeyboardMarkup(kb))
    # Configurar el editor con la lista completa y el tamaño de página usado en la vista de lista
    context.user_data["edit_base_rows"] = rows
    context.user_data["edit_page_size"] = context.user_data.get("list_page_size", 10)
    context.user_data["edit_page"] = page
    context.user_data["edit_source"] = "list"
    context.user_data["edit_title"] = f"Cambiar estado (Lista: {title})"
    return await show_editable_list(q, context, rows, title=context.user_data["edit_title"], page=page, page_size=context.user_data["edit_page_size"])

@require_auth
async def on_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from bot.handlers.admin import (
        admin_add_start, admin_del_start, admin_add_admin_start, admin_del_admin_start
    )
    from bot.handlers.edit import (
        on_edit_page_callback, on_edit_pick_row, on_edit_set_state, send_reserved_vcf, send_reserved_as_contacts
    )

    q = update.callback_query
    await q.answer()
    data = q.data

    if data == "MENU:HOME":
        return await on_menu_home(update, context)

    if data == "MENU:ADMIN":
        if not (update.effective_user and update.effective_user.id in get_admin_ids()):
            return await q.edit_message_text("⛔ Solo administradores.")
        kb = [
            [InlineKeyboardButton("👑 Ver Admins", callback_data="ADMIN:ADM_LIST")],
            [InlineKeyboardButton("➕ Agregar Admin", callback_data="ADMIN:ADM_ADD")],
            [InlineKeyboardButton("➖ Quitar Admin", callback_data="ADMIN:ADM_DEL")],
            [InlineKeyboardButton("👥 Ver Allowed", callback_data="ADMIN:LIST")],
            [InlineKeyboardButton("➕ Agregar ID Allowed", callback_data="ADMIN:ADD")],
            [InlineKeyboardButton("➖ Quitar ID Allowed", callback_data="ADMIN:DEL")],
            [InlineKeyboardButton("🏠 Menú", callback_data="MENU:HOME")],
        ]
        return await q.edit_message_text("🔐 Panel de administración", reply_markup=InlineKeyboardMarkup(kb))

    # --- Admins panel actions ---
    if data == "ADMIN:ADM_LIST":
        if not (update.effective_user and update.effective_user.id in get_admin_ids()):
            return await q.edit_message_text("⛔ Solo administradores.")
        amap = get_admins_map()
        if not amap:
            return await q.edit_message_text("No hay admins configurados.")
        lines = [f"• {uid} - {name}" if name else f"• {uid}" for uid, name in sorted(amap.items())]
        kb = [[InlineKeyboardButton("⬅️ Volver", callback_data="MENU:ADMIN")]]
        return await q.edit_message_text("Admins:\n" + "\n".join(lines), reply_markup=InlineKeyboardMarkup(kb))

    if data == "ADMIN:ADM_ADD":
        return await admin_add_admin_start(update, context)

    if data == "ADMIN:ADM_DEL":
        return await admin_del_admin_start(update, context)

    # --- Allowed panel actions ---
    if data == "ADMIN:LIST":
        if not (update.effective_user and update.effective_user.id in get_admin_ids()):
            return await q.edit_message_text("⛔ Solo administradores.")
        amap = get_allowed_map()
        if not amap:
            return await q.edit_message_text("Allowed vacío (el bot está libre).")
        lines = [f"• {uid} - {name}" if name else f"• {uid}" for uid, name in sorted(amap.items())]
        txt = "Allowed IDs:\n" + "\n".join(lines)
        kb = [[InlineKeyboardButton("⬅️ Volver", callback_data="MENU:ADMIN")]]
        return await q.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb))

    if data == "ADMIN:ADD":
        return await admin_add_start(update, context)

    if data == "ADMIN:DEL":
        return await admin_del_start(update, context)

    # --- Normal menu ---
    if data == "MENU:CANCEL_RESERVA":
        kb = [
            [InlineKeyboardButton("✅ Sí, liberar", callback_data="MENU:CANCEL_CONFIRM"),
             InlineKeyboardButton("❌ No", callback_data="MENU:CANCEL_KEEP")],
        ]
        return await q.edit_message_text("¿Querés liberar esta tanda y devolverla a *Pendiente*?",
                                         reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

    if data == "MENU:CANCEL_CONFIRM":
        release_reservation(context)
        return await cmd_menu(update, context)

    if data == "MENU:CANCEL_KEEP":
        base = context.user_data.get("reserved_rows", [])
        if base:
            return await show_editable_list(q, context, base, title="Cambiar estado (Pendientes)", page=0, page_size=5)
        return await cmd_menu(update, context)

    if data == "MENU:LISTA":
        rows = read_lista_any()
        return await start_list_pagination(q, context, rows, title="Lista completa", page_size=10, page=0, allow_edit=False)

    if data.startswith("MENU:FILTRO:"):
        _, _, estado = data.split(":", 2)

        if estado == "Pendiente":
            reserved = context.user_data.get("reserved_rows") or []
            if reserved:
                if not context.user_data.get("reserved_owner"):
                    try:
                        first_estado = _pad_row(reserved[0], len(CSV_HEADERS))[IDX["Estado"]].strip()
                    except Exception:
                        first_estado = ""
                    if first_estado.startswith("En contacto - "):
                        context.user_data["reserved_owner"] = first_estado.split("En contacto - ", 1)[1].strip()
                context.user_data.pop("pending_preview_keys", None)
                context.user_data.pop("pending_preview_limit", None)
                context.user_data.pop("pending_preview_indices", None)
                msg = "\n".join(_format_persona(r) for r in reserved)
                kb = [
                    [InlineKeyboardButton("✏️ Editar esta tanda", callback_data="MENU:EDIT")],
                    [InlineKeyboardButton("📱 Enviar como contactos", callback_data="MENU:SENDCONTACTS")],
                    [InlineKeyboardButton("🧹 Cancelar y liberar", callback_data="MENU:CANCEL_RESERVA")],
                    [InlineKeyboardButton("🏠 Menú", callback_data="MENU:HOME")],
                ]
                return await q.edit_message_text(
                    f"Tus pendientes asignados ({len(reserved)}):\n\n{msg}",
                    reply_markup=InlineKeyboardMarkup(kb),
                )
            all_rows = read_lista_any()
            pending_positions = _pending_positions(all_rows)
            if not pending_positions:
                context.user_data.pop("reserved_owner", None)
                context.user_data.pop("pending_preview_indices", None)
                kb = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menú", callback_data="MENU:HOME")]])
                return await q.edit_message_text("No hay personas pendientes.", reply_markup=kb)
            preview_positions = pending_positions[:5]
            preview = [row for _, row in preview_positions]
            context.user_data["pending_preview_keys"] = [_row_key(r) for r in preview]
            context.user_data["pending_preview_indices"] = [idx for idx, _ in preview_positions]
            context.user_data["pending_preview_limit"] = len(preview)
            context.user_data.pop("reserved_owner", None)
            msg = "\n".join(_format_persona(r) for r in preview)
            kb = [
                [InlineKeyboardButton("✏️ Editar esta tanda", callback_data="MENU:EDIT")],
                [InlineKeyboardButton("🏠 Menú", callback_data="MENU:HOME")],
            ]
            texto = (
                f"Próxima tanda disponible ({len(preview)}):\n\n{msg}\n\n"
                'Tocá "Editar esta tanda" para reservarla.'
            )
            return await q.edit_message_text(texto, reply_markup=InlineKeyboardMarkup(kb))
        else:
            rows = filter_by_status(read_lista_any(), estado)
            return await start_list_pagination(q, context, rows, title=f"{estado}s", page_size=10, page=0)

    if data == "MENU:SAVE5":
        from bot.handlers.edit import send_reserved_vcf
        return await send_reserved_vcf(update, context)

    if data == "MENU:SENDCONTACTS":
        from bot.handlers.edit import send_reserved_as_contacts
        return await send_reserved_as_contacts(update, context)

    if data == "MENU:EXPORT_GC":
        out = os.path.join("export", "contacts.csv")
        os.makedirs("export", exist_ok=True)
        gen_contacts_any(out)
        return await q.edit_message_text(f"✅ Generado Google Contacts: `{out}`", parse_mode="Markdown")

    if data == "MENU:VCARD":
        out = os.path.join("export", "lista.vcf")
        os.makedirs("export", exist_ok=True)
        gen_vcard_any(out, etiqueta="General")
        return await q.edit_message_text(f"✅ Generado vCard: `{out}`", parse_mode="Markdown")

    if data == "MENU:EDIT":
        base = context.user_data.get("reserved_rows")
        if not base:
            limit = context.user_data.get("pending_preview_limit") or 5
            base = _reserve_pendientes_for_user(update, context, limit=limit)
        if not base:
            return await q.edit_message_text("No hay pendientes disponibles para reservar en este momento.")
        context.user_data["edit_base_rows"] = base
        context.user_data["edit_page_size"] = 5
        context.user_data["edit_page"] = 0
        context.user_data["edit_source"] = "pendientes"
        context.user_data["edit_title"] = "Cambiar estado (Pendientes)"
        return await show_editable_list(q, context, base, title=context.user_data["edit_title"], page=0, page_size=5)

    # Fallback no-op
    return None
