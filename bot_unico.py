# bot_unico.py — FLEX+MENU + Google Sheets backend
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
    Update, Bot,
    InlineKeyboardButton, InlineKeyboardMarkup,
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    ContextTypes,
)

# Google Sheets
import gspread
from google.oauth2.service_account import Credentials

print("BOT_UNICO VERSION -> FLEX+MENU + SHEETS 1.0")

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

# ============================
# Utilidades texto/CSV
# ============================
def _norm(s: str) -> str:
    s = s.strip()
    s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))
    return s.lower()

def _read_csv_rows(path: str) -> List[List[str]]:
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
    sa_file = os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE")
    sa_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")

    if sa_file and os.path.exists(sa_file):
        # Caso 1: usás archivo físico
        creds = Credentials.from_service_account_file(sa_file, scopes=SCOPES)
    elif sa_json:
        # Caso 2: usás JSON en variable de entorno (Render, etc.)
        info = json.loads(sa_json)
        creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    else:
        raise RuntimeError("Falta GOOGLE_SERVICE_ACCOUNT_FILE o GOOGLE_SERVICE_ACCOUNT_JSON")

    return gspread.authorize(creds)


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
    return f"{row[IDX['Teléfono']]}: {row[IDX['Nombre']]}, {row[IDX['Apellido']]} - {row[IDX['Estado']]}"

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
        [InlineKeyboardButton("📤 Exportar Google Contacts (CSV)", callback_data="MENU:EXPORT_GC")],
        [InlineKeyboardButton("🪪 Generar vCard (VCF)", callback_data="MENU:VCARD")],
    ]
    await update.message.reply_text(
        f"Elegí una opción:\nBackend: *{backend}*",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="Markdown",
    )

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

async def show_rows_with_pagination(q, context, rows: List[List[str]], title="Resultados", page=0, page_size=10):
    total = len(rows)
    if total == 0:
        return await q.edit_message_text(f"Sin resultados en *{title}*.", parse_mode="Markdown")

    context.user_data["rows"] = rows
    context.user_data["title"] = title
    context.user_data["page_size"] = page_size

    pages = list(_chunk_rows(rows, page_size))
    page = max(0, min(page, len(pages)-1))
    context.user_data["page"] = page

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

async def on_page_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    _, page_str = q.data.split(":", 1)
    page = int(page_str)
    rows = context.user_data.get("rows", [])
    title = context.user_data.get("title", "Resultados")
    size = context.user_data.get("page_size", 10)
    return await show_rows_with_pagination(q, context, rows, title=title, page=page, page_size=size)

async def on_menu_home(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    backend = "Google Sheets" if USE_SHEETS else f"CSV ({CSV_DEFAULT})"
    kb = [
        [InlineKeyboardButton("📋 Ver lista", callback_data="MENU:LISTA")],
        [
            InlineKeyboardButton("🟡 Pendientes", callback_data="MENU:FILTRO:Pendiente"),
            InlineKeyboardButton("🟢 Aceptados", callback_data="MENU:FILTRO:Aceptado"),
            InlineKeyboardButton("🔴 Rechazados", callback_data="MENU:FILTRO:Rechazado"),
        ],
        [InlineKeyboardButton("📤 Exportar Google Contacts (CSV)", callback_data="MENU:EXPORT_GC")],
        [InlineKeyboardButton("🪪 Generar vCard (VCF)", callback_data="MENU:VCARD")],
    ]
    await q.edit_message_text(f"Elegí una opción:\nBackend: *{backend}*", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

# Comandos “texto” tradicionales (por si los usás)
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

async def cmd_pop_pendientes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 3:
        return await update.message.reply_text("Uso: /pop_pendientes <Nombre> <Apellido> <Telefono> [Aceptado|Rechazado]")
    nombre, apellido, telefono = args[0], args[1], args[2]
    nuevo_estado = "Aceptado" if len(args) < 4 else ("Aceptado" if args[3] == "Aceptado" else "Rechazado")
    rows = read_lista_any()
    buscando = [nombre, apellido, telefono, "Pendiente"]
    poniendo = [nombre, apellido, telefono, nuevo_estado]
    if buscando in rows:
        rows.remove(buscando)
        rows.append(poniendo)
        set_lista_any(rows)
        await update.message.reply_text(f"Actualizado ▶️ {' '.join(buscando[:3])} → {nuevo_estado}")
    else:
        await update.message.reply_text("No se encontró a la persona en Pendiente. Verificá los datos.")

async def cmd_gen_contacts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    out = os.path.join("export", "contacts.csv")
    gen_contacts_any(out)
    await update.message.reply_text(f"Archivo escrito: {out}")

async def cmd_vcard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    out = os.path.join("export", "lista.vcf")
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
# Main: webhook/polling
# ============================
def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("Falta TELEGRAM_BOT_TOKEN.")
    mode = os.environ.get("TG_MODE", "polling").strip().lower()

    app = ApplicationBuilder().token(token).build()

    # Handlers
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("menu", cmd_menu))
    app.add_handler(CallbackQueryHandler(on_menu_callback, pattern=r"^MENU:(?!HOME$).+"))
    app.add_handler(CallbackQueryHandler(on_menu_home, pattern=r"^MENU:HOME$"))
    app.add_handler(CallbackQueryHandler(on_page_callback, pattern=r"^PAGE:\d+$"))

    app.add_handler(CommandHandler("get_lista", cmd_get_lista))
    app.add_handler(CommandHandler("get_pendientes", cmd_get_pendientes))
    app.add_handler(CommandHandler("get_aceptados", cmd_get_aceptados))
    app.add_handler(CommandHandler("get_rechazados", cmd_get_rechazados))
    app.add_handler(CommandHandler("pop_pendientes", cmd_pop_pendientes))
    app.add_handler(CommandHandler("gen_contacts", cmd_gen_contacts))
    app.add_handler(CommandHandler("vcard", cmd_vcard))

    app.add_error_handler(handle_error)

    if mode == "webhook":
        port = int(os.environ.get("PORT", "10000"))
        public_url = (os.environ.get("PUBLIC_URL")
                      or os.environ.get("RENDER_EXTERNAL_URL")
                      or "").rstrip("/")
        if not public_url:
            raise RuntimeError("Falta PUBLIC_URL o RENDER_EXTERNAL_URL para webhook.")
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
