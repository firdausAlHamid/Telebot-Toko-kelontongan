"""
dev_handlers.py — Tool TESTING: ganti role & toko akun sendiri
==============================================================
Khusus developer (telegram_id ada di config.DEV_TELEGRAM_IDS).
User lain yang ngetik /devrole bakal dicuekin.

Alur:  /devrole  →  pilih role  →  pilih toko  →  langsung jadi role itu
Pilihan "Reset" = jadi user baru (belum terdaftar), buat ngetes
alur token / deep link t.me/<bot>?start=toko_<id>.
"""

import logging
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler, CallbackQueryHandler

from config import DEV_TELEGRAM_IDS
from database import SessionLocal, BotUser, Tenant, Product, CartItem
from menu_helpers import build_main_menu_keyboard

logger = logging.getLogger(__name__)

ROLE_LABEL = {
    "owner": "👑 Owner",
    "kasir": "🧾 Kasir",
    "customer": "🙋 Customer",
}


def _is_dev(user_id: int) -> bool:
    return user_id in DEV_TELEGRAM_IDS


def _status_text(user_id: int) -> str:
    db = SessionLocal()
    u = db.query(BotUser).filter(BotUser.telegram_id == user_id).first()
    if not u or not u.is_active:
        db.close()
        return "Status sekarang: *belum terdaftar*"
    t = db.query(Tenant).filter(Tenant.id == u.tenant_id).first()
    db.close()
    toko = f"{t.store_name} (id {t.id})" if t else "-"
    return f"Status sekarang: *{ROLE_LABEL.get(u.role, u.role)}* di *{toko}*"


def _role_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(ROLE_LABEL["owner"], callback_data="dev_role_owner"),
         InlineKeyboardButton(ROLE_LABEL["kasir"], callback_data="dev_role_kasir")],
        [InlineKeyboardButton(ROLE_LABEL["customer"], callback_data="dev_role_customer")],
        [InlineKeyboardButton("🚪 Reset (jadi user baru)", callback_data="dev_reset")],
    ])


async def devrole_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not _is_dev(user_id):
        return
    await update.message.reply_text(
        f"🛠 *Mode Testing — Ganti Role*\n{_status_text(user_id)}\n\nMau jadi apa?",
        parse_mode="Markdown",
        reply_markup=_role_keyboard(),
    )


async def devrole_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = update.effective_user.id
    if not _is_dev(user_id):
        await query.answer()
        return
    await query.answer()
    data = query.data

    # ── Step 1: pilih role → tampilkan daftar toko ───────────────────────
    if data.startswith("dev_role_"):
        role = data.removeprefix("dev_role_")
        db = SessionLocal()
        tenants = db.query(Tenant).filter(Tenant.is_active == True).order_by(Tenant.id).all()
        rows = []
        for t in tenants:
            n = db.query(Product).filter(Product.tenant_id == t.id).count()
            rows.append([InlineKeyboardButton(
                f"🏪 {t.store_name} · {n} produk", callback_data=f"dev_set_{role}_{t.id}"
            )])
        db.close()
        rows.append([InlineKeyboardButton("⬅️ Kembali", callback_data="dev_back")])
        await query.edit_message_text(
            f"Jadi *{ROLE_LABEL[role]}* di toko mana?",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(rows),
        )
        return

    if data == "dev_back":
        await query.edit_message_text(
            f"🛠 *Mode Testing — Ganti Role*\n{_status_text(user_id)}\n\nMau jadi apa?",
            parse_mode="Markdown",
            reply_markup=_role_keyboard(),
        )
        return

    # ── Step 2: terapkan role + toko ─────────────────────────────────────
    db = SessionLocal()
    user = db.query(BotUser).filter(BotUser.telegram_id == user_id).first()

    if data == "dev_reset":
        if user:
            user.is_active = False
        db.query(CartItem).filter(CartItem.user_id == user_id).delete()
        db.commit()
        db.close()
        context.user_data.clear()
        bot_username = context.bot.username
        await query.edit_message_text(
            "🚪 Akun di-reset → sekarang kamu *user baru*.\n\n"
            "Buat ngetes:\n"
            "• Ketik /start → muncul halaman pendaftaran\n"
            "• Paste token `POS-KASIR-...` / `POS-OWNER-...`\n"
            f"• Atau buka link customer: `t.me/{bot_username}?start=toko_1`\n\n"
            "Balik lagi kapan aja pakai /devrole",
            parse_mode="Markdown",
        )
        return

    if data.startswith("dev_set_"):
        _, _, role, tid = data.split("_", 3)
        tenant_id = int(tid)
        tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
        if not tenant or role not in ROLE_LABEL:
            db.close()
            await query.edit_message_text("❌ Toko/role nggak valid.")
            return

        tg = update.effective_user
        if not user:
            user = BotUser(telegram_id=user_id, role=role, tenant_id=tenant_id)
            db.add(user)
        user.role = role
        user.tenant_id = tenant_id
        user.is_active = True
        user.telegram_username = tg.username
        user.full_name = tg.full_name
        user.updated_at = datetime.now()
        if role == "owner":
            tenant.owner_id = user_id

        # Keranjang lama bisa berisi produk toko lain → buang
        db.query(CartItem).filter(CartItem.user_id == user_id).delete()
        db.commit()
        store_name = tenant.store_name
        db.close()
        context.user_data.clear()

        logger.info("DEV role switch: %s → %s @ tenant %s", user_id, role, tenant_id)
        await query.edit_message_text(
            f"✅ Sekarang kamu *{ROLE_LABEL[role]}* di *{store_name}*\n\n"
            f"👋 Halo, *{tg.first_name}*!\n🏪 Toko: *{store_name}*\n\nPilih menu di bawah ini:",
            parse_mode="Markdown",
            reply_markup=build_main_menu_keyboard(user_id=user_id),
        )
        return

    db.close()


def get_dev_handlers():
    """Daftarkan PALING AWAL di main.py supaya nggak ketelen handler lain."""
    return [
        CommandHandler("devrole", devrole_command),
        CallbackQueryHandler(devrole_callback, pattern=r"^dev_"),
    ]
