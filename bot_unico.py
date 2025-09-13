# bot_unico.py — FLEX+MENU + Google Sheets + Edición de Pendientes + /add con upsert
# Python 3.10+

import os
import csv
import re
import json
import logging
import unicodedata
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

print("BOT_UNICO VERSION -> FLEX+MENU + SHEETS + EDIT PENDIENTES + ADD/UPSERT 1.3")

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

# Estados para /add
ADD_NOMBRE, ADD_APELLIDO, ADD_TELEFONO, ADD_DNI, ADD_ESTADO = range(5)

# ============================
# Utilidades texto/CSV
# ============================
def _norm(s: str) -> str:
    s = s.strip()
    s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))
    return s.lower()

def _canon_phone(s: str) -> str:
    """Solo dígitos para comparar, ignora +, espacios y guiones."""
    return re.sub(r"\D", "", s or "")

def _clean_phone(s: str) -> str:
    if not s:
        return ""
    s = s.strip().replace(" ", "").replace("-", "")
    return s

def _read_csv_rows(path: str) -> List[List[str]]:
    if not os.path.exists(path):
        return []
    with open(path, mode="r", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        return [row for row in reader]

def _write_csv_rows(path: str, rows: List[List[str]]):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, mode="w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerows(rows)

def _header_mapping(actual: List[str]) -> dict[str, Optional[int]]:
    norm_actual = [_norm(h) for h in actual]
    pos = {h: i for i, h in enumerate(norm_actual)}

    wanted = {
        "Nombre":   ("nombre",),
        "Apellido": ("apellido",),
        "Teléfono": ("telefono", "teléfono", "telefono celular", "tel"),
        "DNI":      ("dni", "documento", "doc", "email"),
        "Estado":   ("estado", "etiquetas", "status", "label"),
    }

    mapping: dict[str, Optional[int]] = {}
    for target, aliases in wanted.items():
        found = next((pos[a] for a in aliases if a in pos), None)
        if found is None and target not in ("DNI", "Estado"):
            raise ValueError(f"Falta columna requerida para '{target}'. Encabezados: {actual}")
        mapping[target] = found
    return mapping

# ============================
# Backend CSV
# ============================
def read_lista_csv(csv_path: str) -> List[List[str]]:
    rows = _read_csv_rows(csv_path)
    if not rows:
        return []
    if rows[0] == CSV_HEADERS:
        return rows[1:]

    mapping = _header_mapping(rows[0])
    out: List[List[str]] = []
    for r in rows[1:]:
        def get(idx: Optional[int]) -> str:
            return r[idx].strip() if (idx is not None and idx < len(r)) else ""
        nombre   = get(mapping["Nombre"])
        apellido = get(mapping["Apellido"])
        telefono = get(mapping["Teléfono"])
        dni      = get(mapping["DNI"])
        estado   = get(mapping["Estado"])
        estn = _norm(estado)
        if estn.startswith("acept"):
            estado = "Aceptado"
        elif estn.startswith("rech"):
            estado = "Rechazado"
        else:
            estado = "Pendiente"
        out.append([nombre, apellido, telefono, dni, estado])
    return out

def set_lista_csv(csv_path: str, body_rows: List[List[str]]):
    _write_csv_rows(csv_path, [CSV_HEADERS] + body_rows)

# ============================
# Backend Google Sheets
# ============================
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

def _gspread_client():
    sa_file = os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE", "").strip()
    sa_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()

    if sa_file:
        if not os.path.exists(sa_file):
            raise RuntimeError(f"GOOGLE_SERVICE_ACCOUNT_FILE apunta a un archivo que no existe: {sa_file}")
        creds = Credentials.from_service_account_file(sa_file, scopes=SCOPES)
        return gspread.authorize(creds)

    if sa_json:
        try:
            info = json.loads(sa_json)
        except json.JSONDecodeError as e:
            raise RuntimeError(
                "GOOGLE_SERVICE_ACCOUNT_JSON no es un JSON válido "
                "(si pegaste un nombre de archivo, usá GOOGLE_SERVICE_ACCOUNT_FILE)."
            ) from e
        creds = Credentials.from_service_account_info(info, scopes=SCOPES)
        return gspread.authorize(creds)

    raise RuntimeError("Falta GOOGLE_SERVICE_ACCOUNT_FILE o GOOGLE_SERVICE_ACCOUNT_JSON")

def _open_sheet():
    gsid = os.environ.get("GSHEET_ID")
    if not gsid:
        raise RuntimeError("Falta GSHEET_ID (ID del Google Sheet)")
    gc = _gspread_client()
    sh = gc.open_by_key(gsid)
    return sh.sheet1  # primera pestaña

def read_lista_sheet() -> List[List[str]]:
    ws = _open_sheet()
    rows = ws.get_all_values()
    if not rows:
        return []
    header = rows[0]
    body = rows[1:]
    if header == CSV_HEADERS:
        return body

    mapping = _header_mapping(header)
    out: List[List[str]] = []
    for r in body:
        def get(i: Optional[int]) -> str:
            return r[i].strip() if (i is not None and i < len(r)) else ""
        nombre   = get(mapping["Nombre"])
        apellido = get(mapping["Apellido"])
        telefono = get(mapping["Teléfono"])
        dni      = get(mapping["DNI"])
        estado   = get(mapping["Estado"])
        estn = _norm(estado)
        if estn.startswith("acept"):
            estado = "Aceptado"
        elif estn.startswith("rech"):
            estado = "Rechazado"
        else:
            estado = "Pendiente"
        out.append([nombre, apellido, telefono, dni, estado])
    return out

def set_lista_sheet(body_rows: List[List[str]]) -> None:
    ws = _open_sheet()
    data = [CSV_HEADERS] + body_rows
    ws.clear()
    ws.update("A1", data)

# ============================
# Facade: seleccionar backend
# ============================
def read_lista_any() -> List[List[str]]:
    if USE_SHEETS:
        return read_lista_sheet()
    return read_lista_csv(CSV_DEFAULT)

def set_lista_any(rows: List[List[str]]) -> None:
    if USE_SHEETS:
        set_lista_sheet(rows)
    else:
        set_lista_csv(CSV_DEFAULT, rows)

def filter_by_status(rows: List[List[str]], estado: str) -> List[List[str]]:
    return [r for r in rows if len(r) > IDX["Estado"] and r[IDX["Estado"]] == estado]

# ============================
# UPSERT (evita duplicados por Teléfono o DNI)
# ============================
def find_row_index_by_keys(all_rows: List[List[str]], tel: str, dni: str) -> int:
    ct = _canon_phone(tel)
    cd = (dni or "").strip()
    for i, r in enumerate(all_rows):
        rt = _canon_phone(r[IDX["Teléfono"]] if len(r) > IDX["Teléfono"] else "")
        rd = (r[IDX["DNI"]] if len(r) > IDX["DNI"] else "").strip()
        if (ct and rt and ct == rt) or (cd and rd and cd == rd):
            return i
    return -1

def upsert_contact_any(row: List[str]) -> str:
    """
    row = [Nombre, Apellido, Teléfono, DNI, Estado]
    Si ya existe por Teléfono o DNI -> actualiza toda la fila.
    Si no existe -> agrega.
    Devuelve "updated" o "inserted".
    """
    nombre, apellido, telefono, dni, estado = row
    if USE_SHEETS:
        ws = _open_sheet()
        vals = ws.get_all_values()
        if not vals:
            ws.update("A1", [CSV_HEADERS])
            vals = [CSV_HEADERS]
        body = vals[1:] if len(vals) >= 1 else []
        idx = find_row_index_by_keys(body, telefono, dni)
        if idx >= 0:
            # update en la fila real
            real_row = idx + 2  # +1 (base-1) +1 encabezado
            ws.update(f"A{real_row}:E{real_row}", [row])
            return "updated"
        else:
            ws.append_row(row, value_input_option="RAW")
            return "inserted"
    else:
        body = read_lista_csv(CSV_DEFAULT)
        idx = find_row_index_by_keys(body, telefono, dni)
        if idx >= 0:
            body[idx] = row
            set_lista_csv(CSV_DEFAULT, body)
            return "updated"
        else:
            body.append(row)
            set_lista_csv(CSV_DEFAULT, body)
            return "inserted"

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
# Bot: helpers UI
# ============================
def _chunk_rows(rows: List[List[str]], size: int = 10):
    for i in range(0, len(rows), size):
        yield rows[i:i+size]

def _format_persona(row: List[str]) -> str:
    try:
        tel = row[IDX["Teléfono"]] if len(row) > IDX["Teléfono"] else ""
        nom = row[IDX["Nombre"]]   if len(row) > IDX["Nombre"]   else ""
        ape = row[IDX["Apellido"]] if len(row) > IDX["Apellido"] else ""
        est = row[IDX["Estado"]]   if len(row) > IDX["Estado"]   else ""
        return f"{tel}: {nom}, {ape} - {est}"
    except Exception:
        return "Fila inválida"

# ============================
# EDITAR ESTADO (solo Pendientes)
# ============================
def _col_number_from_idx(idx0: int) -> int:
    return idx0 + 1

def _find_by_keys_fallback(all_rows: List[List[str]], target: List[str]) -> int:
    tel = target[IDX["Teléfono"]].strip()
    dni = target[IDX["DNI"]].strip()
    ct = _canon_phone(tel)
    for i, r in enumerate(all_rows):
        rt = _canon_phone(r[IDX["Teléfono"]] if len(r) > IDX["Teléfono"] else "")
        rd = (r[IDX["DNI"]] if len(r) > IDX["DNI"] else "").strip()
        if (ct and rt and ct == rt) or (dni and rd and dni == rd):
            return i
    return -1

def update_estado_by_row_index(abs_index: int, nuevo_estado: str, base_rows: List[List[str]]) -> None:
    if USE_SHEETS:
        all_rows = read_lista_sheet()
        target = base_rows[abs_index]
        try:
            real_idx = all_rows.index(target)  # 0-based
        except ValueError:
            real_idx = _find_by_keys_fallback(all_rows, target)
        if real_idx < 0:
            raise RuntimeError("No se encontró la fila a actualizar (puede haber sido modificada).")
        ws = _open_sheet()
        row = real_idx + 2
        col = _col_number_from_idx(IDX["Estado"])
        ws.update_cell(row, col, nuevo_estado)
    else:
        rows = read_lista_csv(CSV_DEFAULT)
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
            set_lista_csv(CSV_DEFAULT, rows)

# ============================
# Bot: comandos y callbacks
# ============================
async def cmd_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=markup, parse_mode="Markdown")
        return
    if update.message:
        await update.message.reply_text(text, reply_markup=markup, parse_mode="Markdown")
        return
    chat_id = update.effective_chat.id if update.effective_chat else None
    if chat_id:
        await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=markup, parse_mode="Markdown")

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await cmd_menu(update, context)

async def on_menu_home(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await cmd_menu(update, context)

async def on_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data

    if data == "MENU:LISTA":
        rows = read_lista_any()
        return await show_rows_with_pagination(q, context, rows, title="Lista completa")

    if data.startswith("MENU:FILTRO:"):
        _, _, estado = data.split(":", 2)
        rows = filter_by_status(read_lista_any(), estado)
        return await show_rows_with_pagination(q, context, rows, title=f"{estado}s")

    if data == "MENU:EXPORT_GC":
        out = os.path.join("export", "contacts.csv")
        gen_contacts_any(out)
        return await q.edit_message_text(f"✅ Generado Google Contacts: `{out}`", parse_mode="Markdown")

    if data == "MENU:VCARD":
        out = os.path.join("export", "lista.vcf")
        gen_vcard_any(out, etiqueta="General")
        return await q.edit_message_text(f"✅ Generado vCard: `{out}`", parse_mode="Markdown")

    if data == "MENU:EDIT":
        pendientes = filter_by_status(read_lista_any(), "Pendiente")
        context.user_data["edit_base_rows"] = pendientes
        return await show_editable_list(q, context, pendientes, title="Cambiar estado (Pendientes)", page=0, page_size=5)

    if data == "MENU:ADD":
        return await q.edit_message_text(
            "Para agregar un contacto, escribí el comando:\n\n*/add*\n\nTe voy a pedir los datos paso a paso.",
            parse_mode="Markdown"
        )

async def show_rows_with_pagination(q, context, rows: List[List[str]], title="Resultados", page=0, page_size=10):
    total = len(rows)
    if total == 0:
        return await q.edit_message_text(f"Sin resultados en *{title}*.", parse_mode="Markdown")

    pages = list(_chunk_rows(rows, page_size))
    page = max(0, min(page, len(pages)-1))

    body = [_format_persona(r) for r in pages[page]]

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ Anterior", callback_data=f"PAGE:{page-1}"))
    if page < len(pages)-1:
        nav.append(InlineKeyboardButton("Siguiente ➡️", callback_data=f"PAGE:{page+1}"))

    kb = [nav] if nav else []
    kb.append([InlineKeyboardButton("🏠 Menú", callback_data="MENU:HOME")])

    text = f"*{title}* (página {page+1}/{len(pages)}):\n\n" + "\n".join(body)
    return await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

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

    update_estado_by_row_index(abs_idx, nuevo, base_rows)

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
# Comandos “texto” clásicos
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
    rows = read_lista_any()
    return await _send_list_by_status(update, filter_by_status(rows, "Pendiente"), "Pendientes")

async def cmd_get_aceptados(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = read_lista_any()
    return await _send_list_by_status(update, filter_by_status(rows, "Aceptado"), "Aceptadas")

async def cmd_get_rechazados(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = read_lista_any()
    return await _send_list_by_status(update, filter_by_status(rows, "Rechazado"), "Rechazadas")

async def cmd_gen_contacts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    out = os.path.join("export", "contacts.csv")
    gen_contacts_any(out)
    await update.message.reply_text(f"Archivo escrito: {out}")

async def cmd_vcard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    out = os.path.join("export", "lista.vcf")
    gen_vcard_any(out, etiqueta="General")
    await update.message.reply_text(f"Archivo escrito: {out}")

# ============================
# Conversación /add con upsert
# ============================
async def add_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["new_contact"] = {}
    await update.message.reply_text(
        "Vamos a agregar/actualizar un contacto 👇\n\n1/5) *Nombre*:",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove(),
    )
    return ADD_NOMBRE

async def add_nombre(update: Update, context: ContextTypes.DEFAULT_TYPE):
    nombre = update.message.text.strip()
    if not nombre:
        await update.message.reply_text("El nombre no puede estar vacío. Escribilo de nuevo:")
        return ADD_NOMBRE
    context.user_data["new_contact"]["Nombre"] = nombre
    await update.message.reply_text("2/5) *Apellido*:", parse_mode="Markdown")
    return ADD_APELLIDO

async def add_apellido(update: Update, context: ContextTypes.DEFAULT_TYPE):
    apellido = update.message.text.strip()
    if not apellido:
        await update.message.reply_text("El apellido no puede estar vacío. Escribilo de nuevo:")
        return ADD_APELLIDO
    context.user_data["new_contact"]["Apellido"] = apellido
    await update.message.reply_text("3/5) *Teléfono* (ej: +54911xxxxxxxx):", parse_mode="Markdown")
    return ADD_TELEFONO

async def add_telefono(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tel = _clean_phone(update.message.text)
    if not tel:
        await update.message.reply_text("El teléfono no puede estar vacío. Ingresalo de nuevo:")
        return ADD_TELEFONO
    context.user_data["new_contact"]["Teléfono"] = tel
    await update.message.reply_text("4/5) *DNI* (podés dejar vacío):", parse_mode="Markdown")
    return ADD_DNI

async def add_dni(update: Update, context: ContextTypes.DEFAULT_TYPE):
    dni = (update.message.text or "").strip()
    context.user_data["new_contact"]["DNI"] = dni

    kb = [["Pendiente", "Aceptado", "Rechazado"]]
    await update.message.reply_text(
        "5/5) *Estado* (elegí una opción o escribí):",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup(kb, one_time_keyboard=True, resize_keyboard=True),
    )
    return ADD_ESTADO

async def add_estado(update: Update, context: ContextTypes.DEFAULT_TYPE):
    est_in = (update.message.text or "").strip().lower()
    if est_in.startswith("acept"):
        estado = "Aceptado"
    elif est_in.startswith("rech"):
        estado = "Rechazado"
    else:
        estado = "Pendiente"

    data = context.user_data.get("new_contact", {})
    row = [
        data.get("Nombre", ""),
        data.get("Apellido", ""),
        data.get("Teléfono", ""),
        data.get("DNI", ""),
        estado,
    ]

    # UPSERT: si existe por Teléfono/DNI actualiza, sino inserta
    result = upsert_contact_any(row)

    verb = "actualizado" if result == "updated" else "agregado"
    msg = (
        f"✅ *Contacto {verb}*\n\n"
        f"{row[IDX['Teléfono']]}: {row[IDX['Nombre']]}, {row[IDX['Apellido']]} - {row[IDX['Estado']]}"
    )
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=ReplyKeyboardRemove())
    await update.message.reply_text("Volvé al menú con /menu")
    return ConversationHandler.END

async def add_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Operación cancelada.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

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
# Main: webhook/polling
# ============================
def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("Falta TELEGRAM_BOT_TOKEN.")
    mode = os.environ.get("TG_MODE", "polling").strip().lower()

    app = ApplicationBuilder().token(token).build()

    # Menú + callbacks
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("menu", cmd_menu))
    app.add_handler(CallbackQueryHandler(on_menu_callback, pattern=r"^MENU:(?!HOME$).+"))
    app.add_handler(CallbackQueryHandler(on_menu_home, pattern=r"^MENU:HOME$"))

    # Paginación de vista normal (placeholder)
    app.add_handler(CallbackQueryHandler(lambda u, c: None, pattern=r"^PAGE:\d+$"))

    # Editor de pendientes
    app.add_handler(CallbackQueryHandler(on_edit_page_callback, pattern=r"^EDITPAGE:\d+$"))
    app.add_handler(CallbackQueryHandler(on_edit_pick_row,   pattern=r"^EDIT:\d+$"))
    app.add_handler(CallbackQueryHandler(on_edit_set_state,  pattern=r"^SET:\d+:(Aceptado|Rechazado|Pendiente)$"))

    # Conversación /add con upsert
    add_conv = ConversationHandler(
        entry_points=[CommandHandler("add", add_start)],
        states={
            ADD_NOMBRE:   [MessageHandler(filters.TEXT & ~filters.COMMAND, add_nombre)],
            ADD_APELLIDO: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_apellido)],
            ADD_TELEFONO: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_telefono)],
            ADD_DNI:      [MessageHandler(filters.TEXT & ~filters.COMMAND, add_dni)],
            ADD_ESTADO:   [MessageHandler(filters.TEXT & ~filters.COMMAND, add_estado)],
        },
        fallbacks=[CommandHandler("cancel", add_cancel)],
        name="add_contact_conv",
        persistent=False,
    )
    app.add_handler(add_conv)

    # Comandos clásicos
    app.add_handler(CommandHandler("get_lista", cmd_get_lista))
    app.add_handler(CommandHandler("get_pendientes", cmd_get_pendientes))
    app.add_handler(CommandHandler("get_aceptados", cmd_get_aceptados))
    app.add_handler(CommandHandler("get_rechazados", cmd_get_rechazados))
    app.add_handler(CommandHandler("gen_contacts", cmd_gen_contacts))
    app.add_handler(CommandHandler("vcard", cmd_vcard))

    app.add_error_handler(handle_error)

    # Si falta URL pública en modo webhook, caemos a polling
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
