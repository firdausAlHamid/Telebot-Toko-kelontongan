"""
Developer Handlers — /dev command with TOTP 2FA.
Only the system developer (role='developer') can access this panel.

Security flow:
  /dev → TOTP verify (or QR setup first-time) → session unlocked 10 min → developer menu
"""

import io
import logging
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes, CommandHandler, CallbackQueryHandler,
    MessageHandler, ConversationHandler, filters
)

from auth import (
    is_developer,
    is_dev_session_active, activate_dev_session, deactivate_dev_session, dev_session_remaining,
    has_totp_setup, verify_totp, generate_totp_qr,
    register_vendor, register_kasir, deactivate_user, list_users_by_role,
)
from config import DEVELOPER_TELEGRAM_ID
from database import SessionLocal, BotUser, Tenant, Transaction

logger = logging.getLogger(__name__)

# ── Conversation states ────────────────────────────────────────────────────────
(
    DEV_TOTP_INPUT,       # Waiting for 6-digit TOTP code
    DEV_MENU,             # Main developer menu (callback-based)
    DEV_REGISTER_ID,      # Waiting for vendor Telegram ID text input
    DEV_REGISTER_NAME,    # Waiting for store name text input
    DEV_DEACTIVATE_SEL,   # Waiting for deactivation target selection
    DEV_SWITCH_STORE,     # Waiting for store selection to switch into
) = range(6)


# ==============================================================================
# ENTRY POINT
# ==============================================================================

async def dev_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/dev — entry point. Checks role, TOTP setup, and session state."""
    user = update.effective_user

    # ── Role guard ────────────────────────────────────────────────────────────
    if not is_developer(user.id):
        await update.message.reply_text("⛔ Akses ditolak.")
        return ConversationHandler.END

    # ── Session still active? Skip TOTP ───────────────────────────────────────
    if is_dev_session_active(context):
        remaining = dev_session_remaining(context)
        await update.message.reply_text(
            f"✅ Sesi aktif ({remaining // 60}m {remaining % 60}s tersisa)."
        )
        return await _show_dev_menu(update, context)

    # ── First-time: generate and send QR setup ────────────────────────────────
    if not has_totp_setup(user.id):
        qr_bytes, secret, _ = generate_totp_qr(user.id, user.full_name or "Developer")
        qr_io = io.BytesIO(qr_bytes)

        await update.message.reply_photo(
            photo=qr_io,
            caption=(
                "🔐 *Setup Autentikasi 2FA — Langkah Pertama*\n\n"
                "1️⃣ Buka *Google Authenticator* atau *Authy* di HP\n"
                "2️⃣ Pilih *Tambah akun* → *Scan QR code*\n"
                "3️⃣ Scan gambar QR di atas\n"
                "4️⃣ Masukkan kode 6 digit yang muncul di sini:\n\n"
                f"🔑 Kode manual (backup): `{secret}`\n"
                "⚠️ Simpan kode backup ini di tempat aman!"
            ),
            parse_mode="Markdown"
        )
        context.user_data["dev_totp_first_setup"] = True
        return DEV_TOTP_INPUT

    # ── Already set up: ask for code ─────────────────────────────────────────
    await update.message.reply_text(
        "🔐 *Developer Panel*\n\nMasukkan kode TOTP 6 digit dari Google Authenticator:",
        parse_mode="Markdown"
    )
    return DEV_TOTP_INPUT


# ==============================================================================
# TOTP VERIFICATION
# ==============================================================================

async def handle_totp_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Verify TOTP code entered by developer."""
    code = update.message.text.strip().replace(" ", "")
    user = update.effective_user

    if not code.isdigit() or len(code) != 6:
        await update.message.reply_text(
            "❌ Kode harus tepat 6 angka. Coba lagi:"
        )
        return DEV_TOTP_INPUT

    if verify_totp(user.id, code):
        activate_dev_session(context)
        is_first = context.user_data.pop("dev_totp_first_setup", False)
        if is_first:
            await update.message.reply_text(
                "✅ *Setup berhasil! 2FA aktif.*\n\n"
                "Mulai sekarang kamu harus input kode TOTP setiap kali membuka panel developer.",
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text("✅ Verifikasi berhasil!")
        return await _show_dev_menu(update, context)
    else:
        await update.message.reply_text(
            "❌ *Kode salah atau sudah expired.*\n\n"
            "Pastikan waktu HP sinkron dengan internet, lalu coba lagi:",
            parse_mode="Markdown"
        )
        return DEV_TOTP_INPUT


# ==============================================================================
# DEVELOPER MENU
# ==============================================================================

async def _show_dev_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Render the developer main menu."""
    remaining = dev_session_remaining(context)
    mins = remaining // 60
    secs = remaining % 60

    keyboard = [
        [InlineKeyboardButton("📋 Lihat Semua Vendor",          callback_data="dv_list_vendor")],
        [InlineKeyboardButton("➕ Daftarkan Vendor Baru",       callback_data="dv_add_vendor")],
        [InlineKeyboardButton("🏪 Masuk ke Toko (Mode Kasir)", callback_data="dv_switch_store")],
        [InlineKeyboardButton("❌ Nonaktifkan Vendor",          callback_data="dv_deactivate")],
        [InlineKeyboardButton("📊 Statistik Sistem",            callback_data="dv_stats")],
        [InlineKeyboardButton("🔒 Kunci Sesi",                  callback_data="dv_lock")],
    ]

    text = (
        f"👨‍💻 *Developer Panel*\n"
        f"⏱ Sesi aktif: {mins}m {secs}s\n\n"
        "Pilih aksi:"
    )

    if update.callback_query:
        await update.callback_query.edit_message_text(
            text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
        )
    return DEV_MENU


async def handle_dev_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Route developer menu callbacks."""
    query = update.callback_query
    await query.answer()
    data = query.data

    # ── Session guard: if expired mid-use ─────────────────────────────────────
    if not is_dev_session_active(context) and data != "dv_lock":
        await query.edit_message_text(
            "⏰ Sesi expired. Ketik /dev untuk login ulang."
        )
        return ConversationHandler.END

    # ── Route ─────────────────────────────────────────────────────────────────
    if data == "dv_menu":
        return await _show_dev_menu(update, context)

    elif data == "dv_list_vendor":
        vendors = list_users_by_role("vendor")
        if not vendors:
            text = "📋 *Daftar Vendor*\n\n_Belum ada vendor terdaftar._"
        else:
            text = f"📋 *Daftar Vendor* ({len(vendors)} toko)\n\n"
            for v in vendors:
                uname = f"@{v['telegram_username']}" if v['telegram_username'] else f"`{v['telegram_id']}`"
                text += (
                    f"🏪 *{v['store_name']}*\n"
                    f"   👤 {v['full_name'] or '-'} ({uname})\n"
                    f"   🆔 `{v['telegram_id']}`\n\n"
                )
        keyboard = [[InlineKeyboardButton("🔙 Kembali", callback_data="dv_menu")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        return DEV_MENU

    elif data == "dv_add_vendor":
        await query.edit_message_text(
            "➕ *Daftarkan Vendor Baru*\n\n"
            "Masukkan *Telegram ID* pemilik toko:\n"
            "_(Minta mereka kirim pesan ke @userinfobot)_\n\n"
            "/cancel untuk batal",
            parse_mode="Markdown"
        )
        return DEV_REGISTER_ID

    elif data == "dv_switch_store":
        # Show list of tenants for developer to switch into
        db = SessionLocal()
        tenants = db.query(Tenant).filter(Tenant.is_active == True).all()
        db.close()

        if not tenants:
            keyboard = [[InlineKeyboardButton("🔙 Kembali", callback_data="dv_menu")]]
            await query.edit_message_text(
                "🏪 Belum ada toko terdaftar.\n\nDaftarkan vendor terlebih dahulu.",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return DEV_MENU

        keyboard = []
        for t in tenants:
            keyboard.append([InlineKeyboardButton(
                f"🏪 {t.store_name} (ID: {t.id})",
                callback_data=f"dv_switchto_{t.id}"
            )])
        keyboard.append([InlineKeyboardButton("🔙 Kembali", callback_data="dv_menu")])

        await query.edit_message_text(
            "🏪 *Masuk ke Toko*\n\n"
            "Pilih toko yang ingin kamu operasikan sebagai kasir:\n"
            "_(Setelah pilih, kamu bisa pakai /start, /promo, /jadwal, dll untuk toko itu)_",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return DEV_SWITCH_STORE

    elif data.startswith("dv_switchto_"):
        tenant_id = int(data.split("_")[2])

        db = SessionLocal()
        tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()

        # Check if developer already registered as kasir under this tenant
        existing_kasir = db.query(BotUser).filter(
            BotUser.telegram_id == update.effective_user.id,
            BotUser.tenant_id == tenant_id
        ).first()

        if not existing_kasir:
            # Register developer as kasir for this tenant (special override)
            dev_user = db.query(BotUser).filter(
                BotUser.telegram_id == update.effective_user.id
            ).first()
            if dev_user:
                # Update developer's tenant_id so they can operate this store
                # We do NOT change role — developer keeps developer role
                dev_user.tenant_id = tenant_id
                db.commit()

        store_name = tenant.store_name if tenant else f"Tenant #{tenant_id}"
        db.close()

        keyboard = [[InlineKeyboardButton("🔙 Menu Developer", callback_data="dv_menu")]]
        await query.edit_message_text(
            f"✅ *Kamu sekarang beroperasi di toko:*\n🏪 *{store_name}*\n\n"
            f"Gunakan perintah berikut:\n"
            f"• /start → Buka kasir / transaksi\n"
            f"• /promo → Kelola promosi toko ini\n"
            f"• /jadwal → Kelola jadwal toko ini\n"
            f"• /laporan → Lihat laporan penjualan\n"
            f"• /void → Void transaksi\n\n"
            f"_Kamu tetap bisa kembali ke /dev kapan saja._",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return DEV_MENU

    elif data == "dv_deactivate":
        vendors = list_users_by_role("vendor")
        if not vendors:
            keyboard = [[InlineKeyboardButton("🔙 Kembali", callback_data="dv_menu")]]
            await query.edit_message_text(
                "❌ Belum ada vendor untuk dinonaktifkan.",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return DEV_MENU

        keyboard = []
        for v in vendors:
            label = f"🏪 {v['store_name']} | ID: {v['telegram_id']}"
            keyboard.append([InlineKeyboardButton(label, callback_data=f"dv_deact_{v['telegram_id']}")])
        keyboard.append([InlineKeyboardButton("🔙 Kembali", callback_data="dv_menu")])

        await query.edit_message_text(
            "❌ *Nonaktifkan Vendor*\nPilih vendor:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return DEV_DEACTIVATE_SEL

    elif data == "dv_stats":
        db = SessionLocal()
        vendor_count = db.query(BotUser).filter(BotUser.role == "vendor",    BotUser.is_active == True).count()
        kasir_count  = db.query(BotUser).filter(BotUser.role == "kasir",     BotUser.is_active == True).count()
        tenant_count = db.query(Tenant).filter(Tenant.is_active == True).count()
        trx_count    = db.query(Transaction).count()
        db.close()

        text = (
            "📊 *Statistik Sistem*\n\n"
            f"🏪 Toko aktif (vendor): *{vendor_count}*\n"
            f"🏬 Tenant terdaftar: *{tenant_count}*\n"
            f"👤 Kasir aktif: *{kasir_count}*\n"
            f"🧾 Total transaksi: *{trx_count}*\n"
        )
        keyboard = [[InlineKeyboardButton("🔙 Kembali", callback_data="dv_menu")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        return DEV_MENU

    elif data == "dv_lock":
        deactivate_dev_session(context)
        await query.edit_message_text("🔒 Sesi dikunci. Ketik /dev untuk login ulang.")
        return ConversationHandler.END

    return DEV_MENU


# ==============================================================================
# REGISTER VENDOR FLOW
# ==============================================================================

async def handle_register_vendor_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Step 1: receive vendor Telegram ID."""
    text = update.message.text.strip()

    if not text.isdigit():
        await update.message.reply_text(
            "❌ Telegram ID harus angka (contoh: `1234567890`).\nCoba lagi:",
            parse_mode="Markdown"
        )
        return DEV_REGISTER_ID

    target_id = int(text)

    if target_id == DEVELOPER_TELEGRAM_ID:
        await update.message.reply_text("❌ Tidak bisa mendaftarkan diri sendiri sebagai vendor.")
        return DEV_REGISTER_ID

    context.user_data["reg_vendor_id"] = target_id
    await update.message.reply_text(
        f"✅ Telegram ID: `{target_id}`\n\n"
        "Masukkan *nama toko/kios*:",
        parse_mode="Markdown"
    )
    return DEV_REGISTER_NAME


async def handle_register_vendor_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Step 2: receive store name and complete registration."""
    store_name = update.message.text.strip()
    vendor_id  = context.user_data.pop("reg_vendor_id", None)

    if not vendor_id:
        await update.message.reply_text("❌ Terjadi error. Mulai ulang dengan /dev.")
        return ConversationHandler.END

    if len(store_name) < 2:
        await update.message.reply_text("❌ Nama toko terlalu pendek. Minimal 2 karakter:")
        return DEV_REGISTER_NAME

    success, message, tenant_id = register_vendor(
        telegram_id=vendor_id,
        store_name=store_name,
        added_by=update.effective_user.id,
    )

    if success:
        # Try to notify the vendor
        try:
            await context.bot.send_message(
                chat_id=vendor_id,
                text=(
                    "🎉 *Toko kamu sudah terdaftar di sistem POS!*\n\n"
                    f"🏪 Nama Toko: *{store_name}*\n"
                    f"🆔 Tenant ID: `{tenant_id}`\n\n"
                    "Ketik /panel untuk membuka panel manajemen toko.\n"
                    "Dari sana kamu bisa mendaftarkan kasir."
                ),
                parse_mode="Markdown"
            )
            notify_status = "✅ Notifikasi terkirim ke vendor."
        except Exception:
            notify_status = "⚠️ Gagal kirim notifikasi (vendor belum pernah start bot ini)."

        await update.message.reply_text(
            f"✅ {message}\n{notify_status}\n\nKetik /dev untuk kembali ke panel.",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            f"❌ {message}\n\nKetik /dev untuk kembali ke panel.",
            parse_mode="Markdown"
        )

    return ConversationHandler.END


# ==============================================================================
# DEACTIVATE VENDOR
# ==============================================================================

async def handle_deactivate_vendor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle vendor deactivation selection callback."""
    query = update.callback_query
    await query.answer()

    if query.data == "dv_menu":
        return await _show_dev_menu(update, context)

    if query.data.startswith("dv_deact_"):
        target_id = int(query.data.split("_")[2])
        success, message = deactivate_user(target_id)
        icon = "✅" if success else "❌"
        keyboard = [[InlineKeyboardButton("🔙 Menu Developer", callback_data="dv_menu")]]
        await query.edit_message_text(
            f"{icon} {message}",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return DEV_MENU

    return DEV_DEACTIVATE_SEL


# ==============================================================================
# CANCEL
# ==============================================================================

async def dev_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel current developer operation."""
    context.user_data.pop("reg_vendor_id", None)
    await update.message.reply_text("❌ Operasi dibatalkan. Ketik /dev untuk kembali ke panel.")
    return ConversationHandler.END


# ==============================================================================
# CONVERSATION HANDLER FACTORY
# ==============================================================================

def get_dev_handler() -> ConversationHandler:
    """Create and return the developer ConversationHandler."""
    return ConversationHandler(
        entry_points=[CommandHandler("dev", dev_command)],
        states={
            DEV_TOTP_INPUT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_totp_input),
            ],
            DEV_MENU: [
                CallbackQueryHandler(handle_dev_menu, pattern="^dv_"),
            ],
            DEV_REGISTER_ID: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_register_vendor_id),
            ],
            DEV_REGISTER_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_register_vendor_name),
            ],
            DEV_DEACTIVATE_SEL: [
                CallbackQueryHandler(handle_deactivate_vendor, pattern="^dv_"),
            ],
            DEV_SWITCH_STORE: [
                CallbackQueryHandler(handle_dev_menu, pattern="^dv_"),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", dev_cancel),
            CommandHandler("dev", dev_command),
        ],
        per_user=True,
        per_chat=True,
    )
