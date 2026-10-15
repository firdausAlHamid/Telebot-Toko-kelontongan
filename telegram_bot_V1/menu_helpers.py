from telegram import (
    InlineKeyboardMarkup, InlineKeyboardButton, Update, WebAppInfo,
    ReplyKeyboardMarkup, KeyboardButton
)
from telegram.ext import ContextTypes, ConversationHandler
from auth import is_registered, get_store_name, can, is_kasir, is_owner

try:
    from config import API_BASE_URL
except ImportError:
    API_BASE_URL = "http://localhost:8001"


def get_miniapp_urls():
    try:
        import config
        base = config.API_BASE_URL.rstrip('/')
    except Exception:
        base = "http://localhost:8001"
    return {
        "store": f"{base}/miniapp/index.html",
        "store_customer": f"{base}/miniapp/index.html?mode=customer",
        "dashboard": f"{base}/miniapp/dashboard.html",
        "stok": f"{base}/miniapp/dashboard.html?tab=stok",
        "stok_foto": f"{base}/miniapp/dashboard.html?tab=stok&action=ocr",
        "stok_excel": f"{base}/miniapp/dashboard.html?tab=stok&action=excel",
        "laporan": f"{base}/miniapp/dashboard.html?tab=ringkasan",
        "transaksi": f"{base}/miniapp/dashboard.html?tab=transaksi",
        "kasir": f"{base}/miniapp/dashboard.html?tab=kasir",
        "pos": f"{base}/miniapp/dashboard.html",
    }


def build_persistent_reply_keyboard(user_id: int | None = None):
    """Build persistent keyboard with web_app button at bottom of chat."""
    urls = get_miniapp_urls()
    if user_id and (is_kasir(user_id) or is_owner(user_id)):
        return ReplyKeyboardMarkup(
            [[KeyboardButton("💻 Buka Kasir (POS)", web_app=WebAppInfo(url=urls["dashboard"]))]],
            resize_keyboard=True,
            is_persistent=True
        )
    return ReplyKeyboardMarkup(
        [[KeyboardButton("🛍️ Buka Toko", web_app=WebAppInfo(url=urls["store"]))]],
        resize_keyboard=True,
        is_persistent=True
    )


def build_customer_menu_keyboard():
    """Build inline keyboard for customers — each button opens a Mini App popup."""
    urls = get_miniapp_urls()
    kb = [
        [InlineKeyboardButton("🛍️ Buka Toko (Katalog Belanja)", web_app=WebAppInfo(url=urls["store"]))],
        [
            InlineKeyboardButton("📦 Cek Stok Barang", web_app=WebAppInfo(url=urls["stok"])),
            InlineKeyboardButton("🧾 Riwayat Transaksi", web_app=WebAppInfo(url=urls["transaksi"]))
        ],
        [InlineKeyboardButton("🏪 Informasi Toko", web_app=WebAppInfo(url=urls["store"]))]
    ]
    return InlineKeyboardMarkup(kb)


def build_main_menu_keyboard(user_id: int):
    """Build main menu inline keyboard — ALL options open Mini App popups (no chat spam)."""
    urls = get_miniapp_urls()
    kb = []
    
    # Staff / Kasir: Tombol utama langsung buka Kasir POS
    if is_kasir(user_id) or is_owner(user_id):
        kb.append([InlineKeyboardButton("💻 Buka Kasir (POS)", web_app=WebAppInfo(url=urls["dashboard"]))])
    else:
        kb.append([InlineKeyboardButton("🛍️ Buka Toko (Katalog Belanja)", web_app=WebAppInfo(url=urls["store"]))])
    
    # Baris fitur input produk: Tambah via Foto Catatan (AI OCR) & Kelola Spreadsheet Excel
    row_new = [
        InlineKeyboardButton("📷 Tambah via Foto", web_app=WebAppInfo(url=urls["stok_foto"])),
        InlineKeyboardButton("📊 Spreadsheet Excel", web_app=WebAppInfo(url=urls["stok_excel"]))
    ]
    kb.append(row_new)

    row2 = []
    if can(user_id, "stock:view") or can(user_id, "product:view"):
        row2.append(InlineKeyboardButton("📦 Stok & Produk", web_app=WebAppInfo(url=urls["stok"])))
    if can(user_id, "report:view_shift") or can(user_id, "report:view_tenant"):
        row2.append(InlineKeyboardButton("📊 Laporan Penjualan", web_app=WebAppInfo(url=urls["laporan"])))
    if row2:
        kb.append(row2)
        
    row3 = []
    if can(user_id, "history:view_self") or can(user_id, "history:view_tenant"):
        row3.append(InlineKeyboardButton("🧾 Riwayat Transaksi", web_app=WebAppInfo(url=urls["transaksi"])))
    if can(user_id, "panel:manage") or can(user_id, "consign:manage"):
        row3.append(InlineKeyboardButton("⚙️ Panel Owner & Kasir", web_app=WebAppInfo(url=urls["kasir"])))
    elif can(user_id, "promo:view") or can(user_id, "schedule:view"):
        row3.append(InlineKeyboardButton("🏷️ Promo & Jadwal", web_app=WebAppInfo(url=urls["dashboard"])))
    if row3:
        kb.append(row3)
        
    return InlineKeyboardMarkup(kb)


async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show the main menu (used as a callback handler and by ConversationHandlers)."""
    query = update.callback_query
    user_id = update.effective_user.id
    tg_user = update.effective_user

    if query:
        await query.answer()

    store_name = get_store_name(user_id) or "Toko Kelontong"
    text = (
        f"👋 Halo, *{tg_user.first_name}*!\n"
        f"🏪 Toko: *{store_name}*\n\n"
        f"Silakan pilih menu di bawah ini untuk membuka Mini App:"
    )

    if not is_registered(user_id):
        reply_markup = build_customer_menu_keyboard()
    else:
        reply_markup = build_main_menu_keyboard(user_id=user_id)

    if query:
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=reply_markup)
    else:
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=reply_markup)
    
    return ConversationHandler.END
