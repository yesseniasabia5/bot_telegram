from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import ContextTypes, ConversationHandler, MessageHandler, CallbackQueryHandler, CommandHandler, filters

from bot.states import ADD_NOMBRE, ADD_APELLIDO, ADD_TELEFONO, ADD_DNI, ADD_ESTADO, ADD_CANCEL_CONFIRM
from bot.services.lista import _clean_phone, append_contact_any, _pad_row
from bot.utils.pagination import _format_persona

# Import menu to allow returning to it
from bot.handlers.menu import cmd_menu  # circular-safe as menu does not import this module

# release_reservation lives in edit handler (shared by menu/add flows)
from bot.handlers.edit import release_reservation

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
    await update.message.reply_text(
        "5/5) *Estado*:", parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup(kb, one_time_keyboard=True, resize_keyboard=True)
    )
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
        await update.message.reply_text(
            "Escribí la *observación*:", parse_mode="Markdown", reply_markup=ReplyKeyboardRemove()
        )
        return ADD_ESTADO
    else:
        estado = "Pendiente"

    d = context.user_data["new_contact"]
    row = [d.get("Nombre",""), d.get("Apellido",""), d.get("Teléfono",""), d.get("DNI",""), estado, ""]
    res = append_contact_any(row)
    verb = "actualizado" if res == "updated" else "agregado"
    await update.message.reply_text(
        f"✅ Contacto {verb}\n\n{_format_persona(row)}",
        parse_mode="Markdown", reply_markup=ReplyKeyboardRemove()
    )
    return await cmd_menu(update, context)

async def add_estado_observacion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("await_add_obs"):
        return ConversationHandler.END
    obs = (update.message.text or "").strip()
    d = context.user_data["new_contact"]
    row = [d.get("Nombre",""), d.get("Apellido",""), d.get("Teléfono",""), d.get("DNI",""),
           "Contactar Luego", obs]
    res = append_contact_any(row)
    verb = "actualizado" if res == "updated" else "agregado"
    await update.message.reply_text(
        f"✅ Contacto {verb}\n\n{_format_persona(row)}",
        parse_mode="Markdown", reply_markup=ReplyKeyboardRemove()
    )
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

def build_add_conv():
    return ConversationHandler(
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

