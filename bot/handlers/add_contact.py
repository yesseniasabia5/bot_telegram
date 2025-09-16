import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import ContextTypes, ConversationHandler, MessageHandler, CallbackQueryHandler, CommandHandler, filters

from bot.states import ADD_NOMBRE, ADD_APELLIDO, ADD_TELEFONO, ADD_DNI, ADD_ESTADO, ADD_CANCEL_CONFIRM
from bot.services.lista import _clean_phone, append_contact_any
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
    raw = (update.message.text or "").strip()
    phone = _clean_phone(raw)
    if not phone or not re.fullmatch(r"\+?\d+", phone):
        await update.message.reply_text("⚠️ El teléfono debe tener solo dígitos y opcionalmente un `+` al inicio. Intentá de nuevo.", parse_mode="Markdown")
        return ADD_TELEFONO
    context.user_data["new_contact"]["Teléfono"] = phone
    await update.message.reply_text("4/5) *DNI* (opcional):", parse_mode="Markdown")
    return ADD_DNI

async def add_dni(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["new_contact"]["DNI"] = update.message.text.strip()
    buttons = [
        [InlineKeyboardButton("Pendiente", callback_data="ADD_STATE:PENDIENTE"), InlineKeyboardButton("Aceptado", callback_data="ADD_STATE:ACEPTADO")],
        [InlineKeyboardButton("Rechazado", callback_data="ADD_STATE:RECHAZADO"), InlineKeyboardButton("Número incorrecto", callback_data="ADD_STATE:INCORRECTO")],
        [InlineKeyboardButton("Contactar Luego", callback_data="ADD_STATE:CONTACTAR")],
    ]
    await update.message.reply_text(
        "5/5) *Estado*:", parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons)
    )
    return ADD_ESTADO

async def add_estado_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    _, choice = q.data.split(":", 1)
    mapping = {
        "PENDIENTE": "Pendiente",
        "ACEPTADO": "Aceptado",
        "RECHAZADO": "Rechazado",
        "INCORRECTO": "Número incorrecto",
    }
    if choice == "CONTACTAR":
        context.user_data["new_contact"]["Estado"] = "Contactar Luego"
        context.user_data["await_add_obs"] = True
        await q.edit_message_text("Escribí la *observación*:", parse_mode="Markdown")
        return ADD_ESTADO
    estado = mapping.get(choice, "Pendiente")
    context.user_data["new_contact"]["Estado"] = estado
    await q.edit_message_text(f"Estado seleccionado: {estado}")
    return await _finalize_new_contact(update, context, estado)


async def _finalize_new_contact(update: Update, context: ContextTypes.DEFAULT_TYPE, estado: str, observacion: str = ""):
    data = context.user_data.get("new_contact", {})
    row = [
        data.get("Nombre", ""),
        data.get("Apellido", ""),
        data.get("Teléfono", ""),
        data.get("DNI", ""),
        estado,
        observacion,
    ]
    result = append_contact_any(row)
    verb = "actualizado" if result == "updated" else "agregado"
    message = update.effective_message

    await message.reply_text(
        f"✅ Contacto {verb}\n\n{_format_persona(row)}",
        parse_mode="Markdown", reply_markup=ReplyKeyboardRemove()
    )
    context.user_data.pop("await_add_obs", None)
    context.user_data.pop("new_contact", None)
    await cmd_menu(update, context)
    return ConversationHandler.END


async def add_estado_observacion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("await_add_obs"):
        return ConversationHandler.END
    obs = (update.message.text or "").strip()
    return await _finalize_new_contact(update, context, "Contactar Luego", observacion=obs)

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
        await cmd_menu(update, context)
        return ConversationHandler.END
    else:
        await q.edit_message_text("Continuemos. Repetí el dato anterior.")
        # Seguimos en el estado actual esperando el dato anterior
        return ConversationHandler.END

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
                CallbackQueryHandler(add_estado_choice, pattern="^ADD_STATE:"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_estado_observacion),
            ],
            ADD_CANCEL_CONFIRM: [CallbackQueryHandler(on_cancel_callback, pattern="^CANCEL:")],
        },
        fallbacks=[CommandHandler("cancel", add_cancel)],
        name="add_contact_conv",
        persistent=False,
        allow_reentry=True,
    )
