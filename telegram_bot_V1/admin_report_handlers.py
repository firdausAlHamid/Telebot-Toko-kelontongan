"""
Admin Report & Transaction Handlers — /laporan and /void commands.
Provides sales reports and transaction void capability for admins.
"""

import logging
import math
from datetime import date, timedelta

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes, CommandHandler, CallbackQueryHandler,
    MessageHandler, ConversationHandler, filters
)

from auth import is_kasir, is_vendor
from transaction_service import (
    get_daily_summary, get_period_summary, get_top_products,
    get_transaction_history, get_transaction_detail,
    void_transaction, format_date_indo, format_datetime_indo
)

logger = logging.getLogger(__name__)

# --- Conversation States ---
(REPORT_MENU, REPORT_VIEW,
 VOID_LIST, VOID_DETAIL, VOID_CONFIRM) = range(5)


# =============================================================================
# HELPERS
# =============================================================================

def is_admin(update: Update) -> bool:
    """Check if the user has admin-level access (kasir, vendor, or developer)."""
    return is_kasir(update.effective_user.id)


# =============================================================================
# /laporan — SALES REPORT
# =============================================================================

async def laporan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Entry point: /laporan command — shows report period selection."""
    if not is_admin(update):
        if update.message:
            await update.message.reply_text("⛔ Akses ditolak. Hanya admin.")
        return ConversationHandler.END

    keyboard = [
        [InlineKeyboardButton("📊 Hari Ini", callback_data="rpt_today")],
        [InlineKeyboardButton("📊 Kemarin", callback_data="rpt_yesterday")],
        [InlineKeyboardButton("📊 Minggu Ini", callback_data="rpt_week")],
        [InlineKeyboardButton("📊 Bulan Ini", callback_data="rpt_month")],
        [InlineKeyboardButton("🏆 Produk Terlaris (Hari Ini)", callback_data="rpt_top_today")],
        [InlineKeyboardButton("🏆 Produk Terlaris (Bulan Ini)", callback_data="rpt_top_month")],
    ]

    text = "📊 *Laporan Penjualan*\n\nPilih periode laporan:"

    if update.callback_query:
        await update.callback_query.edit_message_text(
            text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
        )

    return REPORT_MENU


async def handle_report_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle report period selection."""
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "rpt_menu":
        return await laporan_command(update, context)

    today = date.today()

    if data == "rpt_today":
        summary = get_daily_summary(today)
        title = f"📊 Laporan Hari Ini — {summary['date_str']}"
        text = _build_summary_text(title, summary)

    elif data == "rpt_yesterday":
        yesterday = today - timedelta(days=1)
        summary = get_daily_summary(yesterday)
        title = f"📊 Laporan Kemarin — {summary['date_str']}"
        text = _build_summary_text(title, summary)

    elif data == "rpt_week":
        start = today - timedelta(days=today.weekday())  # Monday
        summary = get_period_summary(start, today)
        title = f"📊 Laporan Minggu Ini\n📅 {summary['start_date_str']} — {summary['end_date_str']}"
        text = _build_summary_text(title, summary)

    elif data == "rpt_month":
        start = today.replace(day=1)
        summary = get_period_summary(start, today)
        title = f"📊 Laporan Bulan Ini\n📅 {summary['start_date_str']} — {summary['end_date_str']}"
        text = _build_summary_text(title, summary)

    elif data == "rpt_top_today":
        top = get_top_products(today, today, limit=10)
        text = _build_top_products_text("🏆 Produk Terlaris Hari Ini", top)

    elif data == "rpt_top_month":
        start = today.replace(day=1)
        top = get_top_products(start, today, limit=10)
        text = _build_top_products_text("🏆 Produk Terlaris Bulan Ini", top)

    else:
        return REPORT_MENU

    keyboard = [[InlineKeyboardButton("🔙 Menu Laporan", callback_data="rpt_menu")]]
    await query.edit_message_text(
        text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
    )
    return REPORT_VIEW


async def handle_report_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle back navigation from report view."""
    query = update.callback_query
    await query.answer()
    if query.data == "rpt_menu":
        return await laporan_command(update, context)
    return REPORT_VIEW


def _build_summary_text(title, summary):
    """Build formatted summary text."""
    text = f"*{title}*\n"
    text += "━━━━━━━━━━━━━━━━━━━━\n\n"

    text += f"🧾 Total Transaksi: *{summary['total_transactions']}*\n"
    text += f"💰 Total Pendapatan: *Rp{summary['total_revenue']:,}*\n"

    if summary['total_discount'] > 0:
        text += f"🏷️ Total Diskon: *-Rp{summary['total_discount']:,}*\n"

    text += f"📊 Rata-rata/Transaksi: *Rp{summary['avg_transaction']:,}*\n\n"

    # Payment breakdown
    if summary['payment_breakdown']:
        text += "💳 *Metode Pembayaran:*\n"
        for method, info in summary['payment_breakdown'].items():
            text += f"   • {method}: {info['count']}x — Rp{info['amount']:,}\n"
        text += "\n"

    # Voided
    if summary['voided_count'] > 0:
        text += f"❌ Transaksi Void: *{summary['voided_count']}* (Rp{summary['voided_amount']:,})\n"

    if summary['total_transactions'] == 0:
        text += "\n_Belum ada transaksi pada periode ini._"

    return text


def _build_top_products_text(title, products):
    """Build top products text."""
    text = f"*{title}*\n"
    text += "━━━━━━━━━━━━━━━━━━━━\n\n"

    if not products:
        text += "_Belum ada data penjualan._"
        return text

    for i, p in enumerate(products, 1):
        medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
        text += f"{medal} *{p['product_name']}*\n"
        text += f"    📦 Terjual: {p['total_qty']}x — Rp{p['total_revenue']:,}\n"

    return text


# =============================================================================
# /void — VOID TRANSACTION
# =============================================================================

async def void_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Entry point: /void command — shows today's transactions for voiding."""
    if not is_admin(update):
        if update.message:
            await update.message.reply_text("⛔ Akses ditolak. Hanya admin.")
        return ConversationHandler.END

    return await _show_void_list(update, context)


async def _show_void_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show today's completed transactions for void selection."""
    transactions, total = get_transaction_history(status="completed", limit=15)

    # Filter only today's transactions
    today_start = date.today()
    today_trx = [
        t for t in transactions
        if t['created_at'] and hasattr(t['created_at'], 'date')
        and t['created_at'].date() == today_start
    ]

    if not today_trx:
        text = "❌ *Void Transaksi*\n\n_Tidak ada transaksi hari ini yang bisa di-void._"
        keyboard = []
        if update.callback_query:
            await update.callback_query.edit_message_text(text, parse_mode="Markdown")
        else:
            await update.message.reply_text(text, parse_mode="Markdown")
        return ConversationHandler.END

    text = "❌ *Void Transaksi*\n\nPilih transaksi hari ini yang ingin di-void:"

    keyboard = []
    for t in today_trx:
        time_str = t['created_at'].strftime('%H:%M') if hasattr(t['created_at'], 'strftime') else ""
        label = f"{t['invoice_no']} | {time_str} | Rp{t['grand_total']:,}"
        keyboard.append([InlineKeyboardButton(label, callback_data=f"vd_sel_{t['id']}")])

    if update.callback_query:
        await update.callback_query.edit_message_text(
            text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
        )

    return VOID_LIST


async def handle_void_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle transaction selection — show detail and confirm void."""
    query = update.callback_query
    await query.answer()
    data = query.data

    if not data.startswith("vd_sel_"):
        return VOID_LIST

    trx_id = int(data.split("_")[2])
    trx, items = get_transaction_detail(trx_id)

    if not trx:
        await query.edit_message_text("❌ Transaksi tidak ditemukan.")
        return ConversationHandler.END

    text = f"❌ *Void Transaksi*\n\n"
    text += f"🧾 *{trx['invoice_no']}*\n"
    text += f"📅 {trx['created_at_str']}\n"
    text += f"💳 {trx['payment_method']}\n"
    text += "━━━━━━━━━━━━━━━━━━━━\n"

    if items:
        for item in items:
            text += f"▪️ {item['product_name']} x{item['quantity']} — Rp{item['subtotal']:,}\n"
            if item['discount_amount'] > 0:
                text += f"   🏷️ Diskon: -Rp{item['discount_amount']:,}\n"
    else:
        text += "_Detail item tidak tersedia (transaksi lama)_\n"

    text += "━━━━━━━━━━━━━━━━━━━━\n"
    text += f"💰 *Grand Total: Rp{trx['grand_total']:,}*\n\n"
    text += "⚠️ *Yakin ingin void transaksi ini?*"

    context.user_data["void_trx_id"] = trx_id

    keyboard = [
        [InlineKeyboardButton("✅ Ya, Void", callback_data=f"vd_ok_{trx_id}")],
        [InlineKeyboardButton("❌ Batal", callback_data="vd_cancel")],
    ]

    await query.edit_message_text(
        text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
    )
    return VOID_CONFIRM


async def handle_void_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Execute the void."""
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "vd_cancel":
        await query.edit_message_text("❌ Void dibatalkan.")
        return ConversationHandler.END

    if data.startswith("vd_ok_"):
        trx_id = int(data.split("_")[2])
        success, message = void_transaction(trx_id)

        icon = "✅" if success else "❌"
        await query.edit_message_text(f"{icon} {message}")
        return ConversationHandler.END

    return VOID_CONFIRM


async def void_cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel void operation."""
    await update.message.reply_text("❌ Operasi void dibatalkan.")
    return ConversationHandler.END


# =============================================================================
# /riwayat — TRANSACTION HISTORY (accessible by everyone)
# =============================================================================

async def riwayat_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show last 5 transactions for the current user (or all for admin)."""
    user_id = update.effective_user.id
    # Vendor & developer see all transactions; kasir sees only their own
    if is_vendor(user_id):
        transactions, total = get_transaction_history(limit=10)
        title = f"📜 *Riwayat Transaksi* (semua — {total} total)"
    else:
        transactions, total = get_transaction_history(user_id=user_id, limit=5)
        title = f"📜 *Riwayat Transaksi Kamu* ({total} total)"

    if not transactions:
        await update.message.reply_text(
            f"{title}\n\n_Belum ada riwayat transaksi._",
            parse_mode="Markdown"
        )
        return

    text = f"{title}\n"
    text += "━━━━━━━━━━━━━━━━━━━━\n\n"

    keyboard = []

    for t in transactions:
        status_icon = "✅" if t['status'] == "completed" else "❌"
        text += f"{status_icon} *{t['invoice_no']}*\n"
        text += f"   📅 {t['created_at_str']}\n"
        text += f"   💳 {t['payment_method']} — Rp{t['grand_total']:,}\n\n"

        keyboard.append([InlineKeyboardButton(
            f"📋 Detail {t['invoice_no']}",
            callback_data=f"trx_detail_{t['id']}"
        )])

    reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
    await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")


async def handle_trx_detail_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inline button click to show transaction detail."""
    query = update.callback_query
    await query.answer()

    if not query.data.startswith("trx_detail_"):
        return

    trx_id = int(query.data.split("_")[2])
    trx, items = get_transaction_detail(trx_id)

    if not trx:
        await query.edit_message_text("❌ Transaksi tidak ditemukan.")
        return

    text = f"📋 *Detail Transaksi*\n"
    text += "━━━━━━━━━━━━━━━━━━━━\n"
    text += f"🧾 Invoice: *{trx['invoice_no']}*\n"
    text += f"📅 {trx['created_at_str']}\n"
    text += f"💳 Pembayaran: {trx['payment_method']}\n"

    status_label = "✅ Selesai" if trx['status'] == "completed" else "❌ Void"
    text += f"📌 Status: {status_label}\n"

    if trx['status'] == "voided" and trx.get('void_reason'):
        text += f"📝 Alasan: {trx['void_reason']}\n"

    text += "━━━━━━━━━━━━━━━━━━━━\n\n"

    if items:
        text += "🛒 *Daftar Belanjaan:*\n"
        for item in items:
            text += f"▪️ {item['product_name']}\n"
            text += f"   {item['quantity']}x Rp{item['unit_price']:,} = Rp{item['quantity'] * item['unit_price']:,}\n"
            if item['discount_amount'] > 0:
                disc_label = f"{item['discount_value']}%" if item['discount_type'] == 'percentage' else f"Rp{item['discount_value']:,}"
                text += f"   🏷️ Diskon {disc_label}: -Rp{item['discount_amount']:,}\n"
        text += "\n"

    text += "━━━━━━━━━━━━━━━━━━━━\n"
    text += f"💰 Subtotal: Rp{trx['subtotal']:,}\n"

    if trx['total_discount'] > 0:
        text += f"🏷️ Total Diskon: -Rp{trx['total_discount']:,}\n"

    text += f"💵 *Grand Total: Rp{trx['grand_total']:,}*\n"

    if trx['cash_received']:
        text += f"\n💵 Uang Diterima: Rp{trx['cash_received']:,}\n"
        text += f"💰 Kembalian: Rp{trx['cash_change'] or 0:,}\n"

    await query.edit_message_text(text, parse_mode="Markdown")


# =============================================================================
# CONVERSATION HANDLER FACTORIES
# =============================================================================

def get_report_conv_handler():
    """Create and return the admin report ConversationHandler."""
    return ConversationHandler(
        entry_points=[
            CommandHandler("laporan", laporan_command),
        ],
        states={
            REPORT_MENU: [
                CallbackQueryHandler(handle_report_menu, pattern="^rpt_"),
            ],
            REPORT_VIEW: [
                CallbackQueryHandler(handle_report_back, pattern="^rpt_"),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", lambda u, c: ConversationHandler.END),
            CommandHandler("laporan", laporan_command),
        ],
        per_user=True,
        per_chat=True,
    )


def get_void_conv_handler():
    """Create and return the admin void ConversationHandler."""
    return ConversationHandler(
        entry_points=[
            CommandHandler("void", void_command),
        ],
        states={
            VOID_LIST: [
                CallbackQueryHandler(handle_void_select, pattern="^vd_"),
            ],
            VOID_CONFIRM: [
                CallbackQueryHandler(handle_void_confirm, pattern="^vd_"),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", void_cancel_command),
            CommandHandler("void", void_command),
        ],
        per_user=True,
        per_chat=True,
    )
