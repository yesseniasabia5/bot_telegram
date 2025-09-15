# bot_unico.py — FLEX+MENU + SHEETS + EDIT + ADD + RESERVAS + VCF + ROLES + NOMBRES + OBS + ADMINS 7.0
# Python 3.10+

import os
import csv
import re
import json
import logging
import unicodedata
import datetime
from io import BytesIO
from typing import List, Optional, Set, Dict

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

print("BOT_UNICO VERSION -> FLEX+MENU + SHEETS + EDIT + ADD + RESERVAS + VCF + ROLES + NOMBRES + OBS + ADMINS 7.0")

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
CSV_HEADERS = ["Nombre", "Apellido", "Teléfono", "DNI", "Estado", "Observación"]
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

# Pestañas para roles en Sheets
SHEET_ALLOWED = os.environ.get("SHEET_ALLOWED", "Allowed").strip() or "Allowed"
SHEET_ADMINS  = os.environ.get("SHEET_ADMINS", "Admins").strip() or "Admins"

# Estados conversación /add
ADD_NOMBRE, ADD_APELLIDO, ADD_TELEFONO, ADD_DNI, ADD_ESTADO, ADD_CANCEL_CONFIRM = range(6)

# Estados conversación administración (Allowed)
ADM_ADD_ID, ADM_DEL_ID = range(6, 8)

# Estados conversación administración (Admins)
ADM_ADM_ADD_ID, ADM_ADM_DEL_ID = range(8, 10)

# Estado para observación "Contactar Luego"
EDIT_OBS = 100

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

def _pad_row(row: List[str], n: int) -> List[str]:
    if len(row) < n:
        return row + [""] * (n - len(row))
    return row[:n]

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

def _open_spreadsheet():
    gsid = os.environ.get("GSHEET_ID")
    if not gsid:
        raise RuntimeError("Falta GSHEET_ID")
    return _gspread_client().open_by_key(gsid)

def _open_sheet():
    return _open_spreadsheet().sheet1  # principal

def _ensure_worksheet(title: str, headers: Optional[List[str]] = None):
    """Abre o crea (si no existe) una worksheet con el título indicado."""
    sh = _open_spreadsheet()
    try:
        ws = sh.worksheet(title)
    except gspread.exceptions.WorksheetNotFound:
        ws = sh.add_worksheet(title=title, rows=1000, cols=max(5, len(headers or [])))
        if headers:
            ws.update(values=[headers], range_name="A1")
    return ws

# ===== Lista principal (pestaña 1) =====
def read_lista_any() -> List[List[str]]:
    if USE_SHEETS:
        ws = _open_sheet()
        vals = ws.get_all_values()
        body = [_pad_row(r, len(CSV_HEADERS)) for r in (vals[1:] if vals else [])]
        return body
    else:
        rows = _read_csv_rows(CSV_DEFAULT)
        body = [_pad_row(r, len(CSV_HEADERS)) for r in (rows[1:] if rows else [])]
        return body

def set_lista_any(rows: List[List[str]]):
    rows = [_pad_row(r, len(CSV_HEADERS)) for r in rows]
    if USE_SHEETS:
        ws = _open_sheet()
        ws.clear()
        ws.update(values=[CSV_HEADERS] + rows, range_name="A1")
    else:
        _write_csv_rows(CSV_DEFAULT, [CSV_HEADERS] + rows)

def append_contact_any(row: List[str]) -> str:
    """Inserta o actualiza por Teléfono/DNI. Devuelve 'new' o 'updated'."""
    row = _pad_row(row, len(CSV_HEADERS))
    if USE_SHEETS:
        ws = _open_sheet()
        vals = ws.get_all_values()
        if not vals:
            ws.update(values=[CSV_HEADERS], range_name="A1")
            ws.append_row(row)
            return "new"
        body = [_pad_row(r, len(CSV_HEADERS)) for r in vals[1:]]
        for i, r in enumerate(body):
            if r[IDX["Teléfono"]] == row[IDX["Teléfono"]] or (row[IDX["DNI"]] and r[IDX["DNI"]] == row[IDX["DNI"]]):
                ws.update(values=[row], range_name=f"A{i+2}:F{i+2}")  # 6 columnas
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

# ===== Roles (Allowed/Admins) en Sheets — con nombre =====
def _read_ids_and_names_from_sheet(title: str) -> Dict[int, str]:
    """
    Lee IDs/nombres (encabezados 'user_id','name' en A1:B1) y devuelve {id: name}.
    Crea la hoja si no existe.
    """
    ws = _ensure_worksheet(title, headers=["user_id", "name"])
    vals = ws.get_all_values()
    out: Dict[int, str] = {}
    for row in (vals[1:] if vals else []):
        if not row:
            continue
        uid_str = (row[0] or "").strip()
        name = (row[1] or "").strip() if len(row) > 1 else ""
        if uid_str.isdigit():
            out[int(uid_str)] = name
    return out

def _append_id_name_to_sheet(title: str, uid: int, name: str = "") -> None:
    ws = _ensure_worksheet(title, headers=["user_id", "name"])
    registry = _read_ids_and_names_from_sheet(title)
    if uid in registry:
        # Si ya existe, actualizamos el nombre si viene uno no vacío
        if name and registry[uid] != name:
            vals = ws.get_all_values()
            for i, row in enumerate(vals[1:], start=2):
                if row and (row[0] or "").strip().isdigit() and int(row[0].strip()) == uid:
                    ws.update(values=[[str(uid), name]], range_name=f"A{i}:B{i}")
                    return
        return
    ws.append_row([str(uid), name])

def _remove_id_from_sheet(title: str, uid: int) -> bool:
    ws = _ensure_worksheet(title, headers=["user_id", "name"])
    vals = ws.get_all_values()
    if not vals:
        return False
    for i, row in enumerate(vals[1:], start=2):
        uid_str = (row[0] or "").strip()
        if uid_str.isdigit() and int(uid_str) == uid:
            ws.delete_rows(i)
            return True
    return False

def get_admins_map() -> Dict[int, str]:
    env_admins = {int(x): "" for x in os.environ.get("ADMIN_USER_IDS", "").split(",") if x.strip().isdigit()}
    sheet_admins = _read_ids_and_names_from_sheet(SHEET_ADMINS) if USE_SHEETS else {}
    env_admins.update(sheet_admins)
    return env_admins

def get_allowed_map() -> Dict[int, str]:
    """Allowed = Admins ∪ AllowedSheet ∪ ALLOWED_USER_IDS (.env)."""
    env_allowed = {int(x): "" for x in os.environ.get("ALLOWED_USER_IDS", "").split(",") if x.strip().isdigit()}
    sheet_allowed = _read_ids_and_names_from_sheet(SHEET_ALLOWED) if USE_SHEETS else {}
    all_allowed = get_admins_map()
    all_allowed.update(sheet_allowed)
    for k, v in env_allowed.items():
        if k not in all_allowed:
            all_allowed[k] = v
    return all_allowed

def get_admin_ids() -> Set[int]:
    return set(get_admins_map().keys())

def get_allowed_ids() -> Set[int]:
    return set(get_allowed_map().keys())

def auth_is_locked() -> bool:
    """
    Si FORCE_LOCK=1, el bot SIEMPRE está bloqueado (requiere whitelist),
    incluso si no hay admins/allowed en hojas/entorno.
    """
    if os.environ.get("FORCE_LOCK", "0").strip() == "1":
        return True
    return bool(get_admin_ids() or get_allowed_ids())

def get_display_for_uid(uid: int, update: Optional[Update] = None) -> str:
    """Nombre para mostrar: primero Sheet (Allowed/Admins), luego username/full_name si está en el update, sino uid."""
    m = get_allowed_map()
    if uid in m and m[uid]:
        return m[uid]
    if update and update.effective_user:
        u = update.effective_user
        if u.username:
            return f"@{u.username}"
        if u.full_name:
            return u.full_name
    return str(uid)

# ============================
# Exportaciones
# ============================
def gen_contacts_any(output_csv: str) -> str:
    body = read_lista_any()
    out_rows = [GOOGLE_HEADERS]
    for row in body:
        row = _pad_row(row, len(CSV_HEADERS))
        given, family, phone, dni, labels = row[IDX["Nombre"]], row[IDX["Apellido"]], row[IDX["Teléfono"]], row[IDX["DNI"]], row[IDX["Estado"]]
        out_rows.append([given, family, phone, labels, dni, row[IDX["Observación"]]])
    _write_csv_rows(output_csv, out_rows)
    return output_csv

def gen_vcard_from_rows(rows: List[List[str]], output_vcf: str, etiqueta: str = "General") -> str:
    count = 0
    os.makedirs(os.path.dirname(output_vcf) or ".", exist_ok=True)
    with open(output_vcf, "w", encoding="utf-8", newline="") as f:
        for row in rows:
            row = _pad_row(row, len(CSV_HEADERS))
            nombre = row[IDX["Nombre"]].strip()
            telefono = row[IDX["Teléfono"]].strip()
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
        row = _pad_row(row, len(CSV_HEADERS))
        tel = row[IDX["Teléfono"]]
        nom = row[IDX["Nombre"]]
        ape = row[IDX["Apellido"]]
        est = row[IDX["Estado"]]
        obs = row[IDX["Observación"]]
        tail = f" - {est}" if est else ""
        if est.startswith("Contactar Luego") and obs:
            tail += f" ({obs})"
        return f"{tel}: {nom}, {ape}{tail}"
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
def _estado_es_en_contacto(valor: str) -> bool:
    return _norm(valor).startswith("en contacto")

def release_reservation(context: ContextTypes.DEFAULT_TYPE):
    """Devuelve a 'Pendiente' solo los reservados que aún están en 'En contacto*'."""
    reserved = context.user_data.get("reserved_rows", [])
    if reserved:
        all_rows = read_lista_any()
        for r in reserved:
            for rr in all_rows:
                if rr[IDX["Teléfono"]] == r[IDX["Teléfono"]] or (
                    r[IDX["DNI"]] and rr[IDX["DNI"]] == r[IDX["DNI"]]
                ):
                    if _estado_es_en_contacto(rr[IDX["Estado"]]):
                        rr[IDX["Estado"]] = "Pendiente"
                        rr[IDX["Observación"]] = ""
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
    kb = [["Pendiente", "Aceptado", "Rechazado"], ["Número incorrecto", "Contactar Luego"]]
    await update.message.reply_text("5/5) *Estado*:", parse_mode="Markdown",
                                    reply_markup=ReplyKeyboardMarkup(kb, one_time_keyboard=True, resize_keyboard=True))
    return ADD_ESTADO

async def add_estado(update: Update, context: ContextTypes.DEFAULT_TYPE):
    est_in = update.message.text.strip().lower()
    if est_in.startswith("acept"):
        estado = "Aceptado"
    elif est_in.startswith("rech"):
        estado = "Rechazado"
    elif est_in.startswith("número") or est_in.startswith("numero"):
        estado = "Número incorrecto"
    elif est_in.startswith("contactar"):
        # Pedimos observación y cerramos luego
        context.user_data["await_add_obs"] = True
        context.user_data["new_contact"]["Estado"] = "Contactar Luego"
        await update.message.reply_text("Escribí la *observación*:", parse_mode="Markdown",
                                        reply_markup=ReplyKeyboardRemove())
        return ADD_ESTADO
    else:
        estado = "Pendiente"

    d = context.user_data["new_contact"]
    row = [d.get("Nombre",""), d.get("Apellido",""), d.get("Teléfono",""), d.get("DNI",""), estado, ""]
    res = append_contact_any(row)
    verb = "actualizado" if res == "updated" else "agregado"
    await update.message.reply_text(f"✅ Contacto {verb}\n\n{_format_persona(row)}",
                                    parse_mode="Markdown", reply_markup=ReplyKeyboardRemove())
    return await cmd_menu(update, context)

# Si venía Contactar Luego → guardamos observación y terminamos
async def add_estado_observacion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("await_add_obs"):
        return ConversationHandler.END
    obs = (update.message.text or "").strip()
    d = context.user_data["new_contact"]
    row = [d.get("Nombre",""), d.get("Apellido",""), d.get("Teléfono",""), d.get("DNI",""),
           "Contactar Luego", obs]
    res = append_contact_any(row)
    verb = "actualizado" if res == "updated" else "agregado"
    await update.message.reply_text(f"✅ Contacto {verb}\n\n{_format_persona(row)}",
                                    parse_mode="Markdown", reply_markup=ReplyKeyboardRemove())
    context.user_data.pop("await_add_obs", None)
    return await cmd_menu(update, context)

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
        release_reservation(context)
        return await cmd_menu(update, context)
    else:
        await q.edit_message_text("Continuemos. Repetí el dato anterior.")
        return ConversationHandler.WAITING

# ============================
# Generar y enviar VCF de la tanda reservada
# ============================
async def send_reserved_vcf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    reserved = context.user_data.get("reserved_rows", [])
    if not reserved:
        return await q.edit_message_text("No tenés una tanda reservada ahora.")
    buf = BytesIO()
    count = 0
    for row in reserved:
        row = _pad_row(row, len(CSV_HEADERS))
        nombre   = row[IDX["Nombre"]].strip()
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
        row = _pad_row(row, len(CSV_HEADERS))
        first = row[IDX["Nombre"]]
        last  = row[IDX["Apellido"]]
        phone = row[IDX["Teléfono"]]
        if phone:
            await context.bot.send_contact(
                chat_id=q.message.chat_id,
                phone_number=phone,
                first_name=first or "Contacto",
                last_name=last or ""
            )
    await q.answer()

# ============================
# WHITELIST / ADMIN (autorización)
# ============================
from functools import wraps

def require_auth(fn):
    @wraps(fn)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        # Si no hay nadie configurado, no restringimos (modo desarrollo)
        if not auth_is_locked():
            return await fn(update, context, *args, **kwargs)
        u = update.effective_user
        uid = u.id if u else None
        if uid is None or uid not in get_allowed_ids():
            try:
                if getattr(update, "callback_query", None):
                    await update.callback_query.answer("⛔ Acceso denegado", show_alert=True)
                elif getattr(update, "message", None):
                    await update.message.reply_text("⛔ Acceso denegado.")
                else:
                    chat_id = update.effective_chat.id if update.effective_chat else None
                    if chat_id:
                        await context.bot.send_message(chat_id, "⛔ Acceso denegado.")
            except Exception:
                pass
            return
        return await fn(update, context, *args, **kwargs)
    return wrapper

def require_admin(fn):
    @wraps(fn)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        u = update.effective_user
        if not (u and u.id in get_admin_ids()):
            try:
                if getattr(update, "callback_query", None):
                    await update.callback_query.answer("⛔ Solo administradores", show_alert=True)
                elif getattr(update, "message", None):
                    await update.message.reply_text("⛔ Solo administradores.")
            except Exception:
                pass
            return
        return await fn(update, context, *args, **kwargs)
    return wrapper

# ============================
# Menú principal y callbacks
# ============================
@require_admin
async def admin_add_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await q.edit_message_text(
        "Ingresá: `user_id` y *opcionalmente* el nombre en la misma línea.\n"
        "Ejemplos:\n"
        "`123456789`\n"
        "`123456789 Juan Pérez`",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Cancelar", callback_data="MENU:ADMIN")]])
    )
    return ADM_ADD_ID

@require_admin
async def admin_del_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await q.edit_message_text(
        "Ingresá el `user_id` numérico a quitar:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Cancelar", callback_data="MENU:ADMIN")]])
    )
    return ADM_DEL_ID

# ---- Admins (panel específico) ----
@require_admin
async def admin_add_admin_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await q.edit_message_text(
        "Ingresá: `user_id` y *opcionalmente* el nombre para **Admin**.\nEj:\n`123456789`\n`123456789 Juan Pérez`",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Cancelar", callback_data="MENU:ADMIN")]])
    )
    return ADM_ADM_ADD_ID

@require_admin
async def admin_del_admin_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await q.edit_message_text(
        "Ingresá el `user_id` numérico a quitar de **Admins**:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Cancelar", callback_data="MENU:ADMIN")]])
    )
    return ADM_ADM_DEL_ID

@require_admin
async def admin_cancel_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await q.edit_message_text("Volvemos al panel de administración.")
    kb = [
        [InlineKeyboardButton("👑 Ver Admins", callback_data="ADMIN:ADM_LIST")],
        [InlineKeyboardButton("➕ Agregar Admin", callback_data="ADMIN:ADM_ADD")],
        [InlineKeyboardButton("➖ Quitar Admin", callback_data="ADMIN:ADM_DEL")],
        [InlineKeyboardButton("👥 Ver Allowed", callback_data="ADMIN:LIST")],
        [InlineKeyboardButton("➕ Agregar ID Allowed", callback_data="ADMIN:ADD")],
        [InlineKeyboardButton("➖ Quitar ID Allowed", callback_data="ADMIN:DEL")],
        [InlineKeyboardButton("🏠 Menú", callback_data="MENU:HOME")],
    ]
    await q.message.reply_text("🔐 Panel de administración", reply_markup=InlineKeyboardMarkup(kb))
    return ConversationHandler.END

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
        [InlineKeyboardButton("✏️ Cambiar estado (Pendientes)", callback_data="MENU:EDIT")],
        [InlineKeyboardButton("➕ Agregar contacto", callback_data="MENU:ADD")],
        [InlineKeyboardButton("📤 Exportar Google Contacts (CSV)", callback_data="MENU:EXPORT_GC")],
        [InlineKeyboardButton("🪪 Generar vCard (VCF)", callback_data="MENU:VCARD")],
    ]

    # Panel admin solo para admins
    if update.effective_user and update.effective_user.id in get_admin_ids():
        kb.append([InlineKeyboardButton("🔐 Administración", callback_data="MENU:ADMIN")])

    text = f"Elegí una opción:\nBackend: *{backend}*"
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
async def on_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        return await start_list_pagination(q, context, rows, title="Lista completa", page_size=10, page=0)

    if data.startswith("MENU:FILTRO:"):
        _, _, estado = data.split(":", 2)

        if estado == "Pendiente":
            all_rows = read_lista_any()
            pendientes = filter_by_status(all_rows, "Pendiente")
            if not pendientes:
                return await q.edit_message_text("No hay personas pendientes.")
            uid = update.effective_user.id if update.effective_user else 0
            who = get_display_for_uid(uid, update)
            to_assign = pendientes[:5]
            for r in to_assign:
                r = _pad_row(r, len(CSV_HEADERS))
                r[IDX["Estado"]] = f"En contacto - {who}"
                r[IDX["Observación"]] = ""
            set_lista_any(all_rows)
            context.user_data["reserved_rows"] = to_assign
            msg = "\n".join(_format_persona(r) for r in to_assign)
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
        base = context.user_data.get("reserved_rows")
        if base:
            pendientes = base
        else:
            pendientes = filter_by_status(read_lista_any(), "Pendiente")
        context.user_data["edit_base_rows"] = pendientes
        return await show_editable_list(q, context, pendientes, title="Cambiar estado (Pendientes)", page=0, page_size=5)

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
    kb_rows.append([InlineKeyboardButton("📥 Guardar 5 (VCF)", callback_data="MENU:SAVE5"),
                    InlineKeyboardButton("📱 Enviar como contactos", callback_data="MENU:SENDCONTACTS")])
    kb_rows.append([InlineKeyboardButton("🧹 Cancelar y liberar", callback_data="MENU:CANCEL_RESERVA")])
    kb_rows.append([InlineKeyboardButton("🏠 Menú", callback_data="MENU:HOME")])
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
    return await show_editable_list(q, context, base_rows, title="Cambiar estado (Pendientes)", page=page, page_size=size)

@require_auth
async def on_edit_pick_row(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    _, idx_str = q.data.split(":", 1)
    abs_idx = int(idx_str)
    base_rows = context.user_data.get("edit_base_rows", [])
    if not (0 <= abs_idx < len(base_rows)):
        return await q.edit_message_text("Índice inválido. Volvé a intentarlo desde el menú.")
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

@require_auth
async def cmd_whoami(update, context):
    u = update.effective_user
    if not u:
        return await update.message.reply_text("No se pudo determinar tu usuario.")
    name = u.full_name or (f"@{u.username}" if u.username else "")
    await update.message.reply_text(f"Tu user_id: {u.id}\nNombre: {name}")

def _col_number_from_idx(idx0: int) -> int:
    return idx0 + 1

def _find_by_keys_fallback(all_rows: List[List[str]], target: List[str]) -> int:
    target = _pad_row(target, len(CSV_HEADERS))
    tel = target[IDX["Teléfono"]].strip()
    dni = target[IDX["DNI"]].strip()
    for i, r in enumerate(all_rows):
        r = _pad_row(r, len(CSV_HEADERS))
        if (r[IDX["Teléfono"]].strip() == tel) or (dni and r[IDX["DNI"]].strip() == dni):
            return i
    return -1

def update_estado_by_row_index(abs_index: int, nuevo_estado: str, base_rows: List[List[str]], observacion: str = "") -> None:
    """Actualiza Estado (y Observación si aplica) en la fila real correspondiente."""
    if USE_SHEETS:
        all_rows = read_lista_any()
        target = _pad_row(base_rows[abs_index], len(CSV_HEADERS))
        try:
            real_idx = next(i for i, r in enumerate(all_rows) if _pad_row(r, len(CSV_HEADERS)) == target)
        except StopIteration:
            real_idx = _find_by_keys_fallback(all_rows, target)
        if real_idx < 0:
            raise RuntimeError("No se encontró la fila a actualizar.")
        ws = _open_sheet()
        row = real_idx + 2  # header +1
        ws.update_cell(row, _col_number_from_idx(IDX["Estado"]), nuevo_estado)
        if nuevo_estado == "Contactar Luego":
            ws.update_cell(row, _col_number_from_idx(IDX["Observación"]), observacion or "")
        elif nuevo_estado == "Pendiente" or nuevo_estado.startswith("En contacto"):
            ws.update_cell(row, _col_number_from_idx(IDX["Observación"]), "")
    else:
        rows = read_lista_any()
        target = _pad_row(base_rows[abs_index], len(CSV_HEADERS))
        try:
            real_idx = next(i for i, r in enumerate(rows) if _pad_row(r, len(CSV_HEADERS)) == target)
        except StopIteration:
            real_idx = _find_by_keys_fallback(rows, target)
        if 0 <= real_idx < len(rows):
            r = _pad_row(rows[real_idx], len(CSV_HEADERS))
            r[IDX["Estado"]] = nuevo_estado
            if nuevo_estado == "Contactar Luego":
                r[IDX["Observación"]] = observacion or ""
            elif nuevo_estado == "Pendiente" or nuevo_estado.startswith("En contacto"):
                r[IDX["Observación"]] = ""
            rows[real_idx] = r
            set_lista_any(rows)

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
        context.user_data["obs_target_index"] = abs_idx
        await q.edit_message_text("Escribí la *observación* para 'Contactar Luego':", parse_mode="Markdown",
                                  reply_markup=InlineKeyboardMarkup(
                                      [[InlineKeyboardButton("Cancelar", callback_data="OBS:CANCEL")]]
                                  ))
        return EDIT_OBS

    update_estado_by_row_index(abs_index=abs_idx, nuevo_estado=nuevo, base_rows=base_rows)
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

# === Conversación de observación para "Contactar Luego"
@require_auth
async def obs_cancel_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await q.edit_message_text("Operación cancelada.")
    base = context.user_data.get("edit_base_rows", [])
    return await show_editable_list(q, context, base, title="Cambiar estado (Pendientes)", page=context.user_data.get("edit_page",0), page_size=context.user_data.get("edit_page_size",5))

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
    new_pendientes = filter_by_status(read_lista_any(), "Pendiente")
    context.user_data["edit_base_rows"] = new_pendientes
    page = context.user_data.get("edit_page", 0)
    size = context.user_data.get("edit_page_size", 5)
    total_pages = max(1, (len(new_pendientes) + size - 1) // size)
    if page >= total_pages:
        page = max(0, total_pages - 1)
    context.user_data["edit_page"] = page
    await update.message.reply_text("✅ Guardado con 'Contactar Luego' y observación.")
    q_like = type("Q", (), {"edit_message_text": update.message.reply_text})
    return await show_editable_list(q_like, context, new_pendientes, title="Cambiar estado (Pendientes)", page=page, page_size=size)

# ============================
# Comandos “texto”
# ============================
@require_auth
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
        r = _pad_row(r, len(CSV_HEADERS))
        block.append(f"{r[IDX['Teléfono']]}: {r[IDX['Nombre']]}, {r[IDX['Apellido']]}")
        if i % 20 == 0:
            await update.message.reply_text("\n".join(block))
            block = []
    if block:
        await update.message.reply_text("\n".join(block))

@require_auth
async def cmd_get_pendientes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    all_rows = read_lista_any()
    pendientes = filter_by_status(all_rows, "Pendiente")
    if not pendientes:
        return await update.message.reply_text("No hay personas pendientes.")
    uid = update.effective_user.id if update.effective_user else 0
    who = get_display_for_uid(uid, update)
    to_assign = pendientes[:5]
    for r in to_assign:
        r = _pad_row(r, len(CSV_HEADERS))
        r[IDX["Estado"]] = f"En contacto - {who}"
        r[IDX["Observación"]] = ""
    set_lista_any(all_rows)
    context.user_data["reserved_rows"] = to_assign
    msg = "\n".join(f"{r[IDX['Teléfono']]}: {r[IDX['Nombre']]}, {r[IDX['Apellido']]}" for r in to_assign)
    await update.message.reply_text(f"Estos son tus pendientes asignados:\n\n{msg}")

@require_auth
async def cmd_get_aceptados(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = read_lista_any()
    return await _send_list_by_status(update, filter_by_status(rows, "Aceptado"), "Aceptadas")

@require_auth
async def cmd_get_rechazados(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = read_lista_any()
    return await _send_list_by_status(update, filter_by_status(rows, "Rechazado"), "Rechazadas")

@require_auth
async def cmd_gen_contacts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    out = os.path.join("export", "contacts.csv")
    os.makedirs("export", exist_ok=True)
    gen_contacts_any(out)
    await update.message.reply_text(f"Archivo escrito: {out}")

@require_auth
async def cmd_vcard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    out = os.path.join("export", "lista.vcf")
    os.makedirs("export", exist_ok=True)
    gen_vcard_any(out, etiqueta="General")
    await update.message.reply_text(f"Archivo escrito: {out}")

# ============================
# Admin conversations (Allowed)
# ============================
@require_admin
async def admin_add_id_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if not text:
        await update.message.reply_text("⚠️ Ingresá `user_id` y opcionalmente nombre.")
        return ADM_ADD_ID
    parts = text.split()
    if not parts[0].isdigit():
        await update.message.reply_text("⚠️ El primer dato debe ser un número (user_id).")
        return ADM_ADD_ID
    uid = int(parts[0])
    name = " ".join(parts[1:]).strip() if len(parts) > 1 else ""
    _append_id_name_to_sheet(SHEET_ALLOWED, uid, name)
    shown = f"{uid} - {name}" if name else str(uid)
    await update.message.reply_text(f"✅ Agregado a Allowed: {shown}")
    return ConversationHandler.END

@require_admin
async def admin_del_id_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if not text.isdigit():
        await update.message.reply_text("⚠️ Debe ser un número. Probá otra vez o tocá *Cancelar*.", parse_mode="Markdown")
        return ADM_DEL_ID
    uid = int(text)
    ok = _remove_id_from_sheet(SHEET_ALLOWED, uid)
    if ok:
        await update.message.reply_text(f"✅ Quitado de Allowed: {uid}")
    else:
        await update.message.reply_text(f"ℹ️ El ID {uid} no estaba en Allowed.")
    return ConversationHandler.END

# ============================
# Admin conversations (Admins)
# ============================
@require_admin
async def admin_add_admin_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if not text:
        await update.message.reply_text("⚠️ Ingresá `user_id` y opcionalmente nombre.")
        return ADM_ADM_ADD_ID
    parts = text.split()
    if not parts[0].isdigit():
        await update.message.reply_text("⚠️ El primer dato debe ser un número (user_id).")
        return ADM_ADM_ADD_ID
    uid = int(parts[0])
    name = " ".join(parts[1:]).strip() if len(parts) > 1 else ""
    _append_id_name_to_sheet(SHEET_ADMINS, uid, name)
    shown = f"{uid} - {name}" if name else str(uid)
    await update.message.reply_text(f"✅ Agregado a Admins: {shown}")
    return ConversationHandler.END

@require_admin
async def admin_del_admin_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if not text.isdigit():
        await update.message.reply_text("⚠️ Debe ser un número. Probá de nuevo.")
        return ADM_ADM_DEL_ID
    uid = int(text)
    ok = _remove_id_from_sheet(SHEET_ADMINS, uid)
    if ok:
        await update.message.reply_text(f"✅ Quitado de Admins: {uid}")
    else:
        await update.message.reply_text(f"ℹ️ El ID {uid} no estaba en Admins.")
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
# Main
# ============================
def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("Falta TELEGRAM_BOT_TOKEN.")
    mode = os.environ.get("TG_MODE", "polling").strip().lower()

    app = ApplicationBuilder().token(token).build()

    # === Conversación ADD contacto ===
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
            ADD_ESTADO:   [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_estado),
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_estado_observacion),
            ],
            ADD_CANCEL_CONFIRM: [CallbackQueryHandler(on_cancel_callback, pattern="^CANCEL:")],
        },
        fallbacks=[CommandHandler("cancel", add_cancel)],
        name="add_contact_conv",
        persistent=False,
    )
    app.add_handler(add_conv)

    # === Conversación OBS para "Contactar Luego" ===
    obs_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(on_edit_set_state, pattern=r"^SET:\d+:Contactar Luego$")],
        states={
            EDIT_OBS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, obs_text_handler),
                CallbackQueryHandler(obs_cancel_cb, pattern=r"^OBS:CANCEL$")
            ],
        },
        fallbacks=[CallbackQueryHandler(obs_cancel_cb, pattern=r"^OBS:CANCEL$")],
        name="obs_conv",
        persistent=False,
        allow_reentry=True,
    )
    app.add_handler(obs_conv)

    # === Conversación ADMIN (Allowed) ===
    admin_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(admin_add_start, pattern=r"^ADMIN:ADD$"),
            CallbackQueryHandler(admin_del_start, pattern=r"^ADMIN:DEL$"),
        ],
        states={
            ADM_ADD_ID: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_id_text),
                CallbackQueryHandler(admin_cancel_cb, pattern=r"^MENU:ADMIN$")
            ],
            ADM_DEL_ID: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_del_id_text),
                CallbackQueryHandler(admin_cancel_cb, pattern=r"^MENU:ADMIN$")
            ],
        },
        fallbacks=[CallbackQueryHandler(admin_cancel_cb, pattern=r"^MENU:ADMIN$")],
        name="admin_ids_conv",
        persistent=False,
        allow_reentry=True,
    )
    app.add_handler(admin_conv)

    # === Conversación ADMIN (Admins) ===
    admin_admins_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(admin_add_admin_start, pattern=r"^ADMIN:ADM_ADD$"),
            CallbackQueryHandler(admin_del_admin_start, pattern=r"^ADMIN:ADM_DEL$"),
        ],
        states={
            ADM_ADM_ADD_ID: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_admin_text),
                CallbackQueryHandler(admin_cancel_cb, pattern=r"^MENU:ADMIN$")
            ],
            ADM_ADM_DEL_ID: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_del_admin_text),
                CallbackQueryHandler(admin_cancel_cb, pattern=r"^MENU:ADMIN$")
            ],
        },
        fallbacks=[CallbackQueryHandler(admin_cancel_cb, pattern=r"^MENU:ADMIN$")],
        name="admin_admins_conv",
        persistent=False,
        allow_reentry=True,
    )
    app.add_handler(admin_admins_conv)

    # === Menú + callbacks ===
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("menu", cmd_menu))
    app.add_handler(CallbackQueryHandler(on_menu_callback, pattern=r"^MENU:"))
    app.add_handler(CallbackQueryHandler(on_menu_callback, pattern=r"^ADMIN:"))
    app.add_handler(CallbackQueryHandler(on_page_callback, pattern=r"^PAGE:\d+$"))

    # Editor de pendientes
    app.add_handler(CallbackQueryHandler(on_edit_page_callback, pattern=r"^EDITPAGE:\d+$"))
    app.add_handler(CallbackQueryHandler(on_edit_pick_row, pattern=r"^EDIT:\d+$"))
    app.add_handler(CallbackQueryHandler(
        on_edit_set_state,
        pattern=r"^SET:\d+:(Aceptado|Rechazado|Pendiente|Número incorrecto)$"
    ))

    # Comandos clásicos
    app.add_handler(CommandHandler("get_lista", cmd_get_lista))
    app.add_handler(CommandHandler("get_pendientes", cmd_get_pendientes))
    app.add_handler(CommandHandler("get_aceptados", cmd_get_aceptados))
    app.add_handler(CommandHandler("get_rechazados", cmd_get_rechazados))
    app.add_handler(CommandHandler("gen_contacts", cmd_gen_contacts))
    app.add_handler(CommandHandler("vcard", cmd_vcard))
    app.add_handler(CommandHandler("whoami", cmd_whoami))

    # Errores
    app.add_error_handler(handle_error)

    # === Polling o Webhook ===
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
