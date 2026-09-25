"""
Shared main-menu inline callbacks.

Kept in a separate module so ConversationHandler fallbacks can open the POS
catalog without circular imports against main.py.
"""

import importlib
import logging

from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

logger = logging.getLogger(__name__)


async def handle_main_transaksi(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Open product catalog from the main menu inline button."""
    query = update.callback_query
    user_id = update.effective_user.id

    if query:
        try:
            await query.answer()
        except Exception as exc:
            logger.warning("Could not answer callback query: %s", exc)

    try:
        from auth import is_kasir as auth_is_kasir

        if not auth_is_kasir(user_id):
            if query:
                await query.edit_message_text("⛔ Kamu belum terdaftar.")
            return

        main = importlib.import_module("main")
        main.ensure_cart_loaded(user_id, context)
        text = main.build_cart_text_from_memory(
            context, "🏪 *Katalog Produk*\n\nSilakan pilih kategori:"
        )
        reply_markup = main.build_categories_keyboard()

        if query:
            await query.edit_message_text(
                text, reply_markup=reply_markup, parse_mode="Markdown"
            )
        elif update.message:
            await update.message.reply_text(
                text, reply_markup=reply_markup, parse_mode="Markdown"
            )
    except Exception as exc:
        logger.error("[ERROR] handle_main_transaksi: %s", exc, exc_info=True)
        err_msg = f"⚠️ Terjadi kesalahan saat memuat katalog: {exc}"
        if query:
            try:
                await query.edit_message_text(err_msg)
            except Exception:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id, text=err_msg
                )
        elif update.message:
            await update.message.reply_text(err_msg)


async def fallback_main_transaksi_end_conv(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    """ConversationHandler fallback: leave admin flow and open catalog."""
    await handle_main_transaksi(update, context)
    return ConversationHandler.END
