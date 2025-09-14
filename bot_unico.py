# bot_unico.py — FLEX+MENU + Google Sheets + Edición de Pendientes + Alta + Reservas + Cancelación + Paginación + Export VCF
# Python 3.10+

import os
import csv
import re
import json
import logging
import unicodedata
import datetime
from io import BytesIO
from typing import List, Optional

from dotenv import load_dotenv
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

# Google Sheets
import gspread
from google.oauth2.service_account import Credentials

print("BOT_UNICO VERSION -> FLEX+MENU + SHEETS + EDIT + ADD + RESERVAS + VCF 4.2")

# ============================
# Cargar .env y logging
# ============================
load_dotenv()
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

# ============================
# Constantes y encabezados
# ============================
CSV_HEADERS = ["Nombre", "Apellido", "Teléfono", "DNI", "Estado"]
IDX = {h: i for i, h in enumerate(CSV_HEADERS)}

GOOGLE_HEADERS = [
    "Given Name",
    "Family Name",
    "Phone 1 - Value",
    "Labels",
    "Nickname",
    "Notes",
]

CSV_DEFAULT = os.environ.get("LISTA_CSV", "lista.csv").strip() or "lista.csv"
USE_SHEETS = os.environ.get("USE_SHEETS", "1").strip() != "0"

# Estados conversación /add
ADD_NOMBRE, ADD_APELLIDO, ADD_TELEFONO, ADD_DNI, ADD_ESTADO, ADD_CANCEL_CONFIRM = range(6)

# ============================
# Utilidades texto/CSV
# ============================
def _norm(s: str) -> str:
    s = s.strip()
    s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))
    return s.lower()

def _clean_phone(s: str) -> str:
    return s.strip().replace(" ", "").replace("-", "")

def _read_csv_rows(path: str) -> List[List[str]]:
    if not os.path.exists(path):
        return []
    with open(path, mode="r", encoding="utf-8-sig") as f:
        return list(csv.reader(f))

def _write_csv_rows(path: str, rows: List[List[str]]):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerows(rows)

# ============================
# Backend Google Sheets / CSV
# ============================
SCOPES = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]

def _gspread_client():
    sa_file = os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE", "").strip()
    sa_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    if sa_file:
        if not os.path.exists(sa_file):
            raise RuntimeError(f"GOOGLE_SERVICE_ACCOUNT_FILE no existe: {sa_file}")
        creds = Credentials.from_service_account_file(sa_file, scopes=SCOPES)
        return gspread.authorize(creds)
    if sa_json:
        try:
            info = json.loads(sa_json)
        except json.JSONDecodeError as e:
            raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON no es JSON válido.") from e
        creds = Credentials.from_service_account_info(info, scopes=SCOPES)
        return gspread.authorize(creds)
    raise RuntimeError("Falta GOOGLE_SERVICE_ACCOUNT_FILE o GOOGLE_SERVICE_ACCOUNT_JSON")

def _open_sheet():
    gsid = os.environ.get("GSHEET_ID")
    if not gsid:
        raise RuntimeError("Falta GSHEET_ID")
    return _gspread_client().open_by_key(gsid).sheet1

def read_lista_any() -> List[List[str]]:
    if USE_SHEETS:
        ws = _open_sheet()
        vals = ws.get_all_values()
        return vals[1:] if vals else []
    else:
        rows = _read_csv_rows(CSV_DEFAULT)
        return rows[1:] if rows else []

def set_lista_any(rows: List[List[str]]):
    if USE_SHEETS:
        ws = _open_sheet()
        ws.clear()
        ws.update("A1", [CSV_HEADERS] + rows)
    else:
        _write_csv_rows(CSV_DEFAULT, [CSV_HEADERS] + rows)

def append_contact_any(row: List[str]) -> str:
    """Inserta o actualiza por Teléfono/DNI. Devuelve 'new' o 'updated'."""
    if USE_SHEETS:
        ws = _open_sheet()
        vals = ws.get_all_values()
        if not vals:
            ws.update("A1", [CSV_HEADERS])
            ws.append_row(row)
            return "new"
        body = vals[1:]
        for i, r in enumerate(body):
            if r[IDX["Teléfono"]] == row[IDX["Teléfono"]] or (row[IDX["DNI"]] and r[IDX["DNI"]] == row[IDX["DNI"]]):
                ws.update(f"A{i+2}:E{i+2}", [row])
                return "updated"
        ws.append_row(row)
        return "new"
    else:
        rows = read_lista_any()
        for i, r in enumerate(rows):
            if r[IDX["Teléfono"]] == row[IDX["Teléfono"]] or (row[IDX["DNI"]] and r[IDX["DNI"]] == row[IDX["DNI"]]):
                rows[i] = row
                set_lista_any(rows)
                return "updated"
        rows.append(row)
        set_lista_any(rows)
        return "new"

# ============================
# Exportaciones
# ============================
def gen_contacts_any(output_csv: str) -> str:
    body = read_lista_any()
    out_rows = [GOOGLE_HEADERS]
    for row in body:
        given, family, phone, dni, labels = row
        out_rows.append([given, family, phone, labels, dni, ""])
    _write_csv_rows(output_csv, out_rows)
    return output_csv

def gen_vcard_from_rows(rows: List[List[str]], output_vcf: str, etiqueta: str = "General") -> str:
    count = 0
    os.makedirs(os.path.dirname(output_vcf) or ".", exist_ok=True)
    with open(output_vcf, "w", encoding="utf-8", newline="") as f:
        for row in rows:
            nombre = (row[IDX["Nombre"]] if len(row) > IDX["Nombre"] else "").strip()
            telefono = (row[IDX["Teléfono"]] if len(row) > IDX["Teléfono"] else "").strip()
            if not telefono:
                continue
            count += 1
            telefono_uri = re.sub(r"[^\d+]", "", telefono)
            display = f"Fiscal {etiqueta} {nombre}" if nombre else f"Fiscal {etiqueta} {count}"
            f.write("BEGIN:VCARD\n")
            f.write("VERSION:4.0\n")
            f.write(f"FN:{display}\n")
            f.write(f"TEL;TYPE=CELL;VALUE=uri:tel:{telefono_uri}\n")
            f.write("END:VCARD\n")
    return output_vcf

def gen_vcard_any(output_vcf: str, etiqueta: str = "General") -> str:
    rows = read_lista_any()
    return gen_vcard_from_rows(rows, output_vcf, etiqueta)

# ============================
# Helpers UI + paginación
# ============================
def _chunk_rows(rows, size=10):
    for i in range(0, len(rows), size):
        yield rows[i:i+size]

def _format_persona(row: List[str]) -> str:
    try:
        tel = row[IDX["Teléfono"]] if len(row) > IDX["Teléfono"] else ""
        nom = row[IDX["Nombre"]] if len(row) > IDX["Nombre"] else ""
        ape = row[IDX["Apellido"]] if len(row) > IDX["Apellido"] else ""
        est = row[IDX["Estado"]] if len(row) > IDX["Estado"] else ""
        return f"{tel}: {nom}, {ape} - {est}"
    except Exception:
        return "Fila inválida"

def filter_by_status(rows: List[List[str]], estado: str) -> List[List[str]]:
    return [r for r in rows if len(r) > IDX["Estado"] and r[IDX["Estado"]] == estado]

async def start_list_pagination(q, context, rows: List[List[str]], title: str, page_size=10, page=0):
    context.user_data["list_rows"] = rows
    context.user_data["list_title"] = title
    context.user_data["list_page_size"] = page_size
    return await show_rows_with_pagination(q, context, rows, title, page, page_size)

async def show_rows_with_pagination(q, context, rows: List[List[str]], title="Resultados", page=0, page_size=10):
    if not rows:
        return await q.edit_message_text(f"Sin resultados en *{title}*.", parse_mode="Markdown")
    pages = list(_chunk_rows(rows, page_size))
    page = max(0, min(page, len(pages)-1))
    body = [_format_persona(r) for r in pages[page]]
    kb = []
    if page > 0:
        kb.append(InlineKeyboardButton("⬅️ Anterior", callback_data=f"PAGE:{page-1}"))
    if page < len(pages)-1:
        kb.append(InlineKeyboardButton("Siguiente ➡️", callback_data=f"PAGE:{page+1}"))
    nav = [kb] if kb else []
    nav.append([InlineKeyboardButton("🏠 Menú", callback_data="MENU:HOME")])
    text = f"*{title}* (página {page+1}/{len(pages)}):\n\n" + "\n".join(body)
    return await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(nav), parse_mode="Markdown")

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
    return await show_rows_with_pagination(q, context, rows, title, page, size)

# ============================
# Reserva de pendientes (con devolución selectiva)
# ============================
def release_reservation(context: ContextTypes.DEFAULT_TYPE):
    """Devuelve a 'Pendiente' solo los reservados que aún están en 'En contacto'."""
    reserved = context.user_data.get("reserved_rows", [])
    if reserved:
        all_rows = read_lista_any()
        for r in reserved:
            for rr in all_rows:
                if rr[IDX["Teléfono"]] == r[IDX["Teléfono"]] or (
                    r[IDX["DNI"]] and rr[IDX["DNI"]] == r[IDX["DNI"]]
                ):
                    if rr[IDX["Estado"]] == "En contacto":  # solo si sigue reservado
                        rr[IDX["Estado"]] = "Pendiente"
        set_lista_any(all_rows)
        context.user_data["reserved_rows"] = []

# ============================
# Conversación ADD Contacto
# ============================
async def add_start(update_or_q, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["new_contact"] = {}
    target = update_or_q.message if getattr(update_or_q, "message", None) else update_or_q.callback_query.message
    await target.reply_text("1/5) *Nombre*:", parse_mode="Markdown", reply_markup=ReplyKeyboardRemove())
    return ADD_NOMBRE

async def add_nombre(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["new_contact"]["Nombre"] = update.message.text.strip()
    await update.message.reply_text("2/5) *Apellido*:", parse_mode="Markdown")
    return ADD_APELLIDO

async def add_apellido(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["new_contact"]["Apellido"] = update.message.text.strip()
    await update.message.reply_text("3/5) *Teléfono* (+549...):", parse_mode="Markdown")
    return ADD_TELEFONO

async def add_telefono(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["new_contact"]["Teléfono"] = _clean_phone(update.message.text)
    await update.message.reply_text("4/5) *DNI* (opcional):", parse_mode="Markdown")
    return ADD_DNI

async def add_dni(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["new_contact"]["DNI"] = update.message.text.strip()
    kb = [["Pendiente", "Aceptado", "Rechazado"]]
    await update.message.reply_text("5/5) *Estado*:", parse_mode="Markdown",
                                    reply_markup=ReplyKeyboardMarkup(kb, one_time_keyboard=True, resize_keyboard=True))
    return ADD_ESTADO

async def add_estado(update: Update, context: ContextTypes.DEFAULT_TYPE):
    est = update.message.text.strip().lower()
    estado = "Aceptado" if est.startswith("acept") else "Rechazado" if est.startswith("rech") else "Pendiente"
    d = context.user_data["new_contact"]
    row = [d.get("Nombre",""), d.get("Apellido",""), d.get("Teléfono",""), d.get("DNI",""), estado]
    res = append_contact_any(row)
    verb = "actualizado" if res == "updated" else "agregado"
    await update.message.reply_text(f"✅ Contacto {verb}\n\n{_format_persona(row)}",
                                    parse_mode="Markdown", reply_markup=ReplyKeyboardRemove())
    return await cmd_menu(update, context)  # libera reservas y vuelve al menú

async def add_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [[InlineKeyboardButton("✅ Sí, cancelar", callback_data="CANCEL:CONFIRM"),
           InlineKeyboardButton("❌ No, seguir", callback_data="CANCEL:KEEP")]]
    await update.message.reply_text("¿Seguro que querés cancelar?",
                                    reply_markup=InlineKeyboardMarkup(kb))
    return ADD_CANCEL_CONFIRM

async def on_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "CANCEL:CONFIRM":
        release_reservation(context)  # si tenía 5 reservados, los devuelve (solo los aún en "En contacto")
        return await cmd_menu(update, context)
    else:
        await q.edit_message_text("Continuemos. Repetí el dato anterior.")
        return ConversationHandler.WAITING

# ============================
# Generar y enviar VCF de la tanda reservada
# ============================
async def send_reserved_vcf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Genera un VCF con la tanda reservada y lo envía al chat."""
    q = update.callback_query
    reserved = context.user_data.get("reserved_rows", [])
    if not reserved:
        return await q.edit_message_text("No tenés una tanda reservada ahora.")
    buf = BytesIO()
    count = 0
    for row in reserved:
        nombre   = row[IDX["Nombre"]].strip() if len(row) > IDX["Nombre"] else ""
        telefono = row[IDX["Teléfono"]].strip() if len(row) > IDX["Teléfono"] else ""
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
    await q.message.reply_document(
        document=buf,
        filename=filename,
        caption="vCard con tus 5 pendientes reservados. Abrilo para importarlos a tus contactos."
    )
    await q.answer()

# (Opcional) Enviar como contactos de Telegram
async def send_reserved_as_contacts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    reserved = context.user_data.get("reserved_rows", [])
    if not reserved:
        return await q.edit_message_text("No tenés una tanda reservada ahora.")
    for row in reserved:
        first = row[IDX["Nombre"]] if len(row) > IDX["Nombre"] else ""
        last  = row[IDX["Apellido"]] if len(row) > IDX["Apellido"] else ""
        phone = row[IDX["Teléfono"]] if len(row) > IDX["Teléfono"] else ""
        if phone:
            await context.bot.send_contact(
                chat_id=q.message.chat_id,
                phone_number=phone,
                first_name=first or "Contacto",
                last_name=last or ""
            )
    await q.answer()

# ============================
# Menú principal y callbacks
# ============================
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
        [InlineKeyboardButton("✏️ Cambiar estado (Pendientes)", callback_data="MENU:EDIT")],
        [InlineKeyboardButton("➕ Agregar contacto", callback_data="MENU:ADD")],
        [InlineKeyboardButton("📤 Exportar Google Contacts (CSV)", callback_data="MENU:EXPORT_GC")],
        [InlineKeyboardButton("🪪 Generar vCard (VCF)", callback_data="MENU:VCARD")],
    ]
    text = f"Elegí una opción:\nBackend: *{backend}*"
    markup = InlineKeyboardMarkup(kb)
    if getattr(update, "callback_query", None):
        await update.callback_query.edit_message_text(text, reply_markup=markup, parse_mode="Markdown")
    elif getattr(update, "message", None):
        await update.message.reply_text(text, reply_markup=markup, parse_mode="Markdown")

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await cmd_menu(update, context)

async def on_menu_home(update: Update, context: ContextTypes.DEFAULT_TYPE):
    release_reservation(context)
    return await cmd_menu(update, context)

async def on_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data

    if data == "MENU:HOME":
        return await on_menu_home(update, context)

    if data == "MENU:CANCEL_RESERVA":
        # Confirmación de cancelación/liberación
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
        # Vuelve al editor de la misma tanda si existe, sino al menú
        base = context.user_data.get("reserved_rows", [])
        if base:
            return await show_editable_list(q, context, base, title="Cambiar estado (Pendientes)", page=0, page_size=5)
        return await cmd_menu(update, context)

    if data == "MENU:LISTA":
        rows = read_lista_any()
        return await start_list_pagination(q, context, rows, title="Lista completa", page_size=10, page=0)

    if data.startswith("MENU:FILTRO:"):
        _, _, estado = data.split(":", 2)

        if estado == "Pendiente":
            # Reserva: tomar los primeros 5 pendientes y marcarlos como "En contacto"
            all_rows = read_lista_any()
            pendientes = filter_by_status(all_rows, "Pendiente")
            if not pendientes:
                return await q.edit_message_text("No hay personas pendientes.")
            to_assign = pendientes[:5]
            for r in to_assign:
                r[IDX["Estado"]] = "En contacto"
            set_lista_any(all_rows)
            context.user_data["reserved_rows"] = to_assign
            msg = "\n".join(_format_persona(r) for r in to_assign)
            # Ofrecer opciones: editar, guardar VCF, enviar contactos, o cancelar/liberar
            kb = [
                [InlineKeyboardButton("✏️ Editar esta tanda", callback_data="MENU:EDIT")],
                [InlineKeyboardButton("📥 Guardar 5 (VCF)", callback_data="MENU:SAVE5"),
                 InlineKeyboardButton("📱 Enviar como contactos", callback_data="MENU:SENDCONTACTS")],
                [InlineKeyboardButton("🧹 Cancelar y liberar", callback_data="MENU:CANCEL_RESERVA")],
                [InlineKeyboardButton("🏠 Menú", callback_data="MENU:HOME")],
            ]
            return await q.edit_message_text(f"Tus pendientes asignados (5):\n\n{msg}",
                                             reply_markup=InlineKeyboardMarkup(kb))
        else:
            rows = filter_by_status(read_lista_any(), estado)
            return await start_list_pagination(q, context, rows, title=f"{estado}s", page_size=10, page=0)

    if data == "MENU:SAVE5":
        return await send_reserved_vcf(update, context)

    if data == "MENU:SENDCONTACTS":
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
        # Si hay reserva en memoria, editar esa; si no, editar pendientes actuales
        base = context.user_data.get("reserved_rows")
        if base:
            pendientes = base
        else:
            pendientes = filter_by_status(read_lista_any(), "Pendiente")
        context.user_data["edit_base_rows"] = pendientes
        return await show_editable_list(q, context, pendientes, title="Cambiar estado (Pendientes)", page=0, page_size=5)

# ==== Editor de Pendientes ====
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
        linea = _format_persona(row)
        body_lines.append(f"{abs_idx+1:>3}. {linea}")
        kb_rows.append([InlineKeyboardButton(f"✏️ Cambiar #{abs_idx+1}", callback_data=f"EDIT:{abs_idx}")])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ Anterior", callback_data=f"EDITPAGE:{page-1}"))
    if page < len(pages)-1:
        nav.append(InlineKeyboardButton("Siguiente ➡️", callback_data=f"EDITPAGE:{page+1}"))
    if nav:
        kb_rows.append(nav)
    # botones extra
    kb_rows.append([InlineKeyboardButton("📥 Guardar 5 (VCF)", callback_data="MENU:SAVE5"),
                    InlineKeyboardButton("📱 Enviar como contactos", callback_data="MENU:SENDCONTACTS")])
    kb_rows.append([InlineKeyboardButton("🧹 Cancelar y liberar", callback_data="MENU:CANCEL_RESERVA")])
    kb_rows.append([InlineKeyboardButton("🏠 Menú", callback_data="MENU:HOME")])
    text = f"*{title}* (página {page+1}/{len(pages)}):\n\n" + "\n".join(body_lines)
    return await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb_rows), parse_mode="Markdown")

async def on_edit_page_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    _, page_str = q.data.split(":", 1)
    page = int(page_str)
    base_rows = context.user_data.get("edit_base_rows", [])
    size = context.user_data.get("edit_page_size", 5)
    return await show_editable_list(q, context, base_rows, title="Cambiar estado (Pendientes)", page=page, page_size=size)

async def on_edit_pick_row(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    _, idx_str = q.data.split(":", 1)
    abs_idx = int(idx_str)
    base_rows = context.user_data.get("edit_base_rows", [])
    if not (0 <= abs_idx < len(base_rows)):
        return await q.edit_message_text("Índice inválido. Volvé a intentarlo desde el menú.")
    persona = _format_persona(base_rows[abs_idx])
    kb = [
        [
            InlineKeyboardButton("🟢 Aceptado", callback_data=f"SET:{abs_idx}:Aceptado"),
            InlineKeyboardButton("🔴 Rechazado", callback_data=f"SET:{abs_idx}:Rechazado"),
            InlineKeyboardButton("🟡 Pendiente", callback_data=f"SET:{abs_idx}:Pendiente"),
        ],
        [InlineKeyboardButton("📥 Guardar 5 (VCF)", callback_data="MENU:SAVE5"),
         InlineKeyboardButton("📱 Enviar como contactos", callback_data="MENU:SENDCONTACTS")],
        [InlineKeyboardButton("🧹 Cancelar y liberar", callback_data="MENU:CANCEL_RESERVA")],
        [InlineKeyboardButton("🏠 Menú", callback_data="MENU:HOME"),
         InlineKeyboardButton("↩️ Volver", callback_data=f"EDITPAGE:{context.user_data.get('edit_page',0)}")],
    ]
    return await q.edit_message_text(
        f"Elegiste:\n\n{persona}\n\n¿Nuevo estado?",
        reply_markup=InlineKeyboardMarkup(kb)
    )

async def on_edit_set_state(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    _, idx_str, nuevo = q.data.split(":", 2)
    abs_idx = int(idx_str)
    base_rows = context.user_data.get("edit_base_rows", [])
    if not (0 <= abs_idx < len(base_rows)):
        return await q.edit_message_text("Índice inválido. Volvé a intentarlo desde el menú.")
    update_estado_by_row_index(abs_index=abs_idx, nuevo_estado=nuevo, base_rows=base_rows)
    # refrescar base en memoria
    new_pendientes = filter_by_status(read_lista_any(), "Pendiente")
    context.user_data["edit_base_rows"] = new_pendientes
    page = context.user_data.get("edit_page", 0)
    size = context.user_data.get("edit_page_size", 5)
    total_pages = max(1, (len(new_pendientes) + size - 1) // size)
    if page >= total_pages:
        page = max(0, total_pages - 1)
    context.user_data["edit_page"] = page
    await q.edit_message_text(f"✅ Estado actualizado a *{nuevo}*.", parse_mode="Markdown")
    return await show_editable_list(q, context, new_pendientes, title="Cambiar estado (Pendientes)", page=page, page_size=size)

# ============================
# Edición low-level
# ============================
def _col_number_from_idx(idx0: int) -> int:
    return idx0 + 1

def _find_by_keys_fallback(all_rows: List[List[str]], target: List[str]) -> int:
    tel = target[IDX["Teléfono"]].strip()
    dni = target[IDX["DNI"]].strip()
    for i, r in enumerate(all_rows):
        if (len(r) > IDX["Teléfono"] and r[IDX["Teléfono"]].strip() == tel) or \
           (len(r) > IDX["DNI"] and dni and r[IDX["DNI"]].strip() == dni):
            return i
    return -1

def update_estado_by_row_index(abs_index: int, nuevo_estado: str, base_rows: List[List[str]]) -> None:
    if USE_SHEETS:
        all_rows = read_lista_any()
        target = base_rows[abs_index]
        try:
            real_idx = all_rows.index(target)  # 0-based en body
        except ValueError:
            real_idx = _find_by_keys_fallback(all_rows, target)
        if real_idx < 0:
            raise RuntimeError("No se encontró la fila a actualizar.")
        ws = _open_sheet()
        row = real_idx + 2  # header +1
        col = _col_number_from_idx(IDX["Estado"])
        ws.update_cell(row, col, nuevo_estado)
    else:
        rows = read_lista_any()
        target = base_rows[abs_index]
        try:
            real_idx = rows.index(target)
        except ValueError:
            real_idx = _find_by_keys_fallback(rows, target)
        if 0 <= real_idx < len(rows):
            r = rows[real_idx]
            if len(r) < len(CSV_HEADERS):
                r = (r + [""] * len(CSV_HEADERS))[:len(CSV_HEADERS)]
            r[IDX["Estado"]] = nuevo_estado
            rows[real_idx] = r
            set_lista_any(rows)

# ============================
# Comandos “texto”
# ============================
async def cmd_get_lista(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = read_lista_any()
    if not rows:
        return await update.message.reply_text("La lista está vacía.")
    block = []
    for i, r in enumerate(rows, 1):
        block.append(_format_persona(r))
        if i % 20 == 0:
            await update.message.reply_text("\n".join(block))
            block = []
    if block:
        await update.message.reply_text("\n".join(block))

async def _send_list_by_status(update: Update, rows: List[List[str]], titulo: str):
    if not rows:
        return await update.message.reply_text(f"No hay personas {titulo.lower()}.")
    await update.message.reply_text(f"Esta es la lista de personas {titulo.lower()}:")
    block = []
    for i, r in enumerate(rows, 1):
        block.append(f"{r[IDX['Teléfono']]}: {r[IDX['Nombre']]}, {r[IDX['Apellido']]}")
        if i % 20 == 0:
            await update.message.reply_text("\n".join(block))
            block = []
    if block:
        await update.message.reply_text("\n".join(block))

async def cmd_get_pendientes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Asigna 5 y marca "En contacto"
    all_rows = read_lista_any()
    pendientes = filter_by_status(all_rows, "Pendiente")
    if not pendientes:
        return await update.message.reply_text("No hay personas pendientes.")
    to_assign = pendientes[:5]
    for r in to_assign:
        r[IDX["Estado"]] = "En contacto"
    set_lista_any(all_rows)
    context.user_data["reserved_rows"] = to_assign
    msg = "\n".join(f"{r[IDX['Teléfono']]}: {r[IDX['Nombre']]}, {r[IDX['Apellido']]}" for r in to_assign)
    await update.message.reply_text(f"Estos son tus pendientes asignados:\n\n{msg}")

async def cmd_get_aceptados(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = read_lista_any()
    return await _send_list_by_status(update, filter_by_status(rows, "Aceptado"), "Aceptadas")

async def cmd_get_rechazados(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = read_lista_any()
    return await _send_list_by_status(update, filter_by_status(rows, "Rechazado"), "Rechazadas")

async def cmd_gen_contacts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    out = os.path.join("export", "contacts.csv")
    os.makedirs("export", exist_ok=True)
    gen_contacts_any(out)
    await update.message.reply_text(f"Archivo escrito: {out}")

async def cmd_vcard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    out = os.path.join("export", "lista.vcf")
    os.makedirs("export", exist_ok=True)
    gen_vcard_any(out, etiqueta="General")
    await update.message.reply_text(f"Archivo escrito: {out}")

# ============================
# Errores
# ============================
async def handle_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    logging.exception("Excepción en handler", exc_info=context.error)
    try:
        if isinstance(update, Update) and update.effective_chat:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="⚠️ Ocurrió un error procesando tu pedido. Revisá logs."
            )
    except Exception:
        pass

# ============================
# Main
# ============================
def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("Falta TELEGRAM_BOT_TOKEN.")
    mode = os.environ.get("TG_MODE", "polling").strip().lower()

    app = ApplicationBuilder().token(token).build()

    # Conversación ADD (debe registrarse ANTES que el handler genérico de MENU para capturar MENU:ADD)
    add_conv = ConversationHandler(
        entry_points=[
            CommandHandler("add", add_start),
            CallbackQueryHandler(add_start, pattern="^MENU:ADD$"),
        ],
        states={
            ADD_NOMBRE:   [MessageHandler(filters.TEXT & ~filters.COMMAND, add_nombre)],
            ADD_APELLIDO: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_apellido)],
            ADD_TELEFONO: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_telefono)],
            ADD_DNI:      [MessageHandler(filters.TEXT & ~filters.COMMAND, add_dni)],
            ADD_ESTADO:   [MessageHandler(filters.TEXT & ~filters.COMMAND, add_estado)],
            ADD_CANCEL_CONFIRM: [CallbackQueryHandler(on_cancel_callback, pattern="^CANCEL:")],
        },
        fallbacks=[CommandHandler("cancel", add_cancel)],
        name="add_contact_conv",
        persistent=False,
    )
    app.add_handler(add_conv)

    # Menú + callbacks
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("menu", cmd_menu))
    app.add_handler(CallbackQueryHandler(on_menu_callback, pattern=r"^MENU:"))
    app.add_handler(CallbackQueryHandler(on_page_callback, pattern=r"^PAGE:\d+$"))

    # Editor de pendientes
    app.add_handler(CallbackQueryHandler(on_edit_page_callback, pattern=r"^EDITPAGE:\d+$"))
    app.add_handler(CallbackQueryHandler(on_edit_pick_row,   pattern=r"^EDIT:\d+$"))
    app.add_handler(CallbackQueryHandler(on_edit_set_state,  pattern=r"^SET:\d+:(Aceptado|Rechazado|Pendiente)$"))

    # Comandos clásicos
    app.add_handler(CommandHandler("get_lista", cmd_get_lista))
    app.add_handler(CommandHandler("get_pendientes", cmd_get_pendientes))
    app.add_handler(CommandHandler("get_aceptados", cmd_get_aceptados))
    app.add_handler(CommandHandler("get_rechazados", cmd_get_rechazados))
    app.add_handler(CommandHandler("gen_contacts", cmd_gen_contacts))
    app.add_handler(CommandHandler("vcard", cmd_vcard))

    app.add_error_handler(handle_error)

    # Polling simple por defecto (si usás webhook en Render, esto respeta TG_MODE)
    if mode == "webhook":
        port = int(os.environ.get("PORT", "10000"))
        public_url = (os.environ.get("PUBLIC_URL")
                      or os.environ.get("RENDER_EXTERNAL_URL")
                      or "").rstrip("/")
        if not public_url:
            logging.warning("No hay PUBLIC_URL/RENDER_EXTERNAL_URL; cambiando a polling automáticamente.")
            mode = "polling"

    if mode == "webhook":
        webhook_path = "/" + os.environ.get("WEBHOOK_PATH", token)
        webhook_url = f"{public_url}{webhook_path}"
        app.run_webhook(
            listen="0.0.0.0",
            port=port,
            url_path=webhook_path,
            webhook_url=webhook_url,
            drop_pending_updates=True,
            allowed_updates=Update.ALL_TYPES,
        )
    else:
        app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

if __name__ == "__main__":
    main()
