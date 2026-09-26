"""
product_handlers.py — Product management with inline buttons (based on stock_handlers pattern)
=============================================================
Features:
  ➕ Tambah Produk — add new product
  ✏️ Edit Harga — edit existing product price
  🗑 Hapus Produk — delete product
  📋 Lihat Produk — view products by category
"""

import logging
import math
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes, ConversationHandler, CommandHandler,
    CallbackQueryHandler, MessageHandler, filters
)

from database import SessionLocal, Product
from auth import is_owner, get_tenant_id

logger = logging.getLogger(__name__)

# ── Conversation States ────────────────────────────────────────────────────
(
    PRODUCT_MENU,
    PRODUCT_ADD_CAT,       # picking category for add
    PRODUCT_ADD_NAME,      # typing name for add
    PRODUCT_ADD_PRICE,     # typing price for add
    PRODUCT_EDIT_CAT,      # picking category for edit
    PRODUCT_EDIT_PROD,     # picking product for edit
    PRODUCT_EDIT_PRICE,    # typing price for edit
    PRODUCT_DEL_CAT,       # picking category for delete
    PRODUCT_DEL_PROD,      # picking product for delete
    PRODUCT_VIEW_CAT,      # picking category for view
    PRODUCT_VIEW_PROD,     # picking product for view
) = range(11)

PER_PAGE = 8


def _categories_keyboard(prefix: str, tenant_id=None, page: int = 1):
    """Build a paginated category keyboard."""
    db = SessionLocal()
    cats = db.query(Product.category).filter(
        Product.tenant_id == tenant_id
    ).distinct().order_by(Product.category).all()
    db.close()
    cats = [c[0] for c in cats if c[0]]

    total_pages = max(1, math.ceil(len(cats) / PER_PAGE))
    page = min(page, total_pages)
    start = (page - 1) * PER_PAGE
    page_cats = cats[start:start + PER_PAGE]

    keyboard = []
    row = []
    for cat in page_cats:
        short = cat[:18]
        row.append(InlineKeyboardButton(cat, callback_data=f"{prefix}_{short}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"{prefix}_page_{page - 1}"))
    if page < total_pages:
        nav.append(InlineKeyboardButton("Next ➡️", callback_data=f"{prefix}_page_{page + 1}"))
    if nav:
        keyboard.append(nav)

    keyboard.append([InlineKeyboardButton("🔙 Menu Produk", callback_data="prod_menu_back")])
    return InlineKeyboardMarkup(keyboard)


def _products_keyboard(prefix: str, category_short: str, tenant_id=None, page: int = 1):
    """Build a paginated product keyboard for a category."""
    db = SessionLocal()
    category = db.query(Product.category).filter(
        Product.category.like(f"{category_short}%"),
        Product.tenant_id == tenant_id
    ).first()
    full_cat = category[0] if category else category_short

    q = db.query(Product).filter(
        Product.category == full_cat,
        Product.tenant_id == tenant_id
    ).order_by(Product.item_name)
    total = q.count()
    total_pages = max(1, math.ceil(total / PER_PAGE))
    page = min(page, total_pages)
    products = q.offset((page - 1) * PER_PAGE).limit(PER_PAGE).all()
    db.close()

    keyboard = []
    for p in products:
        label = f"{p.item_name} — Rp{p.price:,}"
        keyboard.append([InlineKeyboardButton(label, callback_data=f"{prefix}_p_{p.id}")])

    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"{prefix}_{category_short}_pg_{page - 1}"))
    if page < total_pages:
        nav.append(InlineKeyboardButton("Next ➡️", callback_data=f"{prefix}_{category_short}_pg_{page + 1}"))
    if nav:
        keyboard.append(nav)

    keyboard.append([InlineKeyboardButton("🔙 Pilih Kategori", callback_data=f"{prefix}_back")])
    keyboard.append([InlineKeyboardButton("🔙 Menu Produk", callback_data="prod_menu_back")])
    return InlineKeyboardMarkup(keyboard), full_cat


def _product_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Tambah Produk", callback_data="product_add")],
        [InlineKeyboardButton("✏️ Edit Harga", callback_data="product_edit")],
        [InlineKeyboardButton("🗑 Hapus Produk", callback_data="product_del")],
        [InlineKeyboardButton("📋 Lihat Produk", callback_data="product_view")],
        [InlineKeyboardButton("🔙 Menu Utama", callback_data="main_menu")],
    ])


async def product_menu_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Entry point — called by /produk or callback."""
    query = update.callback_query
    if query:
        await query.answer()
        await query.edit_message_text(
            "📦 *Manajemen Produk*\n\nPilih menu:",
            reply_markup=_product_menu_keyboard(),
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            "📦 *Manajemen Produk*\n\nPilih menu:",
            reply_markup=_product_menu_keyboard(),
            parse_mode="Markdown"
        )
    return PRODUCT_MENU


# ── Tambah Produk ──────────────────────────────────────────────────────────

async def product_add_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start add product workflow."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "➕ *Tambah Produk Baru*\n\nKetik nama produk:",
        parse_mode="Markdown"
    )
    return PRODUCT_ADD_NAME


async def product_add_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle product name input."""
    text = update.message.text.strip()
    if not text:
        await update.message.reply_text("Nama tidak boleh kosong. Coba lagi:")
        return PRODUCT_ADD_NAME
    
    context.user_data["new_product_name"] = text
    tenant_id = get_tenant_id(update.effective_user.id)
    kb = _categories_keyboard("add_cat", tenant_id)
    await update.message.reply_text(
        f"Nama: *{text}*\n\nPilih kategori dari tombol, atau *ketik nama kategori baru*:",
        reply_markup=kb, parse_mode="Markdown"
    )
    return PRODUCT_ADD_CAT


async def product_add_category_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle new category typed by user."""
    text = update.message.text.strip()
    if not text:
        await update.message.reply_text("Kategori tidak boleh kosong. Ketik nama kategori baru:")
        return PRODUCT_ADD_CAT

    context.user_data["new_product_category"] = text[:18]
    context.user_data["new_product_full_category"] = text
    
    await update.message.reply_text(
        f"Kategori baru: *{text}*\n\nKetik harga (angka) tanpa titik (contoh: 15000):",
        parse_mode="Markdown"
    )
    return PRODUCT_ADD_PRICE


async def product_add_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle category selection for add."""
    query = update.callback_query
    await query.answer()
    data = query.data
    tenant_id = get_tenant_id(query.from_user.id)

    if data == "add_cat_back":
        kb = _categories_keyboard("add_cat", tenant_id)
        await query.edit_message_text("Pilih kategori:", reply_markup=kb, parse_mode="Markdown")
        return PRODUCT_ADD_CAT

    if data.startswith("add_cat_page_"):
        page = int(data.split("_")[-1])
        kb = _categories_keyboard("add_cat", tenant_id, page)
        await query.edit_message_text("Pilih kategori:", reply_markup=kb, parse_mode="Markdown")
        return PRODUCT_ADD_CAT

    cat_short = data[9:]  # strip "add_cat_"
    context.user_data["new_product_category"] = cat_short
    
    db = SessionLocal()
    category = db.query(Product.category).filter(
        Product.category.like(f"{cat_short}%"),
        Product.tenant_id == tenant_id
    ).first()
    full_cat = category[0] if category else cat_short
    db.close()

    context.user_data["new_product_full_category"] = full_cat
    await query.edit_message_text(
        f"Kategori: *{full_cat}*\n\nKetik harga (angka):",
        parse_mode="Markdown"
    )
    return PRODUCT_ADD_PRICE


async def product_add_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle price input and create product."""
    text = update.message.text.strip()
    try:
        price = int(text)
        if price <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("Harga harus angka positif. Coba lagi:")
        return PRODUCT_ADD_PRICE
    
    db = SessionLocal()
    tenant_id = get_tenant_id(update.effective_user.id)
    product = Product(
        item_name=context.user_data.get("new_product_name"),
        category=context.user_data.get("new_product_full_category"),
        subcategory=context.user_data.get("new_product_category"),
        price=price,
        stock=0,
        tenant_id=tenant_id
    )
    db.add(product)
    db.commit()
    db.refresh(product)
    
    p_name = product.item_name
    p_cat = product.category
    p_price = product.price
    p_id = product.id
    db.close()

    await update.message.reply_text(
        f"✅ *Produk berhasil ditambahkan!*\n\n"
        f"📦 Nama: *{p_name}*\n"
        f"🏷️ Kategori: {p_cat}\n"
        f"💰 Harga: Rp{p_price:,}\n"
        f"🆔 ID: #{p_id}",
        reply_markup=_product_menu_keyboard(),
        parse_mode="Markdown"
    )
    return PRODUCT_MENU


# ── Edit Harga ─────────────────────────────────────────────────────────────

async def product_edit_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start edit price workflow."""
    query = update.callback_query
    await query.answer()
    tenant_id = get_tenant_id(query.from_user.id)
    kb = _categories_keyboard("edit_cat", tenant_id)
    await query.edit_message_text(
        "✏️ *Edit Harga Produk*\n\nPilih kategori:",
        reply_markup=kb, parse_mode="Markdown"
    )
    return PRODUCT_EDIT_CAT


async def product_edit_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle category selection for editing."""
    query = update.callback_query
    await query.answer()
    tenant_id = get_tenant_id(query.from_user.id)
    data = query.data

    if data == "edit_cat_back":
        kb = _categories_keyboard("edit_cat", tenant_id)
        await query.edit_message_text("Pilih kategori:", reply_markup=kb, parse_mode="Markdown")
        return PRODUCT_EDIT_CAT

    if data.startswith("edit_cat_page_"):
        page = int(data.split("_")[-1])
        kb = _categories_keyboard("edit_cat", tenant_id, page)
        await query.edit_message_text("Pilih kategori:", reply_markup=kb, parse_mode="Markdown")
        return PRODUCT_EDIT_CAT

    cat_short = data[10:]  # strip "edit_cat_"
    kb, full_cat = _products_keyboard("edit_prod", cat_short, tenant_id)
    context.user_data["edit_category"] = full_cat
    await query.edit_message_text(
        f"Pilih produk untuk edit harga:",
        reply_markup=kb, parse_mode="Markdown"
    )
    return PRODUCT_EDIT_PROD


async def product_edit_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle product selection for editing."""
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "edit_prod_back":
        tenant_id = get_tenant_id(query.from_user.id)
        kb = _categories_keyboard("edit_cat", tenant_id)
        await query.edit_message_text("Pilih kategori:", reply_markup=kb, parse_mode="Markdown")
        return PRODUCT_EDIT_CAT

    if "_pg_" in data:
        tenant_id = get_tenant_id(query.from_user.id)
        parts = data.replace("edit_prod_", "").split("_pg_")
        cat_short = parts[0]
        page = int(parts[1])
        kb, _ = _products_keyboard("edit_prod", cat_short, tenant_id, page)
        await query.edit_message_text("Pilih produk:", reply_markup=kb, parse_mode="Markdown")
        return PRODUCT_EDIT_PROD

    product_id = int(data.split("_p_")[1])
    context.user_data["edit_product_id"] = product_id

    db = SessionLocal()
    product = db.query(Product).filter(Product.id == product_id).first()
    db.close()

    await query.edit_message_text(
        f"✏️ *Edit Harga*\n\n"
        f"Produk: *{product.item_name}*\n"
        f"Harga saat ini: Rp{product.price:,}\n\n"
        f"Ketik harga baru:",
        parse_mode="Markdown"
    )
    return PRODUCT_EDIT_PRICE


async def product_edit_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle price update."""
    text = update.message.text.strip()
    try:
        price = int(text)
        if price <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("Harga harus angka positif. Coba lagi:")
        return PRODUCT_EDIT_PRICE

    db = SessionLocal()
    product = db.query(Product).filter(
        Product.id == context.user_data.get("edit_product_id")
    ).first()
    if product:
        product.price = price
        db.commit()
        msg = f"✅ *Harga berhasil diubah!*\n\n📦 {product.item_name}: Rp{product.price:,}"
    else:
        msg = "Produk tidak ditemukan."
    db.close()

    await update.message.reply_text(
        msg,
        reply_markup=_product_menu_keyboard(),
        parse_mode="Markdown"
    )
    return PRODUCT_MENU


# ── Hapus Produk ───────────────────────────────────────────────────────────

async def product_del_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start delete workflow."""
    query = update.callback_query
    await query.answer()
    tenant_id = get_tenant_id(query.from_user.id)
    kb = _categories_keyboard("del_cat", tenant_id)
    await query.edit_message_text(
        "🗑 *Hapus Produk*\n\nPilih kategori:",
        reply_markup=kb, parse_mode="Markdown"
    )
    return PRODUCT_DEL_CAT


async def product_del_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle category selection for deletion."""
    query = update.callback_query
    await query.answer()
    data = query.data
    tenant_id = get_tenant_id(query.from_user.id)

    if data == "del_cat_back":
        kb = _categories_keyboard("del_cat", tenant_id)
        await query.edit_message_text("Pilih kategori:", reply_markup=kb, parse_mode="Markdown")
        return PRODUCT_DEL_CAT

    if data.startswith("del_cat_page_"):
        page = int(data.split("_")[-1])
        kb = _categories_keyboard("del_cat", tenant_id, page)
        await query.edit_message_text("Pilih kategori:", reply_markup=kb, parse_mode="Markdown")
        return PRODUCT_DEL_CAT

    cat_short = data[9:]  # strip "del_cat_"
    kb, full_cat = _products_keyboard("del_prod", cat_short, tenant_id, mode="delete")
    await query.edit_message_text(
        f"Pilih produk untuk dihapus:",
        reply_markup=kb, parse_mode="Markdown"
    )
    return PRODUCT_DEL_PROD


async def product_del_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle product selection for deletion."""
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "del_prod_back":
        tenant_id = get_tenant_id(query.from_user.id)
        kb = _categories_keyboard("del_cat", tenant_id)
        await query.edit_message_text("Pilih kategori:", reply_markup=kb, parse_mode="Markdown")
        return PRODUCT_DEL_CAT

    if "_pg_" in data:
        tenant_id = get_tenant_id(query.from_user.id)
        parts = data.replace("del_prod_", "").split("_pg_")
        cat_short = parts[0]
        page = int(parts[1])
        kb, _ = _products_keyboard("del_prod", cat_short, tenant_id, page, mode="delete")
        await query.edit_message_text("Pilih produk:", reply_markup=kb, parse_mode="Markdown")
        return PRODUCT_DEL_PROD

    product_id = int(data.split("_p_")[1])
    
    db = SessionLocal()
    product = db.query(Product).filter(Product.id == product_id).first()
    if product:
        db.delete(product)
        db.commit()
        msg = f"✅ *Produk berhasil dihapus!*\n\n📦 {product.item_name} (#{product.id})"
    else:
        msg = "Produk tidak ditemukan."
    db.close()

    await query.edit_message_text(
        msg,
        reply_markup=_product_menu_keyboard(),
        parse_mode="Markdown"
    )
    return PRODUCT_MENU


# ── Lihat Produk ───────────────────────────────────────────────────────────

async def product_view_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start view workflow."""
    query = update.callback_query
    await query.answer()
    tenant_id = get_tenant_id(query.from_user.id)
    kb = _categories_keyboard("view_cat", tenant_id)
    await query.edit_message_text(
        "📋 *Lihat Produk*\n\nPilih kategori:",
        reply_markup=kb, parse_mode="Markdown"
    )
    return PRODUCT_VIEW_CAT


async def product_view_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle category selection for viewing."""
    query = update.callback_query
    await query.answer()
    tenant_id = get_tenant_id(query.from_user.id)
    data = query.data

    if data == "view_cat_back":
        kb = _categories_keyboard("view_cat", tenant_id)
        await query.edit_message_text("Pilih kategori:", reply_markup=kb, parse_mode="Markdown")
        return PRODUCT_VIEW_CAT

    if data.startswith("view_cat_page_"):
        page = int(data.split("_")[-1])
        kb = _categories_keyboard("view_cat", tenant_id, page)
        await query.edit_message_text("Pilih kategori:", reply_markup=kb, parse_mode="Markdown")
        return PRODUCT_VIEW_CAT

    cat_short = data[9:]  # strip "view_cat_"
    kb, full_cat = _products_keyboard("view_prod", cat_short, tenant_id)
    await query.edit_message_text(
        f"📦 *{full_cat}* (produk):\n\n",
        reply_markup=kb, parse_mode="Markdown"
    )
    return PRODUCT_VIEW_PROD


async def product_view_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle product selection/pagination in VIEW mode."""
    query = update.callback_query
    await query.answer()
    data = query.data
    tenant_id = get_tenant_id(query.from_user.id)

    if data == "view_prod_back":
        kb = _categories_keyboard("view_cat", tenant_id)
        await query.edit_message_text("Pilih kategori:", reply_markup=kb, parse_mode="Markdown")
        return PRODUCT_VIEW_CAT

    if "_pg_" in data:
        parts = data.replace("view_prod_", "").split("_pg_")
        cat_short = parts[0]
        page = int(parts[1])
        kb, full_cat = _products_keyboard("view_prod", cat_short, tenant_id, page)
        await query.edit_message_text(
            f"📦 *{full_cat}* (produk):\n\n",
            reply_markup=kb, parse_mode="Markdown"
        )
        return PRODUCT_VIEW_PROD

    # Product selected - show details
    product_id = int(data.split("_p_")[1])
    db = SessionLocal()
    product = db.query(Product).filter(Product.id == product_id).first()
    db.close()

    if product:
        await query.edit_message_text(
            f"📦 *Detail Produk*\n\n"
            f"📝 Nama: *{product.item_name}*\n"
            f"🏷️ Kategori: {product.category}\n"
            f"📂 Sub-kategori: {product.subcategory}\n"
            f"💰 Harga: *Rp{product.price:,}*\n"
            f"📦 Stok: {product.stock}\n"
            f"🆔 ID: #{product.id}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Kembali", callback_data="view_prod_back")]
            ]),
            parse_mode="Markdown"
        )
    else:
        await query.edit_message_text("Produk tidak ditemukan.")
    return PRODUCT_VIEW_PROD


# ── Shared handlers ────────────────────────────────────────────────────────

async def main_menu_return(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Return to main menu."""
    return ConversationHandler.END


async def cancel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel current operation and return to product menu."""
    query = update.callback_query
    if query:
        await query.answer()
        await query.edit_message_text(
            "📦 *Manajemen Produk*\n\nPilih menu:",
            reply_markup=_product_menu_keyboard(),
            parse_mode="Markdown"
        )
    return PRODUCT_MENU


def get_product_handler():
    """Build and return the product management ConversationHandler."""
    cancel_cb = CallbackQueryHandler(cancel_handler, pattern="^(cancel|prod_menu_back)$")

    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(product_menu_entry, pattern="^prod_menu$"),
            CommandHandler("produk", product_menu_entry),
        ],
        states={
            PRODUCT_MENU: [
                CallbackQueryHandler(product_add_start, pattern="^product_add$"),
                CallbackQueryHandler(product_edit_start, pattern="^product_edit$"),
                CallbackQueryHandler(product_del_start, pattern="^product_del$"),
                CallbackQueryHandler(product_view_start, pattern="^product_view$"),
                CallbackQueryHandler(main_menu_return, pattern="^main_menu$"),
            ],
            PRODUCT_ADD_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, product_add_name),
                cancel_cb,
            ],
            PRODUCT_ADD_CAT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, product_add_category_text),
                CallbackQueryHandler(product_add_category, pattern="^add_cat_back"),
                CallbackQueryHandler(product_add_category, pattern="^add_cat_page_"),
                CallbackQueryHandler(product_add_category, pattern="^add_cat_"),
                cancel_cb,
            ],
            PRODUCT_ADD_PRICE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, product_add_price),
                cancel_cb,
            ],
            PRODUCT_EDIT_CAT: [
                CallbackQueryHandler(product_edit_category, pattern="^edit_cat_back"),
                CallbackQueryHandler(product_edit_category, pattern="^edit_cat_page_"),
                CallbackQueryHandler(product_edit_category, pattern="^edit_cat_"),
                cancel_cb,
            ],
            PRODUCT_EDIT_PROD: [
                CallbackQueryHandler(product_edit_product, pattern="^edit_prod_back"),
                CallbackQueryHandler(product_edit_product, pattern="^edit_prod_.*_pg_"),
                CallbackQueryHandler(product_edit_product, pattern="^edit_prod_"),
                cancel_cb,
            ],
            PRODUCT_EDIT_PRICE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, product_edit_price),
                cancel_cb,
            ],
            PRODUCT_DEL_CAT: [
                CallbackQueryHandler(product_del_category, pattern="^del_cat_back"),
                CallbackQueryHandler(product_del_category, pattern="^del_cat_page_"),
                CallbackQueryHandler(product_del_category, pattern="^del_cat_"),
                cancel_cb,
            ],
            PRODUCT_DEL_PROD: [
                CallbackQueryHandler(product_del_product, pattern="^del_prod_back"),
                CallbackQueryHandler(product_del_product, pattern="^del_prod_.*_pg_"),
                CallbackQueryHandler(product_del_product, pattern="^del_prod_"),
                cancel_cb,
            ],
            PRODUCT_VIEW_CAT: [
                CallbackQueryHandler(product_view_category, pattern="^view_cat_back"),
                CallbackQueryHandler(product_view_category, pattern="^view_cat_page_"),
                CallbackQueryHandler(product_view_category, pattern="^view_cat_"),
                cancel_cb,
            ],
            PRODUCT_VIEW_PROD: [
                CallbackQueryHandler(product_view_product, pattern="^view_prod_back"),
                CallbackQueryHandler(product_view_product, pattern="^view_prod_.*_pg_"),
                CallbackQueryHandler(product_view_product, pattern="^view_prod_"),
                cancel_cb,
            ],
        },
        fallbacks=[
            CallbackQueryHandler(main_menu_return, pattern="^main_menu$"),
            CommandHandler("cancel", lambda u, c: ConversationHandler.END),
        ],
        per_message=False,
    )