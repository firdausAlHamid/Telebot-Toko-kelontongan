"""
Admin Schedule Handlers — Telegram ConversationHandler for store schedule CRUD.
All admin flows use inline keyboards with 'as_' callback data prefix.
"""

import logging
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes, CommandHandler, CallbackQueryHandler,
    MessageHandler, ConversationHandler, filters
)

from auth import is_kasir as _is_kasir
from schedule_service import (
    create_schedule, list_schedules, delete_schedule, update_schedule
)
from promotion_service import format_date_indo

logger = logging.getLogger(__name__)

# --- Conversation States ---
(SCHED_MENU,
 ADD_SDATE, ADD_EDATE, ADD_STATUS, ADD_HOURS, ADD_REASON, ADD_CONFIRM,
 DEL_SEL, DEL_CONFIRM) = range(9)


# =============================================================================
# HELPERS
# =============================================================================

def is_admin(update: Update) -> bool:
    """Check if the user has admin-level access (kasir, vendor, or developer)."""
    return _is_kasir(update.effective_user.id)


# =============================================================================
# MAIN MENU
# =============================================================================

async def sched_menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Entry point: /jadwal command — shows admin schedule menu."""
    if not is_admin(update):
        if update.message:
            await update.message.reply_text("⛔ Akses ditolak. Hanya admin yang bisa mengelola jadwal.")
        return ConversationHandler.END

    keyboard = [
        [InlineKeyboardButton("➕ Tambah Jadwal / Libur", callback_data="as_add")],
        [InlineKeyboardButton("📋 Daftar Jadwal Aktif", callback_data="as_list")],
        [InlineKeyboardButton("🗑 Hapus Jadwal", callback_data="as_del")],
    ]

    text = "🗓️ *Menu Jadwal Operasional*\n\nPilih aksi di bawah:"

    if update.callback_query:
        await update.callback_query.edit_message_text(
            text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
        )

    return SCHED_MENU


async def handle_sched_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Route main menu button clicks."""
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "as_add":
        context.user_data["sched_add"] = {}
        await query.edit_message_text(
            "➕ *Tambah Jadwal*\n\n📅 Masukkan tanggal MULAI jadwal ini berlaku:\n_Format: DD/MM/YYYY (contoh: 01/08/2026)_",
            parse_mode="Markdown"
        )
        return ADD_SDATE
    elif data == "as_list":
        return await show_sched_list(update, context)
    elif data == "as_del":
        return await show_delete_list(update, context)
    elif data == "as_menu":
        return await sched_menu_command(update, context)

    return SCHED_MENU


# =============================================================================
# ADD FLOW
# =============================================================================

async def handle_add_sdate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text_input = update.message.text.strip()
    try:
        start_date = datetime.strptime(text_input, "%d/%m/%Y").date()
    except ValueError:
        await update.message.reply_text("❌ Format salah. Gunakan DD/MM/YYYY:")
        return ADD_SDATE

    context.user_data["sched_add"]["start_date"] = start_date
    await update.message.reply_text(
        f"✅ Tanggal mulai: *{format_date_indo(start_date)}*\n\n"
        f"📅 Masukkan tanggal SELESAI jadwal ini berlaku:\n_Format: DD/MM/YYYY_",
        parse_mode="Markdown"
    )
    return ADD_EDATE


async def handle_add_edate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text_input = update.message.text.strip()
    try:
        end_date = datetime.strptime(text_input, "%d/%m/%Y").date()
    except ValueError:
        await update.message.reply_text("❌ Format salah. Gunakan DD/MM/YYYY:")
        return ADD_EDATE

    if end_date < context.user_data["sched_add"]["start_date"]:
        await update.message.reply_text("❌ Tanggal selesai harus setelah atau sama dengan tanggal mulai. Coba lagi:")
        return ADD_EDATE

    context.user_data["sched_add"]["end_date"] = end_date

    keyboard = [
        [InlineKeyboardButton("🟢 BUKA", callback_data="as_stat_Buka")],
        [InlineKeyboardButton("🔴 TUTUP", callback_data="as_stat_Tutup")],
        [InlineKeyboardButton("❌ Batal", callback_data="as_menu")],
    ]
    await update.message.reply_text(
        "Pilih status operasional toko pada periode ini:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ADD_STATUS


async def handle_add_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "as_menu":
        return await sched_menu_command(update, context)

    status = "Buka" if data == "as_stat_Buka" else "Tutup"
    context.user_data["sched_add"]["status"] = status

    if status == "Buka":
        keyboard = [[InlineKeyboardButton("⏭ Skip (Sama)", callback_data="as_skip_hours")]]
        await query.edit_message_text(
            "⏰ Masukkan jam operasional (contoh: 08:00 - 17:00)\nAtau tekan skip jika sama dengan biasa:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return ADD_HOURS
    else:
        context.user_data["sched_add"]["operating_hours"] = None
        keyboard = [[InlineKeyboardButton("⏭ Skip (Tanpa Alasan)", callback_data="as_skip_reason")]]
        await query.edit_message_text(
            "Toko diset TUTUP.\n📝 Masukkan alasan/keterangan tutup (contoh: Libur Lebaran):",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return ADD_REASON


async def handle_add_hours_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["sched_add"]["operating_hours"] = update.message.text.strip()
    keyboard = [[InlineKeyboardButton("⏭ Skip (Tanpa Alasan)", callback_data="as_skip_reason")]]
    await update.message.reply_text(
        "📝 Masukkan alasan/keterangan (opsional, contoh: Buka setengah hari):\nKetik alasan atau tekan skip:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ADD_REASON


async def handle_add_hours_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "as_skip_hours":
        context.user_data["sched_add"]["operating_hours"] = None
        keyboard = [[InlineKeyboardButton("⏭ Skip (Tanpa Alasan)", callback_data="as_skip_reason")]]
        await query.edit_message_text(
            "📝 Masukkan alasan/keterangan (opsional):\nKetik alasan atau tekan skip:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return ADD_REASON
    return ADD_HOURS


async def handle_add_reason_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["sched_add"]["reason"] = update.message.text.strip()
    return await show_add_confirm(update, context)


async def handle_add_reason_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "as_skip_reason":
        context.user_data["sched_add"]["reason"] = None
        return await show_add_confirm(update, context, from_cb=True)
    return ADD_REASON


async def show_add_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE, from_cb=False):
    data = context.user_data["sched_add"]
    
    text = (
        f"📋 *Konfirmasi Jadwal Baru*\n\n"
        f"📅 Mulai: {format_date_indo(data['start_date'])}\n"
        f"📅 Selesai: {format_date_indo(data['end_date'])}\n"
        f"🚦 Status: *{data['status']}*\n"
        f"⏰ Jam: {data['operating_hours'] or '-'}\n"
        f"📝 Alasan: {data['reason'] or '-'}\n\n"
        f"Simpan jadwal ini?"
    )

    keyboard = [
        [InlineKeyboardButton("✅ Simpan", callback_data="as_asave")],
        [InlineKeyboardButton("❌ Batal", callback_data="as_menu")],
    ]

    if from_cb:
        await update.callback_query.edit_message_text(
            text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
        )
    return ADD_CONFIRM


async def handle_add_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "as_menu":
        return await sched_menu_command(update, context)

    if data == "as_asave":
        s_data = context.user_data["sched_add"]
        sched_id, msg = create_schedule(
            start_date=s_data["start_date"],
            end_date=s_data["end_date"],
            status=s_data["status"],
            operating_hours=s_data.get("operating_hours"),
            reason=s_data.get("reason"),
        )

        keyboard = [[InlineKeyboardButton("🔙 Menu Jadwal", callback_data="as_menu")]]
        await query.edit_message_text(
            f"✅ {msg}", reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return SCHED_MENU

    return ADD_CONFIRM


# =============================================================================
# LIST FLOW
# =============================================================================

async def show_sched_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    scheds = list_schedules(active_only=True)

    if not scheds:
        text = "📋 *Daftar Jadwal Khusus*\n\n_Belum ada jadwal yang diset._"
    else:
        text = f"📋 *Daftar Jadwal Khusus Aktif* ({len(scheds)})\n\n"
        for s in scheds:
            text += (
                f"*#{s['id']}* — {s['status_label']}\n"
                f"   📅 {s['start_date_str']} s/d {s['end_date_str']}\n"
                f"   🚦 Status: {s['status']}\n"
                f"   ⏰ Jam: {s['operating_hours']}\n"
                f"   📝 Ket: {s['reason']}\n\n"
            )

    keyboard = [[InlineKeyboardButton("🔙 Menu Jadwal", callback_data="as_menu")]]

    if update.callback_query:
        await update.callback_query.edit_message_text(
            text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
        )
    return SCHED_MENU


# =============================================================================
# DELETE FLOW
# =============================================================================

async def show_delete_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    scheds = list_schedules(active_only=True)

    if not scheds:
        text = "🗑 *Hapus Jadwal*\n\n_Belum ada jadwal._"
        keyboard = [[InlineKeyboardButton("🔙 Menu Jadwal", callback_data="as_menu")]]
        await update.callback_query.edit_message_text(
            text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
        )
        return SCHED_MENU

    text = "🗑 *Hapus Jadwal*\n\nPilih jadwal yang akan dihapus:"

    keyboard = []
    for s in scheds:
        label = f"#{s['id']} {s['status']} ({s['start_date_str']})"
        keyboard.append([InlineKeyboardButton(label, callback_data=f"as_dsel_{s['id']}")])
    keyboard.append([InlineKeyboardButton("🔙 Menu Jadwal", callback_data="as_menu")])

    await update.callback_query.edit_message_text(
        text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
    )
    return DEL_SEL


async def handle_delete_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "as_menu":
        return await sched_menu_command(update, context)

    if data.startswith("as_dsel_"):
        sched_id = int(data.split("_")[2])
        scheds = list_schedules(active_only=True)
        s = next((x for x in scheds if x["id"] == sched_id), None)

        if not s:
            await query.edit_message_text("❌ Jadwal tidak ditemukan.")
            return SCHED_MENU

        text = (
            f"🗑 *Konfirmasi Hapus*\n\n"
            f"*#{s['id']}* — {s['status']}\n"
            f"📅 {s['start_date_str']} s/d {s['end_date_str']}\n"
            f"📝 {s['reason']}\n\n"
            f"Yakin ingin menghapus jadwal ini?"
        )

        keyboard = [
            [InlineKeyboardButton("✅ Ya, Hapus", callback_data=f"as_dok_{sched_id}")],
            [InlineKeyboardButton("❌ Batal", callback_data="as_menu")],
        ]

        await query.edit_message_text(
            text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
        )
        return DEL_CONFIRM
    return DEL_SEL


async def handle_delete_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "as_menu":
        return await sched_menu_command(update, context)

    if data.startswith("as_dok_"):
        sched_id = int(data.split("_")[2])
        success, msg = delete_schedule(sched_id)

        keyboard = [[InlineKeyboardButton("🔙 Menu Jadwal", callback_data="as_menu")]]
        await query.edit_message_text(f"{'✅' if success else '❌'} {msg}", reply_markup=InlineKeyboardMarkup(keyboard))
        return SCHED_MENU

    return DEL_CONFIRM


# =============================================================================
# CANCEL
# =============================================================================

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel the current operation."""
    await update.message.reply_text("❌ Operasi jadwal dibatalkan.")
    return ConversationHandler.END


# =============================================================================
# CONVERSATION HANDLER FACTORY
# =============================================================================

def get_admin_schedule_handler():
    """Create and return the admin schedule ConversationHandler."""
    return ConversationHandler(
        entry_points=[
            CommandHandler("jadwal", sched_menu_command),
        ],
        states={
            SCHED_MENU: [
                CallbackQueryHandler(handle_sched_menu, pattern="^as_"),
            ],
            ADD_SDATE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_add_sdate),
            ],
            ADD_EDATE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_add_edate),
            ],
            ADD_STATUS: [
                CallbackQueryHandler(handle_add_status, pattern="^as_stat_|as_menu"),
            ],
            ADD_HOURS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_add_hours_text),
                CallbackQueryHandler(handle_add_hours_cb, pattern="^as_skip_hours"),
            ],
            ADD_REASON: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_add_reason_text),
                CallbackQueryHandler(handle_add_reason_cb, pattern="^as_skip_reason"),
            ],
            ADD_CONFIRM: [
                CallbackQueryHandler(handle_add_confirm, pattern="^as_"),
            ],
            DEL_SEL: [
                CallbackQueryHandler(handle_delete_select, pattern="^as_"),
            ],
            DEL_CONFIRM: [
                CallbackQueryHandler(handle_delete_confirm, pattern="^as_"),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_command),
            CommandHandler("jadwal", sched_menu_command),
        ],
        per_user=True,
        per_chat=True,
    )
