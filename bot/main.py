import os
import logging

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from bot.handlers.add_contact import build_add_conv
from bot.handlers.edit import (
    on_edit_page_callback,
    on_edit_pick_row,
    on_edit_set_state,
    obs_cancel_cb,
    obs_text_handler,
)
from bot.handlers.admin import (
    admin_add_start,
    admin_del_start,
    admin_add_admin_start,
    admin_del_admin_start,
    admin_add_id_text,
    admin_del_id_text,
    admin_add_admin_text,
    admin_del_admin_text,
    admin_cancel_cb,
)
from bot.handlers.menu import (
    cmd_start,
    cmd_menu,
    on_menu_callback,
    on_page_callback,
    on_list_edit_start,
)
from bot.handlers.commands import (
    cmd_get_lista,
    cmd_get_pendientes,
    cmd_get_aceptados,
    cmd_get_rechazados,
    cmd_gen_contacts,
    cmd_vcard,
    cmd_whoami,
)
from bot.handlers.errors import handle_error
from bot.states import (
    EDIT_OBS,
    ADM_ADD_ID,
    ADM_DEL_ID,
    ADM_ADM_ADD_ID,
    ADM_ADM_DEL_ID,
)

print("BOT_UNICO VERSION -> FLEX+MENU + SHEETS + EDIT + ADD + RESERVAS + VCF + ROLES + NOMBRES + OBS + ADMINS 7.0")

def build_obs_conv():
    return ConversationHandler(
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

def build_admin_allowed_conv():
    return ConversationHandler(
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

def build_admin_admins_conv():
    return ConversationHandler(
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

def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("Falta TELEGRAM_BOT_TOKEN.")
    mode = os.environ.get("TG_MODE", "polling").strip().lower()

    app = ApplicationBuilder().token(token).build()

    # Conversations
    app.add_handler(build_add_conv())
    app.add_handler(build_obs_conv())
    app.add_handler(build_admin_allowed_conv())
    app.add_handler(build_admin_admins_conv())

    # Menú + callbacks
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("menu", cmd_menu))
    app.add_handler(CallbackQueryHandler(on_menu_callback, pattern=r"^MENU:"))
    app.add_handler(CallbackQueryHandler(on_menu_callback, pattern=r"^ADMIN:"))
    app.add_handler(CallbackQueryHandler(on_page_callback, pattern=r"^PAGE:\d+$"))
    app.add_handler(CallbackQueryHandler(on_list_edit_start, pattern=r"^LISTEDIT:\d+$"))

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

    # Polling o Webhook
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
