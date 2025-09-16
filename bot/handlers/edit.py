import datetime
import re
from io import BytesIO
from typing import List

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import ContextTypes, ConversationHandler

from bot.auth import require_auth, get_display_for_uid
from bot.config import CSV_HEADERS, IDX
from bot.services.lista import (
    read_lista_any,
    set_lista_any,
    filter_by_status,
    _pad_row,
    update_estado_by_row_index,
)
from bot.utils.pagination import _chunk_rows, _format_persona


def _estado_es_en_contacto(valor: str) -> bool:
    from bot.services.lista import _norm
    return _norm(valor).startswith("en contacto")


def _find_row_by_keys(all_rows, target):
    target = _pad_row(target, len(CSV_HEADERS))
    tel = target[IDX["Teléfono"]].strip() if len(target) > IDX["Teléfono"] else ""
    dni = target[IDX["DNI"]].strip() if len(target) > IDX["DNI"] else ""
    for index, candidate in enumerate(all_rows):
        padded = _pad_row(candidate, len(CSV_HEADERS))
        if padded[IDX["Teléfono"]].strip() == tel or (dni and padded[IDX["DNI"]].strip() == dni):
            return index, padded
    return -1, None


def _active_reserved_rows(context: ContextTypes.DEFAULT_TYPE, all_rows):
    reserved = context.user_data.get("reserved_rows", [])
    reserved_indices = context.user_data.get("reserved_indices") or []
    if not reserved and not reserved_indices:
        return []
    owner = context.user_data.get("reserved_owner")
    active_rows = []
    active_indices = []

    def _include_by_index(abs_idx: int) -> None:
        nonlocal owner
        if not (0 <= abs_idx < len(all_rows)):
            return
        padded = _pad_row(all_rows[abs_idx], len(CSV_HEADERS))
        estado = padded[IDX["Estado"]].strip()
        if not _estado_es_en_contacto(estado):
            return
        if owner:
            if not estado.startswith(f"En contacto - {owner}"):
                return
        else:
            if estado.startswith("En contacto - "):
                owner = estado.split("En contacto - ", 1)[1].strip()
                context.user_data["reserved_owner"] = owner
        active_rows.append(padded)
        active_indices.append(abs_idx)
        all_rows[abs_idx] = padded

    for abs_idx in reserved_indices:
        _include_by_index(abs_idx)

    if not active_rows and reserved:
        for cached in reserved:
            idx, current = _find_row_by_keys(all_rows, cached)
            if idx < 0 or current is None:
                continue
            all_rows[idx] = current
            _include_by_index(idx)

    context.user_data["reserved_rows"] = active_rows
    context.user_data["reserved_indices"] = active_indices
    if not active_rows:
        context.user_data.pop("reserved_owner", None)
    return active_rows


def release_reservation(context: ContextTypes.DEFAULT_TYPE):
    """Devuelve a 'Pendiente' solo los reservados que aún están en 'En contacto*'."""
    reserved = context.user_data.get("reserved_rows", [])
    reserved_indices = context.user_data.get("reserved_indices") or []
    if not reserved and not reserved_indices:
        context.user_data.pop("reserved_owner", None)
        context.user_data.pop("reserved_indices", None)
        return
    owner = context.user_data.get("reserved_owner")
    all_rows = read_lista_any()
    changed = False
    processed = set()

    def _release_at_index(abs_idx, owner_hint):
        nonlocal owner, changed
        if abs_idx in processed or not (0 <= abs_idx < len(all_rows)):
            return
        padded = _pad_row(all_rows[abs_idx], len(CSV_HEADERS))
        estado_actual = padded[IDX["Estado"]].strip()
        if not _estado_es_en_contacto(estado_actual):
            return
        current_owner = owner_hint or owner
        if current_owner:
            if not estado_actual.startswith(f"En contacto - {current_owner}"):
                return
        else:
            if estado_actual.startswith("En contacto - "):
                current_owner = estado_actual.split("En contacto - ", 1)[1].strip()
                owner = current_owner
                context.user_data["reserved_owner"] = current_owner
        padded[IDX["Estado"]] = "Pendiente"
        padded[IDX["Observación"]] = ""
        all_rows[abs_idx] = padded
        processed.add(abs_idx)
        changed = True

    for abs_idx in reserved_indices:
        _release_at_index(abs_idx, owner)

    if reserved:
        for cached in reserved:
            idx, current = _find_row_by_keys(all_rows, cached)
            if idx < 0 or current is None or idx in processed:
                continue
            owner_hint = owner
            if not owner_hint:
                cached_padded = _pad_row(cached, len(CSV_HEADERS))
                cached_estado = cached_padded[IDX["Estado"]].strip()
                if cached_estado.startswith("En contacto - "):
                    owner_hint = cached_estado.split("En contacto - ", 1)[1].strip()
            all_rows[idx] = current
            _release_at_index(idx, owner_hint)

    if changed:
        set_lista_any(all_rows)
    context.user_data["reserved_rows"] = []
    context.user_data.pop("reserved_owner", None)
    context.user_data.pop("reserved_indices", None)


# ==== Editor de Pendientes ====

# IMPORTANTE: NO decorar con @require_auth — esta función recibe un CallbackQuery, no un Update
async def show_editable_list(q, context, rows: List[List[str]], title="Cambiar estado", page=0, page_size=5):
    total = len(rows)
    if total == 0:
        return await q.edit_message_text("No hay pendientes para editar.")
    context.user_data["edit_page_size"] = page_size
    pages = list(_chunk_rows(rows, page_size))
    page = max(0, min(page, len(pages)-1))
    context.user_data["edit_page"] = page
    start_index = page * page_size
    body_lines = []
    kb_rows = []
    for i, row in enumerate(pages[page]):
        abs_idx = start_index + i
        linea = _format_persona(_pad_row(row, len(CSV_HEADERS)))
        body_lines.append(f"{abs_idx+1:>3}. {linea}")
        kb_rows.append([InlineKeyboardButton(f"✏️ Cambiar #{abs_idx+1}", callback_data=f"EDIT:{abs_idx}")])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ Anterior", callback_data=f"EDITPAGE:{page-1}"))
    if page < len(pages)-1:
        nav.append(InlineKeyboardButton("Siguiente ➡️", callback_data=f"EDITPAGE:{page+1}"))
    if nav:
        kb_rows.append(nav)
    kb_rows.append([InlineKeyboardButton("🧹 Cancelar y liberar", callback_data="MENU:CANCEL_RESERVA")])
    kb_rows.append([InlineKeyboardButton("↩️ Volver", callback_data="MENU:HOME"),
                    InlineKeyboardButton("🏠 Menú", callback_data="MENU:HOME")])
    text = f"*{title}* (página {page+1}/{len(pages)}):\n\n" + "\n".join(body_lines)
    return await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb_rows), parse_mode="Markdown")


@require_auth
async def on_edit_page_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    _, page_str = q.data.split(":", 1)
    page = int(page_str)
    base_rows = context.user_data.get("edit_base_rows", [])
    size = context.user_data.get("edit_page_size", 5)
    title = context.user_data.get("edit_title", "Cambiar estado")
    return await show_editable_list(q, context, base_rows, title=title, page=page, page_size=size)


@require_auth
async def on_edit_pick_row(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    _, idx_str = q.data.split(":", 1)
    abs_idx = int(idx_str)
    base_rows = context.user_data.get("edit_base_rows", [])
    if not (0 <= abs_idx < len(base_rows)):
        return await q.edit_message_text("Índice inválido. Volvé a intentarlo desde el menú.")
    # Guardamos el índice seleccionado para acciones posteriores (enviar contacto/VCF)
    context.user_data["edit_selected_idx"] = abs_idx
    persona = _format_persona(_pad_row(base_rows[abs_idx], len(CSV_HEADERS)))
    kb = [
        [
            InlineKeyboardButton("🟢 Aceptado", callback_data=f"SET:{abs_idx}:Aceptado"),
            InlineKeyboardButton("🔴 Rechazado", callback_data=f"SET:{abs_idx}:Rechazado"),
            InlineKeyboardButton("🟡 Pendiente", callback_data=f"SET:{abs_idx}:Pendiente"),
        ],
        [
            InlineKeyboardButton("📵 Número incorrecto", callback_data=f"SET:{abs_idx}:Número incorrecto"),
            InlineKeyboardButton("🕓 Contactar Luego", callback_data=f"SET:{abs_idx}:Contactar Luego"),
        ],
        [InlineKeyboardButton("📱 Enviar como contactos", callback_data="MENU:SENDCONTACTS")],
        [InlineKeyboardButton("🧹 Cancelar y liberar", callback_data="MENU:CANCEL_RESERVA")],
        [InlineKeyboardButton("🏠 Menú", callback_data="MENU:HOME"),
         InlineKeyboardButton("↩️ Volver", callback_data=f"EDITPAGE:{context.user_data.get('edit_page',0)}")],
    ]
    return await q.edit_message_text(
        f"Elegiste:\n\n{persona}\n\n¿Nuevo estado?",
        reply_markup=InlineKeyboardMarkup(kb)
    )


@require_auth
async def on_edit_set_state(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    _, idx_str, nuevo = q.data.split(":", 2)
    abs_idx = int(idx_str)
    base_rows = context.user_data.get("edit_base_rows", [])
    if not (0 <= abs_idx < len(base_rows)):
        return await q.edit_message_text("Índice inválido. Volvé a intentarlo desde el menú.")

    if nuevo == "Contactar Luego":
        from bot.states import EDIT_OBS
        context.user_data["obs_target_index"] = abs_idx
        await q.edit_message_text(
            "Escribí la *observación* para 'Contactar Luego':", parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Cancelar", callback_data="OBS:CANCEL")],
                [InlineKeyboardButton("↩️ Volver", callback_data="OBS:CANCEL")],
            ])
        )
        return EDIT_OBS

    update_estado_by_row_index(abs_index=abs_idx, nuevo_estado=nuevo, base_rows=base_rows)
    source = context.user_data.get("edit_source", "pendientes")
    all_rows = read_lista_any()
    if source == "list":
        new_rows = all_rows
        context.user_data["edit_title"] = context.user_data.get("edit_title", "Cambiar estado (Lista)")
        size = context.user_data.get("edit_page_size", 10)
    else:
        new_rows = _active_reserved_rows(context, all_rows)
        context.user_data["edit_title"] = "Cambiar estado (Pendientes)"
        size = context.user_data.get("edit_page_size", 5)
    context.user_data["edit_base_rows"] = new_rows
    page = context.user_data.get("edit_page", 0)
    total_pages = max(1, (len(new_rows) + size - 1) // size)
    if page >= total_pages:
        page = max(0, total_pages - 1)
    context.user_data["edit_page"] = page
    await q.edit_message_text(f"✅ Estado actualizado a *{nuevo}*.", parse_mode="Markdown")
    return await show_editable_list(q, context, new_rows, title=context.user_data.get("edit_title", "Cambiar estado"), page=page, page_size=size)


# === Conversación de observación para "Contactar Luego"
@require_auth
async def obs_cancel_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await q.edit_message_text("Operación cancelada.")
    base = context.user_data.get("edit_base_rows", [])
    title = context.user_data.get("edit_title", "Cambiar estado")
    return await show_editable_list(q, context, base, title=title, page=context.user_data.get("edit_page",0), page_size=context.user_data.get("edit_page_size",5))


@require_auth
async def obs_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    obs = (update.message.text or "").strip()
    base_rows = context.user_data.get("edit_base_rows", [])
    idx = context.user_data.get("obs_target_index", None)
    if idx is None or not (0 <= idx < len(base_rows)):
        await update.message.reply_text("No se encontró el elemento. Volvé al menú.")
        return ConversationHandler.END
    update_estado_by_row_index(abs_index=idx, nuevo_estado="Contactar Luego", base_rows=base_rows, observacion=obs)
    context.user_data.pop("obs_target_index", None)
    source = context.user_data.get("edit_source", "pendientes")
    all_rows = read_lista_any()
    if source == "list":
        new_rows = all_rows
        context.user_data["edit_title"] = context.user_data.get("edit_title", "Cambiar estado (Lista)")
        size = context.user_data.get("edit_page_size", 10)
    else:
        new_rows = _active_reserved_rows(context, all_rows)
        context.user_data["edit_title"] = "Cambiar estado (Pendientes)"
        size = context.user_data.get("edit_page_size", 5)
    context.user_data["edit_base_rows"] = new_rows
    page = context.user_data.get("edit_page", 0)
    total_pages = max(1, (len(new_rows) + size - 1) // size)
    if page >= total_pages:
        page = max(0, total_pages - 1)
    context.user_data["edit_page"] = page
    await update.message.reply_text("✅ Guardado con 'Contactar Luego' y observación.")
    q_like = type("Q", (), {"edit_message_text": update.message.reply_text})
    return await show_editable_list(q_like, context, new_rows, title=context.user_data.get("edit_title", "Cambiar estado"), page=page, page_size=size)


# ============================
# Generar y enviar VCF de la tanda reservada
# ============================
@require_auth
async def send_reserved_vcf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    reserved = context.user_data.get("reserved_rows", [])

    # Fallbacks: contacto seleccionado, editor actual o primeras 5 pendientes
    rows_to_export = list(reserved)
    if not rows_to_export:
        base_rows = context.user_data.get("edit_base_rows", [])
        sel_idx = context.user_data.get("edit_selected_idx")
        if isinstance(sel_idx, int) and 0 <= sel_idx < len(base_rows):
            rows_to_export = [base_rows[sel_idx]]
    if not rows_to_export:
        edit_rows = context.user_data.get("edit_base_rows", [])
        page = context.user_data.get("edit_page", 0)
        size = context.user_data.get("edit_page_size", 5)
        if edit_rows:
            start = page * size
            rows_to_export = edit_rows[start:start + 5]
        else:
            all_rows = read_lista_any()
            pendientes = filter_by_status(all_rows, "Pendiente")
            rows_to_export = pendientes[:5]

    if not rows_to_export:
        return await q.edit_message_text("No hay contactos disponibles para exportar.")

    buf = BytesIO()
    count = 0
    for row in rows_to_export:
        row = _pad_row(row, len(CSV_HEADERS))
        nombre = row[IDX["Nombre"]].strip()
        telefono = row[IDX["Teléfono"]].strip()
        if not telefono:
            continue
        count += 1
        telefono_uri = re.sub(r"[^\d+]", "", telefono)
        display = nombre if nombre else f"Pendiente {count}"
        buf.write(b"BEGIN:VCARD\n")
        buf.write(b"VERSION:4.0\n")
        buf.write(f"FN:{display}\n".encode("utf-8"))
        buf.write(f"TEL;TYPE=CELL;VALUE=uri:tel:{telefono_uri}\n".encode("utf-8"))
        buf.write(b"END:VCARD\n")
    if buf.tell() == 0:
        return await q.edit_message_text("No hay teléfonos válidos para exportar.")
    buf.seek(0)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M")
    filename = f"pendientes_{ts}.vcf"
    try:
        await q.message.reply_document(
            document=InputFile(buf, filename),
            caption="vCard con tus pendientes seleccionados. Abrilo para importarlos a tus contactos."
        )
    except Exception as e:
        return await q.edit_message_text(f"No se pudo enviar el VCF: {e}")
    await q.answer()


@require_auth
async def send_reserved_as_contacts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    reserved = context.user_data.get("reserved_rows", [])
    rows_to_send = list(reserved)
    if not rows_to_send:
        base_rows = context.user_data.get("edit_base_rows", [])
        sel_idx = context.user_data.get("edit_selected_idx")
        if isinstance(sel_idx, int) and 0 <= sel_idx < len(base_rows):
            rows_to_send = [base_rows[sel_idx]]
    if not rows_to_send:
        return await q.edit_message_text("No tenés una tanda reservada ni un contacto seleccionado.")
    for row in rows_to_send:
        row = _pad_row(row, len(CSV_HEADERS))
        first = row[IDX["Nombre"]]
        last = row[IDX["Apellido"]]
        phone = row[IDX["Teléfono"]]
        if phone:
            await context.bot.send_contact(
                chat_id=q.message.chat_id,
                phone_number=phone,
                first_name=first or "Contacto",
                last_name=last or ""
            )
    await q.answer()

