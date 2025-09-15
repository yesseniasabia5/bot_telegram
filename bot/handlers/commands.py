from typing import List

from telegram import Update
from telegram.ext import ContextTypes

from bot.auth import require_auth, get_display_for_uid
from bot.config import CSV_HEADERS, IDX
from bot.services.lista import read_lista_any, set_lista_any, filter_by_status, _pad_row
from bot.services.exports import gen_contacts_any, gen_vcard_any

@require_auth
async def cmd_get_lista(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = read_lista_any()
    if not rows:
        return await update.message.reply_text("La lista está vacía.")
    block = []
    for i, r in enumerate(rows, 1):
        r = _pad_row(r, len(CSV_HEADERS))
        block.append(f"{r[IDX['Teléfono']]}: {r[IDX['Nombre']]}, {r[IDX['Apellido']]}")
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
        # Modificar la fila original (referencia compartida con all_rows)
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
    import os
    out = os.path.join("export", "contacts.csv")
    os.makedirs("export", exist_ok=True)
    gen_contacts_any(out)
    await update.message.reply_text(f"Archivo escrito: {out}")

@require_auth
async def cmd_vcard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    import os
    out = os.path.join("export", "lista.vcf")
    os.makedirs("export", exist_ok=True)
    gen_vcard_any(out, etiqueta="General")
    await update.message.reply_text(f"Archivo escrito: {out}")

@require_auth
async def cmd_whoami(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    if not u:
        return await update.message.reply_text("No se pudo determinar tu usuario.")
    name = u.full_name or (f"@{u.username}" if u.username else "")
    await update.message.reply_text(f"Tu user_id: {u.id}\nNombre: {name}")
