from telegram import InlineKeyboardMarkup, InlineKeyboardButton, Update
from telegram.ext import ContextTypes, ConversationHandler
from auth import is_registered, get_store_name, can

def build_main_menu_keyboard(user_id: int):
    """Build the main menu inline keyboard based on RBAC permissions."""
    kb = []
    
    if can(user_id, "trx:create"):
        kb.append([InlineKeyboardButton("🛒 Mulai Transaksi", callback_data="main_transaksi")])
        
    row2 = []
    if can(user_id, "stock:view"):
        row2.append(InlineKeyboardButton("📦 Stok Barang", callback_data="stk_menu"))
    if can(user_id, "report:view_shift") or can(user_id, "report:view_tenant"):
        row2.append(InlineKeyboardButton("📊 Laporan", callback_data="main_laporan"))
    if row2:
        kb.append(row2)
        
    row3 = []
    if can(user_id, "promo:view") or can(user_id, "promo:manage"):
        row3.append(InlineKeyboardButton("🏷️ Promo", callback_data="main_promo"))
    if can(user_id, "schedule:view") or can(user_id, "schedule:manage"):
        row3.append(InlineKeyboardButton("🗓️ Jadwal", callback_data="main_jadwal"))
    if row3:
        kb.append(row3)
        
    row4 = []
    if can(user_id, "product:manage"):
        row4.append(InlineKeyboardButton("📦 Produk", callback_data="prod_menu"))
    elif can(user_id, "product:view"):
        row4.append(InlineKeyboardButton("🛒 Katalog Produk", callback_data="customer_katalog"))
        
    if can(user_id, "panel:manage"):
        row4.append(InlineKeyboardButton("⚙️ Panel Owner", callback_data="main_panel"))
    if row4:
        kb.append(row4)
        
    return InlineKeyboardMarkup(kb)

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show the main menu (used as a callback handler and by ConversationHandlers)."""
    query = update.callback_query
    user_id = update.effective_user.id
    tg_user = update.effective_user

    if query:
        await query.answer()

    if not is_registered(user_id):
        text = "⛔ Kamu belum terdaftar."
        if query:
            await query.edit_message_text(text)
        else:
            await update.message.reply_text(text)
        return ConversationHandler.END

    store_name = get_store_name(user_id) or "Toko Kamu"
    text = (
        f"👋 Halo, *{tg_user.first_name}*!\n"
        f"🏪 Toko: *{store_name}*\n\n"
        f"Pilih menu di bawah ini:"
    )

    reply_markup = build_main_menu_keyboard(user_id=user_id)

    if query:
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=reply_markup)
    else:
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=reply_markup)
    
    return ConversationHandler.END
