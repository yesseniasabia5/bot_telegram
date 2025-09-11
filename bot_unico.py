# bot_unico.py — FLEX + MENU
# Unifica lista CSV, exportación Google Contacts, vCard y Bot de Telegram.
# Incluye UI con botones (InlineKeyboard) y paginación.
# Python 3.10+

import os
import csv
import re
import logging
import unicodedata
import asyncio
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

print("BOT_UNICO VERSION -> FLEX+MENU 1.0")

# ============================
# Cargar .env y logging
# ============================
load_dotenv()  # lee TELEGRAM_BOT_TOKEN, LISTA_CSV, DROP_WEBHOOK

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

# ============================
# Utilidades CSV / texto
# ============================
def _norm(s: str) -> str:
    """Normaliza: trim, quita tildes, pasa a minúsculas."""
    s = s.strip()
    s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))
    return s.lower()

def _read_csv_rows(path: str) -> List[List[str]]:
    # utf-8-sig para tolerar BOM
    with open(path, mode="r", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        return [row for row in reader]

def _write_csv_rows(path: str, rows: List[List[str]]):
    with open(path, mode="w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerows(rows)

def _header_mapping(actual: List[str]) -> dict[str, Optional[int]]:
    """Mapea encabezados reales a posiciones requeridas, aceptando sinónimos."""
    norm_actual = [_norm(h) for h in actual]
    pos = {h: i for i, h in enumerate(norm_actual)}

    # Sinónimos por columna esperada
    wanted = {
        "Nombre":   ("nombre",),
        "Apellido": ("apellido",),
        "Teléfono": ("telefono", "teléfono", "telefono celular", "tel"),
        "DNI":      ("dni", "documento", "doc", "email"),       # si falta DNI, puede usar email
        "Estado":   ("estado", "etiquetas", "status", "label"), # si falta, default Pendiente
    }

    mapping: dict[str, Optional[int]] = {}
    for target, aliases in wanted.items():
        found = next((pos[a] for a in aliases if a in pos), None)
        if found is None and target not in ("DNI", "Estado"):
            raise ValueError(f"Falta columna requerida para '{target}'. Encabezados: {actual}")
        mapping[target] = found
    return mapping

# ==================================
# 1) Lectura/Escritura lista base
# ==================================
def read_lista(csv_path: str) -> List[List[str]]:
    rows = _read_csv_rows(csv_path)
    if not rows:
        return []

    # Si ya viene con los headers estándar exactos:
    if rows[0] == CSV_HEADERS:
        return rows[1:]

    # Si no, mapear encabezados flexibles
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
        if estn in ("aceptado", "aceptada"):
            estado = "Aceptado"
        elif estn in ("rechazado", "rechazada"):
            estado = "Rechazado"
        else:
            estado = "Pendiente"

        out.append([nombre, apellido, telefono, dni, estado])
    return out

def set_lista(csv_path: str, body_rows: List[List[str]]):
    _write_csv_rows(csv_path, [CSV_HEADERS] + body_rows)

def filter_by_status(rows: List[List[str]], estado: str) -> List[List[str]]:
    return [r for r in rows if len(r) > IDX["Estado"] and r[IDX["Estado"]] == estado]

# ==================================
# 2) Exportación a Google Contacts
# ==================================
def gen_contacts(input_csv: str, output_csv: str) -> str:
    # lee/normaliza cualquier encabezado soportado
    body = read_lista(input_csv)  # -> [Nombre, Apellido, Teléfono, DNI, Estado]
    out_rows = [GOOGLE_HEADERS]
    for row in body:
        given, family, phone, dni, labels = row
        out_rows.append([given, family, phone, labels, dni, ""])
    _write_csv_rows(output_csv, out_rows)
    return output_csv

# ==================================
# 3) Exportación a vCard (.vcf)
# ==================================
def gen_vcard(input_csv: str, output_vcf: str, etiqueta: str = "General") -> str:
    # Si input_csv es un CSV 2-col (Nombre,Teléfono) también funciona
    rows = _read_csv_rows(input_csv)
    if not rows:
        _write_csv_rows(output_vcf, [])
        return output_vcf

    header = rows[0]
    if _norm(",".join(header)) in (_norm("Nombre,Teléfono"), _norm("Nombre;Teléfono")) or header == ["Nombre", "Teléfono"]:
        name_idx = 0
        phone_idx = 1
        body = rows[1:] if rows and rows[0] == header else rows
    else:
        # normalizar con read_lista y operar sobre el estándar
        body = read_lista(input_csv)
        name_idx = IDX["Nombre"]
        phone_idx = IDX["Teléfono"]

    count = 0
    with open(output_vcf, "w", encoding="utf-8", newline="") as f:
        for row in body:
            if not row or len(row) <= phone_idx:
                continue
            nombre = row[name_idx].strip() if len(row) > name_idx else ""
            telefono = row[phone_idx].strip() if len(row) > phone_idx else ""
            if not telefono:
                continue
            count += 1
            telefono_uri = re.sub(r"[^\d+]", "", telefono)  # deja dígitos y '+'
            display = f"Fiscal {etiqueta} {nombre}" if nombre else f"Fiscal {etiqueta} {count}"
            f.write("BEGIN:VCARD\n")
            f.write("VERSION:4.0\n")
            f.write(f"FN:{display}\n")
            f.write(f"TEL;TYPE=CELL;VALUE=uri:tel:{telefono_uri}\n")
            f.write("END:VCARD\n")
    return output_vcf

# ==================================
# 4) Bot de Telegram (comandos + UI)
# ==================================
CSV_DEFAULT = os.environ.get("LISTA_CSV", "lista.csv").strip() or "lista.csv"

def _ensure_csv(path: str):
    if not os.path.exists(path):
        # crea un CSV vacío con encabezados
        set_lista(path, [])

def _chunk_rows(rows: List[List[str]], size: int = 10):
    for i in range(0, len(rows), size):
        yield rows[i:i+size]

def _format_persona(row: List[str]) -> str:
    return f"{row[IDX['Teléfono']]}: {row[IDX['Nombre']]}, {row[IDX['Apellido']]} - {row[IDX['Estado']]}"

# ---- Menú principal
async def cmd_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [
        [InlineKeyboardButton("📋 Ver lista", callback_data="MENU:LISTA")],
        [
            InlineKeyboardButton("🟡 Pendientes", callback_data="MENU:FILTRO:Pendiente"),
            InlineKeyboardButton("🟢 Aceptados", callback_data="MENU:FILTRO:Aceptado"),
            InlineKeyboardButton("🔴 Rechazados", callback_data="MENU:FILTRO:Rechazado"),
        ],
        [InlineKeyboardButton("📤 Exportar Google Contacts", callback_data="MENU:EXPORT_GC")],
        [InlineKeyboardButton("🪪 Generar vCard", callback_data="MENU:VCARD")],
    ]
    await update.message.reply_text(
        "Elegí una opción:",
        reply_markup=InlineKeyboardMarkup(kb),
    )

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Al iniciar, mostramos el menú directamente
    return await cmd_menu(update, context)

# ---- Callbacks del menú
async def on_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data  # p.ej. "MENU:LISTA" ó "MENU:FILTRO:Aceptado"
    csv_path = CSV_DEFAULT
    _ensure_csv(csv_path)

    if data == "MENU:LISTA":
        rows = read_lista(csv_path)
        await show_rows_with_pagination(q, context, rows, title="Lista completa")
        return

    if data.startswith("MENU:FILTRO:"):
        _, _, estado = data.split(":", 2)
        rows = read_lista(csv_path)
        rows = filter_by_status(rows, estado)
        await show_rows_with_pagination(q, context, rows, title=f"{estado}s")
        return

    if data == "MENU:EXPORT_GC":
        os.makedirs("export", exist_ok=True)
        out = os.path.join("export", "contacts.csv")
        gen_contacts(csv_path, out)
        await q.edit_message_text(f"✅ Generado Google Contacts:\n`{out}`", parse_mode="Markdown")
        return

    if data == "MENU:VCARD":
        # demo: genera una vcard por defecto
        os.makedirs("export", exist_ok=True)
        out = os.path.join("export", "lista.vcf")
        gen_vcard(csv_path, out, etiqueta="General")
        await q.edit_message_text(f"✅ Generado vCard:\n`{out}`", parse_mode="Markdown")
        return

async def show_rows_with_pagination(q, context, rows: List[List[str]], title="Resultados", page=0, page_size=10):
    total = len(rows)
    if total == 0:
        await q.edit_message_text(f"Sin resultados en *{title}*.", parse_mode="Markdown")
        return
    # Guardamos en user_data para re-usar en callbacks
    context.user_data["rows"] = rows
    context.user_data["title"] = title
    context.user_data["page_size"] = page_size

    pages = list(_chunk_rows(rows, page_size))
    page = max(0, min(page, len(pages)-1))
    context.user_data["page"] = page

    body = [ _format_persona(r) for r in pages[page] ]

    # Botones de navegación
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ Anterior", callback_data=f"PAGE:{page-1}"))
    if page < len(pages)-1:
        nav.append(InlineKeyboardButton("Siguiente ➡️", callback_data=f"PAGE:{page+1}"))

    kb = [nav] if nav else []
    kb.append([InlineKeyboardButton("🏠 Menú", callback_data="MENU:HOME")])

    text = f"*{title}* (página {page+1}/{len(pages)}):\n\n" + "\n".join(body)
    if q.message:
        await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    else:
        await q.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def on_page_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data  # "PAGE:2"
    _, page_str = data.split(":", 1)
    page = int(page_str)
    rows = context.user_data.get("rows", [])
    title = context.user_data.get("title", "Resultados")
    size = context.user_data.get("page_size", 10)
    await show_rows_with_pagination(q, context, rows, title=title, page=page, page_size=size)

async def on_menu_home(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    kb = [
        [InlineKeyboardButton("📋 Ver lista", callback_data="MENU:LISTA")],
        [
            InlineKeyboardButton("🟡 Pendientes", callback_data="MENU:FILTRO:Pendiente"),
            InlineKeyboardButton("🟢 Aceptados", callback_data="MENU:FILTRO:Aceptado"),
            InlineKeyboardButton("🔴 Rechazados", callback_data="MENU:FILTRO:Rechazado"),
        ],
        [InlineKeyboardButton("📤 Exportar Google Contacts", callback_data="MENU:EXPORT_GC")],
        [InlineKeyboardButton("🪪 Generar vCard", callback_data="MENU:VCARD")],
    ]
    await q.edit_message_text("Elegí una opción:", reply_markup=InlineKeyboardMarkup(kb))

# ---- Comandos de texto tradicionales (se mantienen)
async def cmd_get_lista(update: Update, context: ContextTypes.DEFAULT_TYPE):
    csv_path = (context.args[0] if context.args else CSV_DEFAULT)
    _ensure_csv(csv_path)
    rows = read_lista(csv_path)
    if not rows:
        await update.message.reply_text("La lista está vacía.")
        return
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
        await update.message.reply_text(f"No hay personas {titulo.lower()}.")
        return
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
    csv_path = (context.args[0] if context.args else CSV_DEFAULT)
    _ensure_csv(csv_path)
    rows = read_lista(csv_path)
    await _send_list_by_status(update, filter_by_status(rows, "Pendiente"), "Pendientes")

async def cmd_get_aceptados(update: Update, context: ContextTypes.DEFAULT_TYPE):
    csv_path = (context.args[0] if context.args else CSV_DEFAULT)
    _ensure_csv(csv_path)
    rows = read_lista(csv_path)
    await _send_list_by_status(update, filter_by_status(rows, "Aceptado"), "Aceptadas")

async def cmd_get_rechazados(update: Update, context: ContextTypes.DEFAULT_TYPE):
    csv_path = (context.args[0] if context.args else CSV_DEFAULT)
    _ensure_csv(csv_path)
    rows = read_lista(csv_path)
    await _send_list_by_status(update, filter_by_status(rows, "Rechazado"), "Rechazadas")

async def cmd_pop_pendientes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 3:
        await update.message.reply_text("Uso: /pop_pendientes <Nombre> <Apellido> <Telefono> [Aceptado|Rechazado] [ruta_csv]")
        return
    nombre, apellido, telefono = args[0], args[1], args[2]
    nuevo_estado = "Aceptado"
    csv_path = CSV_DEFAULT
    if len(args) >= 4 and args[3] in ("Aceptado", "Rechazado"):
        nuevo_estado = args[3]
        if len(args) >= 5:
            csv_path = args[4]
    elif len(args) >= 4:
        csv_path = args[3]
    _ensure_csv(csv_path)
    rows = read_lista(csv_path)
    buscando = [nombre, apellido, telefono, "Pendiente"]
    poniendo = [nombre, apellido, telefono, nuevo_estado]
    if buscando in rows:
        rows.remove(buscando)
        rows.append(poniendo)
        set_lista(csv_path, rows)
        await update.message.reply_text(f"Actualizado ▶️ {' '.join(buscando[:3])} → {nuevo_estado}")
    else:
        await update.message.reply_text("No se encontró a la persona en Pendiente. Verificá los datos.")

async def cmd_gen_contacts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("Uso: /gen_contacts <input_csv> <output_csv>")
        return
    input_csv, output_csv = context.args[0], context.args[1]
    gen_contacts(input_csv, output_csv)
    await update.message.reply_text(f"Archivo escrito: {output_csv}")

async def cmd_vcard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 3:
        await update.message.reply_text("Uso: /vcard <Etiqueta> <input_csv> <output_vcf>")
        return
    etiqueta, input_csv, output_vcf = context.args[0], context.args[1], context.args[2]
    gen_vcard(input_csv, output_vcf, etiqueta)
    await update.message.reply_text(f"Archivo escrito para {etiqueta}: {os.path.basename(output_vcf)}")

# ==================================
# 5) Manejo de errores + Webhook opcional
# ==================================
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

async def _drop_webhook_if_requested(token: str):
    if os.environ.get("DROP_WEBHOOK", "").strip() == "1":
        bot = Bot(token)
        await bot.delete_webhook(drop_pending_updates=True)
        logging.info("Webhook eliminado (DROP_WEBHOOK=1).")

# ==================================
# 6) Main
# ==================================
def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("Falta el token. Definí TELEGRAM_BOT_TOKEN en .env o variables del sistema.")

    app = ApplicationBuilder().token(token).build()

    # Menú y callbacks
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("menu", cmd_menu))
    app.add_handler(CallbackQueryHandler(on_menu_callback, pattern=r"^MENU:(?!HOME$).+"))
    app.add_handler(CallbackQueryHandler(on_menu_home, pattern=r"^MENU:HOME$"))
    app.add_handler(CallbackQueryHandler(on_page_callback, pattern=r"^PAGE:\d+$"))

    # Comandos tradicionales
    app.add_handler(CommandHandler("get_lista", cmd_get_lista))
    app.add_handler(CommandHandler("get_pendientes", cmd_get_pendientes))
    app.add_handler(CommandHandler("get_aceptados", cmd_get_aceptados))
    app.add_handler(CommandHandler("get_rechazados", cmd_get_rechazados))
    app.add_handler(CommandHandler("pop_pendientes", cmd_pop_pendientes))
    app.add_handler(CommandHandler("gen_contacts", cmd_gen_contacts))
    app.add_handler(CommandHandler("vcard", cmd_vcard))

    app.add_error_handler(handle_error)

    # ✅ Borrar webhook dentro del loop del bot
    async def post_init(application):
        if os.environ.get("DROP_WEBHOOK", "").strip() == "1":
            await application.bot.delete_webhook(drop_pending_updates=True)
            logging.info("Webhook eliminado (DROP_WEBHOOK=1).")

    app.post_init = post_init

    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
