from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler

from bot.auth import require_admin
from bot.states import ADM_ADD_ID, ADM_DEL_ID, ADM_ADM_ADD_ID, ADM_ADM_DEL_ID
from bot.config import SHEET_ALLOWED, SHEET_ADMINS
from bot.services.roles import _append_id_name_to_sheet, _remove_id_from_sheet


ADMIN_BACK_KB = InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Volver al panel", callback_data="MENU:ADMIN")]])

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
        [InlineKeyboardButton("👥 Ver usuarios permitidos", callback_data="ADMIN:LIST")],
        [InlineKeyboardButton("➕ Agregar ID usuarios permitidos", callback_data="ADMIN:ADD")],
        [InlineKeyboardButton("➖ Quitar ID usuarios permitidos", callback_data="ADMIN:DEL")],
        [InlineKeyboardButton("🏠 Menú", callback_data="MENU:HOME")],
    ]
    await q.message.reply_text("🔐 Panel de administración", reply_markup=InlineKeyboardMarkup(kb))
    return ConversationHandler.END

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
    await update.message.reply_text(f"✅ Agregado a usuarios permitidos: {shown}", reply_markup=ADMIN_BACK_KB)
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
        await update.message.reply_text(f"✅ Quitado de usuarios permitidos: {uid}", reply_markup=ADMIN_BACK_KB)
    else:
        await update.message.reply_text(f"ℹ️ El ID {uid} no estaba en Usuarios permitidos.", reply_markup=ADMIN_BACK_KB)
    return ConversationHandler.END

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
    await update.message.reply_text(f"✅ Agregado a Admins: {shown}", reply_markup=ADMIN_BACK_KB)
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
        await update.message.reply_text(f"✅ Quitado de Admins: {uid}", reply_markup=ADMIN_BACK_KB)
    else:
        await update.message.reply_text(f"ℹ️ El ID {uid} no estaba en Admins.", reply_markup=ADMIN_BACK_KB)
    return ConversationHandler.END

