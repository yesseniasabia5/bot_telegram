from functools import wraps
from typing import Optional

from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

from bot.services.roles import get_allowed_ids, get_admin_ids, get_allowed_map

def auth_is_locked() -> bool:
    """
    Si FORCE_LOCK=1, el bot SIEMPRE está bloqueado (requiere whitelist),
    incluso si no hay admins/allowed en hojas/entorno.
    """
    import os
    if os.environ.get("FORCE_LOCK", "0").strip() == "1":
        return True
    return bool(get_admin_ids() or get_allowed_ids())

def get_display_for_uid(uid: int, update: Optional[Update] = None) -> str:
    """Nombre para mostrar: primero Sheet (Usuarios permitidos/Admins), luego username/full_name si está en el update, sino uid."""
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

