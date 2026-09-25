"""
owner_handlers.py — /panel command for store owner management.

Owner can:
  - Generate kasir invitation tokens
  - View/deactivate kasir
  - View store info
  - Open the Mini App dashboard

All kasir management is done via token (no direct Telegram ID input).
"""

import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import (
    ContextTypes, CommandHandler, CallbackQueryHandler,
    ConversationHandler, filters, MessageHandler
)

from auth import is_owner, generate_kasir_token, list_kasir_for_owner, deactivate_user, get_store_name
from menu_callbacks import fallback_main_transaksi_end_conv
from database import SessionLocal, BotUser, Tenant

# ── Try to import config ───────────────────────────────────────────────────────
try:
    from config import API_BASE_URL
except ImportError:
    API_BASE_URL = "http://localhost:8000"

logger = logging.getLogger(__name__)

# ── Conversation states ────────────────────────────────────────────────────────
(
    OWNER_MENU,        # Main owner menu
    OWNER_DEACT_SEL,   # Waiting for deactivate target selection
) = range(2)


# ==============================================================================
# ENTRY POINT
# ==============================================================================

async def panel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/panel — entry point for owner management."""
    user = update.effective_user

    if not is_owner(user.id):
        await update.message.reply_text(
            "⛔ Akses ditolak. Command ini hanya untuk pemilik toko (owner)."
        )
        return ConversationHandler.END

    return await _show_owner_menu(update, context)


# ==============================================================================
# OWNER MENU
# ==============================================================================

async def _show_owner_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Render owner main menu."""
    user_id = update.effective_user.id
    store_name = get_store_name(user_id) or "Toko Kamu"

    # Mini App URL
    mini_app_url = f"{API_BASE_URL.rstrip('/')}/miniapp/"

    keyboard = []
    if mini_app_url.startswith("https://"):
        keyboard.append([InlineKeyboardButton("📊 Buka Dashboard", web_app=WebAppInfo(url=mini_app_url))])
    else:
        keyboard.append([InlineKeyboardButton("📊 Buka Dashboard (Lokal)", callback_data="own_dashboard_info")])
    
    keyboard.extend([
        [InlineKeyboardButton("🔑 Generate Token Kasir", callback_data="own_gen_token")],
        [InlineKeyboardButton("👥 Lihat Daftar Kasir",   callback_data="own_list_kasir")],
        [InlineKeyboardButton("❌ Nonaktifkan Kasir",     callback_data="own_deact_kasir")],
        [InlineKeyboardButton("🏪 Info Toko",             callback_data="own_info")],
    ])

    text = f"🏪 *Panel Owner — {store_name}*\n\nPilih aksi:"

    if update.callback_query:
        await update.callback_query.edit_message_text(
            text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
        )
    return OWNER_MENU


# ==============================================================================
# GENERATE KASIR TOKEN
# ==============================================================================

async def handle_gen_token(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generate a kasir invitation token."""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    success, result = generate_kasir_token(user_id)

    if not success:
        await query.edit_message_text(
            f"❌ Gagal generate token: {result}",
            parse_mode="Markdown"
        )
        return OWNER_MENU

    token_str = result
    back_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 Kembali ke Panel", callback_data="own_back")]
    ])

    await query.edit_message_text(
        f"🔑 *Token Kasir Baru*\n\n"
        f"```\n{token_str}\n```\n\n"
        f"📋 *Cara pakai:*\n"
        f"1\\. Salin token di atas\n"
        f"2\\. Bagikan ke kasir kamu\n"
        f"3\\. Kasir buka bot → `/start` → paste token\n\n"
        f"⏰ _Token berlaku selama 48 jam_",
        reply_markup=back_kb,
        parse_mode="MarkdownV2"
    )
    return OWNER_MENU


# ==============================================================================
# LIST KASIR
# ==============================================================================

async def handle_list_kasir(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show list of active kasir in the owner's store."""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    kasirs = list_kasir_for_owner(user_id)

    back_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 Kembali", callback_data="own_back")]
    ])

    if not kasirs:
        await query.edit_message_text(
            "👥 Belum ada kasir yang terdaftar di toko kamu.\n\n"
            "Generate token kasir untuk mengundang kasir baru.",
            reply_markup=back_kb
        )
        return OWNER_MENU

    text = "👥 *Daftar Kasir Aktif:*\n\n"
    for i, k in enumerate(kasirs, 1):
        username_str = f"@{k['telegram_username']}" if k['telegram_username'] else "—"
        name_str = k['full_name'] or "—"
        text += f"{i}. *{name_str}* ({username_str})\n"
        text += f"   ID: `{k['telegram_id']}`\n\n"

    await query.edit_message_text(text, reply_markup=back_kb, parse_mode="Markdown")
    return OWNER_MENU


# ==============================================================================
# DEACTIVATE KASIR
# ==============================================================================

async def handle_deact_kasir_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show kasir selection for deactivation."""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    kasirs = list_kasir_for_owner(user_id)

    if not kasirs:
        back_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Kembali", callback_data="own_back")]
        ])
        await query.edit_message_text(
            "Tidak ada kasir aktif yang bisa dinonaktifkan.",
            reply_markup=back_kb
        )
        return OWNER_MENU

    keyboard = []
    for k in kasirs:
        label = k['full_name'] or k['telegram_username'] or f"ID:{k['telegram_id']}"
        keyboard.append([
            InlineKeyboardButton(
                f"❌ {label}",
                callback_data=f"own_deact_{k['telegram_id']}"
            )
        ])
    keyboard.append([InlineKeyboardButton("🔙 Kembali", callback_data="own_back")])

    await query.edit_message_text(
        "⚠️ *Pilih kasir yang ingin dinonaktifkan:*",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return OWNER_DEACT_SEL


async def handle_deact_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Execute kasir deactivation."""
    query = update.callback_query
    await query.answer()

    target_id = int(query.data.split("_")[-1])
    success, msg = deactivate_user(target_id)

    back_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 Kembali ke Panel", callback_data="own_back")]
    ])

    status = "✅" if success else "❌"
    await query.edit_message_text(
        f"{status} {msg}",
        reply_markup=back_kb
    )
    return OWNER_MENU


# ==============================================================================
# STORE INFO
# ==============================================================================

async def handle_store_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show store information."""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    db = SessionLocal()
    owner = db.query(BotUser).filter(BotUser.telegram_id == user_id).first()
    tenant = (
        db.query(Tenant).filter(Tenant.id == owner.tenant_id).first()
        if owner and owner.tenant_id else None
    )
    kasir_count = (
        db.query(BotUser).filter(
            BotUser.tenant_id == owner.tenant_id,
            BotUser.role == "kasir",
            BotUser.is_active == True
        ).count()
        if owner and owner.tenant_id else 0
    )
    db.close()

    back_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 Kembali", callback_data="own_back")]
    ])

    if not tenant:
        await query.edit_message_text("Informasi toko tidak ditemukan.", reply_markup=back_kb)
        return OWNER_MENU

    text = (
        f"🏪 *Informasi Toko*\n\n"
        f"📌 Nama Toko: *{tenant.store_name}*\n"
        f"👤 Owner ID: `{user_id}`\n"
        f"👥 Kasir Aktif: *{kasir_count} orang*\n"
        f"📅 Terdaftar: {tenant.created_at.strftime('%d/%m/%Y') if tenant.created_at else '—'}\n"
    )
    await query.edit_message_text(text, reply_markup=back_kb, parse_mode="Markdown")
    return OWNER_MENU


async def handle_dashboard_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show info for local dashboard URL."""
    query = update.callback_query
    await query.answer()
    mini_app_url = f"{API_BASE_URL.rstrip('/')}/miniapp/"
    text = (
        f"📊 *Dashboard Mini App (Dev Mode)*\n\n"
        f"Gunakan URL berikut di browser Anda:\n`{mini_app_url}`\n\n"
        f"💡 _Telegram mewajibkan HTTPS untuk membuka Mini App langsung di dalam aplikasi Telegram._"
    )
    keyboard = [[InlineKeyboardButton("🔙 Kembali", callback_data="own_back")]]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    return OWNER_MENU


# ==============================================================================
# CONVERSATION HANDLER BUILDER
# ==============================================================================

def get_owner_handler() -> ConversationHandler:
    """Build and return the ConversationHandler for /panel."""
    return ConversationHandler(
        entry_points=[
            CommandHandler("panel", panel_command),
            CallbackQueryHandler(panel_command, pattern="^main_panel$"),
        ],
        states={
            OWNER_MENU: [
                CallbackQueryHandler(handle_dashboard_info, pattern="^own_dashboard_info$"),
                CallbackQueryHandler(handle_gen_token,      pattern="^own_gen_token$"),
                CallbackQueryHandler(handle_list_kasir,     pattern="^own_list_kasir$"),
                CallbackQueryHandler(handle_deact_kasir_menu, pattern="^own_deact_kasir$"),
                CallbackQueryHandler(handle_store_info,     pattern="^own_info$"),
                CallbackQueryHandler(_show_owner_menu,      pattern="^own_back$"),
            ],
            OWNER_DEACT_SEL: [
                CallbackQueryHandler(handle_deact_confirm,  pattern="^own_deact_\\d+$"),
                CallbackQueryHandler(_show_owner_menu,      pattern="^own_back$"),
            ],
        },
        fallbacks=[
            CallbackQueryHandler(
                fallback_main_transaksi_end_conv, pattern="^main_transaksi$"
            ),
            CommandHandler("cancel", lambda u, c: ConversationHandler.END),
            CommandHandler("panel", panel_command),
        ],
        allow_reentry=True,
        per_user=True,
        per_chat=True,
        per_message=False,
    )
