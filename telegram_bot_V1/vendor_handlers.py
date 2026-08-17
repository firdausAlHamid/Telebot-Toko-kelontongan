"""
Vendor Handlers — /panel command for store owner (vendor) management.
Vendor can register/deactivate kasir and view store information.
"""

import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes, CommandHandler, CallbackQueryHandler,
    MessageHandler, ConversationHandler, filters
)

from auth import is_vendor, register_kasir, list_kasir_for_vendor, deactivate_user, get_tenant_id
from database import SessionLocal, BotUser, Tenant

logger = logging.getLogger(__name__)

# ── Conversation states ────────────────────────────────────────────────────────
(
    VENDOR_MENU,          # Main vendor menu (callback-based)
    VENDOR_ADD_KASIR_ID,  # Waiting for kasir Telegram ID text input
    VENDOR_DEACT_SEL,     # Waiting for deactivate target selection
) = range(3)


# ==============================================================================
# ENTRY POINT
# ==============================================================================

async def panel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/panel — entry point for vendor management."""
    user = update.effective_user

    if not is_vendor(user.id):
        await update.message.reply_text(
            "⛔ Akses ditolak. Command ini hanya untuk pemilik toko (vendor)."
        )
        return ConversationHandler.END

    return await _show_vendor_menu(update, context)


# ==============================================================================
# VENDOR MENU
# ==============================================================================

async def _show_vendor_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Render vendor main menu."""
    user_id = update.effective_user.id

    db = SessionLocal()
    vendor = db.query(BotUser).filter(BotUser.telegram_id == user_id).first()
    tenant = (
        db.query(Tenant).filter(Tenant.id == vendor.tenant_id).first()
        if vendor and vendor.tenant_id else None
    )
    db.close()

    store_name = tenant.store_name if tenant else "Toko Kamu"

    keyboard = [
        [InlineKeyboardButton("👥 Lihat Daftar Kasir",    callback_data="vn_list_kasir")],
        [InlineKeyboardButton("➕ Tambah Kasir Baru",     callback_data="vn_add_kasir")],
        [InlineKeyboardButton("❌ Nonaktifkan Kasir",     callback_data="vn_deact_kasir")],
        [InlineKeyboardButton("🏪 Info Toko",             callback_data="vn_info")],
    ]

    text = f"🏪 *Panel Vendor — {store_name}*\n\nPilih aksi:"

    if update.callback_query:
        await update.callback_query.edit_message_text(
            text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
        )
    return VENDOR_MENU


async def handle_vendor_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Route vendor menu callbacks."""
    query = update.callback_query
    await query.answer()
    data    = query.data
    user_id = update.effective_user.id

    if data == "vn_menu":
        return await _show_vendor_menu(update, context)

    # ── Lihat daftar kasir ────────────────────────────────────────────────────
    elif data == "vn_list_kasir":
        kasirs = list_kasir_for_vendor(user_id)
        if not kasirs:
            text = "👥 *Daftar Kasir*\n\n_Belum ada kasir terdaftar._"
        else:
            text = f"👥 *Daftar Kasir* ({len(kasirs)} orang)\n\n"
            for k in kasirs:
                uname = f"@{k['telegram_username']}" if k['telegram_username'] else f"`{k['telegram_id']}`"
                text += (
                    f"• *{k['full_name'] or '-'}* ({uname})\n"
                    f"  🆔 `{k['telegram_id']}`\n"
                )
        keyboard = [[InlineKeyboardButton("🔙 Kembali", callback_data="vn_menu")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        return VENDOR_MENU

    # ── Tambah kasir ─────────────────────────────────────────────────────────
    elif data == "vn_add_kasir":
        await query.edit_message_text(
            "➕ *Tambah Kasir Baru*\n\n"
            "Masukkan *Telegram ID* kasir yang ingin didaftarkan:\n"
            "_(Minta kasir kirim pesan ke @userinfobot untuk dapat ID-nya)_\n\n"
            "/cancel untuk batal",
            parse_mode="Markdown"
        )
        return VENDOR_ADD_KASIR_ID

    # ── Nonaktifkan kasir ─────────────────────────────────────────────────────
    elif data == "vn_deact_kasir":
        kasirs = list_kasir_for_vendor(user_id)
        if not kasirs:
            keyboard = [[InlineKeyboardButton("🔙 Kembali", callback_data="vn_menu")]]
            await query.edit_message_text(
                "❌ Tidak ada kasir aktif untuk dinonaktifkan.",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return VENDOR_MENU

        keyboard = []
        for k in kasirs:
            uname = k['telegram_username'] or str(k['telegram_id'])
            label = f"{k['full_name'] or uname} | ID: {k['telegram_id']}"
            keyboard.append([InlineKeyboardButton(label, callback_data=f"vn_deact_{k['telegram_id']}")])
        keyboard.append([InlineKeyboardButton("🔙 Kembali", callback_data="vn_menu")])

        await query.edit_message_text(
            "❌ *Nonaktifkan Kasir*\nPilih kasir:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return VENDOR_DEACT_SEL

    # ── Info toko ─────────────────────────────────────────────────────────────
    elif data == "vn_info":
        db = SessionLocal()
        vendor = db.query(BotUser).filter(BotUser.telegram_id == user_id).first()
        tenant = (
            db.query(Tenant).filter(Tenant.id == vendor.tenant_id).first()
            if vendor and vendor.tenant_id else None
        )
        kasir_count = db.query(BotUser).filter(
            BotUser.tenant_id == (vendor.tenant_id if vendor else 0),
            BotUser.role == "kasir",
            BotUser.is_active == True
        ).count()
        db.close()

        eff_user = update.effective_user
        text = (
            "🏪 *Info Toko*\n\n"
            f"📛 Nama Toko: *{tenant.store_name if tenant else '-'}*\n"
            f"🆔 Tenant ID: `{vendor.tenant_id if vendor else '-'}`\n"
            f"👤 Pemilik: {eff_user.full_name}\n"
            f"🔖 Username: @{eff_user.username or '-'}\n"
            f"👥 Kasir aktif: {kasir_count}\n"
        )
        keyboard = [[InlineKeyboardButton("🔙 Kembali", callback_data="vn_menu")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        return VENDOR_MENU

    return VENDOR_MENU


# ==============================================================================
# ADD KASIR FLOW
# ==============================================================================

async def handle_add_kasir_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receive kasir Telegram ID and register them."""
    text    = update.message.text.strip()
    user_id = update.effective_user.id

    if not text.isdigit():
        await update.message.reply_text(
            "❌ Telegram ID harus angka (contoh: `1234567890`).\nCoba lagi:",
            parse_mode="Markdown"
        )
        return VENDOR_ADD_KASIR_ID

    kasir_id = int(text)

    if kasir_id == user_id:
        await update.message.reply_text("❌ Kamu tidak bisa mendaftarkan diri sendiri sebagai kasir.")
        return VENDOR_ADD_KASIR_ID

    success, message = register_kasir(kasir_id, user_id)

    if success:
        try:
            await context.bot.send_message(
                chat_id=kasir_id,
                text=(
                    "🎉 *Kamu sudah terdaftar sebagai Kasir.*\n\n"
                    "Ketik /start untuk mulai menggunakan sistem POS."
                ),
                parse_mode="Markdown"
            )
            notify = "✅ Notifikasi terkirim ke kasir."
        except Exception:
            notify = "⚠️ Gagal kirim notifikasi (kasir belum pernah start bot ini)."

        await update.message.reply_text(
            f"✅ {message}\n{notify}\n\nKetik /panel untuk kembali.",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            f"❌ {message}\n\nKetik /panel untuk kembali.",
            parse_mode="Markdown"
        )

    return ConversationHandler.END


# ==============================================================================
# DEACTIVATE KASIR
# ==============================================================================

async def handle_deactivate_kasir(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle kasir deactivation selection callback."""
    query   = update.callback_query
    await query.answer()
    user_id = update.effective_user.id

    if query.data == "vn_menu":
        return await _show_vendor_menu(update, context)

    if query.data.startswith("vn_deact_"):
        target_id = int(query.data.split("_")[2])

        # Security: verify this kasir actually belongs to this vendor's tenant
        kasirs    = list_kasir_for_vendor(user_id)
        kasir_ids = [k["telegram_id"] for k in kasirs]
        if target_id not in kasir_ids:
            await query.edit_message_text("❌ Kasir tidak ditemukan di toko kamu.")
            return VENDOR_MENU

        success, message = deactivate_user(target_id)
        icon    = "✅" if success else "❌"
        keyboard = [[InlineKeyboardButton("🔙 Menu Vendor", callback_data="vn_menu")]]
        await query.edit_message_text(
            f"{icon} {message}",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return VENDOR_MENU

    return VENDOR_DEACT_SEL


# ==============================================================================
# CANCEL
# ==============================================================================

async def vendor_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel current vendor operation."""
    await update.message.reply_text("❌ Operasi dibatalkan. Ketik /panel untuk kembali.")
    return ConversationHandler.END


# ==============================================================================
# CONVERSATION HANDLER FACTORY
# ==============================================================================

def get_vendor_handler() -> ConversationHandler:
    """Create and return the vendor ConversationHandler."""
    return ConversationHandler(
        entry_points=[CommandHandler("panel", panel_command)],
        states={
            VENDOR_MENU: [
                CallbackQueryHandler(handle_vendor_menu, pattern="^vn_"),
            ],
            VENDOR_ADD_KASIR_ID: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_add_kasir_id),
            ],
            VENDOR_DEACT_SEL: [
                CallbackQueryHandler(handle_deactivate_kasir, pattern="^vn_"),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", vendor_cancel),
            CommandHandler("panel", panel_command),
        ],
        per_user=True,
        per_chat=True,
    )
