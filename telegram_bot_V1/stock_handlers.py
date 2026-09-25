"""
stock_handlers.py — Inline-button stock management for the POS Telegram Bot.
=============================================================================
Features:
  📥 Barang Masuk    — record incoming stock
  📤 Barang Keluar   — record outgoing stock (non-sale)
  📋 Lihat Stok      — view current stock per category
  ⚠️ Stok Rendah     — products below min_stock threshold
  🤝 Konsinyasi      — toggle consignment status & set supplier
"""

import logging
import math
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes, ConversationHandler, CommandHandler,
    CallbackQueryHandler, MessageHandler, filters
)

from database import SessionLocal, Product, StockMovement
from auth import is_kasir, is_owner, get_tenant_id

logger = logging.getLogger(__name__)

# ── Conversation States ────────────────────────────────────────────────────
(
    STOCK_MENU,
    STOCK_IN_CAT,       # picking category for stock-in
    STOCK_IN_PRODUCT,   # picking product for stock-in
    STOCK_IN_QTY,       # typing quantity for stock-in
    STOCK_OUT_CAT,
    STOCK_OUT_PRODUCT,
    STOCK_OUT_QTY,
    STOCK_VIEW_CAT,     # viewing stock per category
    CONSIGN_CAT,        # picking category for consignment toggle
    CONSIGN_PRODUCT,    # picking product for consignment toggle
    CONSIGN_SUPPLIER,   # typing supplier name
) = range(11)

PER_PAGE = 8


# ══════════════════════════════════════════════════════════════════════════════
# UTILITY — build keyboards
# ══════════════════════════════════════════════════════════════════════════════

def _categories_keyboard(prefix: str, page: int = 1):
    """Build a paginated category keyboard with callback prefix."""
    db = SessionLocal()
    cats = db.query(Product.category).distinct().order_by(Product.category).all()
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
        nav.append(InlineKeyboardButton("⬅️", callback_data=f"{prefix}_page_{page - 1}"))
    if page < total_pages:
        nav.append(InlineKeyboardButton("➡️", callback_data=f"{prefix}_page_{page + 1}"))
    if nav:
        keyboard.append(nav)

    keyboard.append([InlineKeyboardButton("🔙 Menu Stok", callback_data="stock_menu")])
    return InlineKeyboardMarkup(keyboard)


def _products_keyboard(prefix: str, category_short: str, page: int = 1, show_stock: bool = True):
    """Build a paginated product keyboard for a category."""
    db = SessionLocal()
    category = db.query(Product.category).filter(
        Product.category.like(f"{category_short}%")
    ).first()
    full_cat = category[0] if category else category_short

    q = db.query(Product).filter(Product.category == full_cat).order_by(Product.item_name)
    total = q.count()
    total_pages = max(1, math.ceil(total / PER_PAGE))
    page = min(page, total_pages)
    products = q.offset((page - 1) * PER_PAGE).limit(PER_PAGE).all()
    db.close()

    keyboard = []
    for p in products:
        consign_mark = "🤝 " if p.is_consignment else ""
        if show_stock:
            label = f"{consign_mark}{p.item_name} [{p.stock}]"
        else:
            label = f"{consign_mark}{p.item_name}"
        keyboard.append([InlineKeyboardButton(label, callback_data=f"{prefix}_p_{p.id}")])

    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton("⬅️", callback_data=f"{prefix}_{category_short}_pg_{page - 1}"))
    if page < total_pages:
        nav.append(InlineKeyboardButton("➡️", callback_data=f"{prefix}_{category_short}_pg_{page + 1}"))
    if nav:
        keyboard.append(nav)

    keyboard.append([InlineKeyboardButton("🔙 Pilih Kategori", callback_data=f"{prefix}_back")])
    return InlineKeyboardMarkup(keyboard), full_cat


# ══════════════════════════════════════════════════════════════════════════════
# STOCK MENU — entry point
# ══════════════════════════════════════════════════════════════════════════════

def _stock_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📥 Barang Masuk", callback_data="stk_in"),
         InlineKeyboardButton("📤 Barang Keluar", callback_data="stk_out")],
        [InlineKeyboardButton("📋 Lihat Stok", callback_data="stk_view"),
         InlineKeyboardButton("⚠️ Stok Rendah", callback_data="stk_low")],
        [InlineKeyboardButton("🤝 Konsinyasi", callback_data="stk_consign")],
        [InlineKeyboardButton("🔙 Menu Utama", callback_data="main_menu")],
    ])


async def stock_menu_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Entry point — called by main menu inline button."""
    query = update.callback_query
    if query:
        await query.answer()
        await query.edit_message_text(
            "📦 *Manajemen Stok*\n\nPilih menu:",
            reply_markup=_stock_menu_keyboard(),
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            "📦 *Manajemen Stok*\n\nPilih menu:",
            reply_markup=_stock_menu_keyboard(),
            parse_mode="Markdown"
        )
    return STOCK_MENU


# ══════════════════════════════════════════════════════════════════════════════
# BARANG MASUK (Stock In)
# ══════════════════════════════════════════════════════════════════════════════

async def stock_in_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    kb = _categories_keyboard("sin")
    await query.edit_message_text(
        "📥 *Barang Masuk*\n\nPilih kategori produk:",
        reply_markup=kb, parse_mode="Markdown"
    )
    return STOCK_IN_CAT


async def stock_in_cat_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("sin_page_"):
        page = int(data.split("_")[-1])
        kb = _categories_keyboard("sin", page)
        await query.edit_message_text("📥 *Barang Masuk*\n\nPilih kategori:", reply_markup=kb, parse_mode="Markdown")
        return STOCK_IN_CAT

    cat_short = data[4:]  # strip "sin_"
    context.user_data["stk_cat"] = cat_short
    kb, full_cat = _products_keyboard("sin", cat_short)
    await query.edit_message_text(
        f"📥 *Barang Masuk — {full_cat}*\n\nPilih produk:",
        reply_markup=kb, parse_mode="Markdown"
    )
    return STOCK_IN_PRODUCT


async def stock_in_product_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "sin_back":
        kb = _categories_keyboard("sin")
        await query.edit_message_text("📥 *Barang Masuk*\n\nPilih kategori:", reply_markup=kb, parse_mode="Markdown")
        return STOCK_IN_CAT

    if "_pg_" in data:
        parts = data.replace("sin_", "").split("_pg_")
        cat_short = parts[0]
        page = int(parts[1])
        kb, full_cat = _products_keyboard("sin", cat_short, page)
        await query.edit_message_text(
            f"📥 *Barang Masuk — {full_cat}*\n\nPilih produk:",
            reply_markup=kb, parse_mode="Markdown"
        )
        return STOCK_IN_PRODUCT

    product_id = int(data.split("_p_")[1])
    context.user_data["stk_product_id"] = product_id

    db = SessionLocal()
    product = db.query(Product).filter(Product.id == product_id).first()
    name = product.item_name if product else "?"
    current_stock = product.stock if product else 0
    db.close()

    context.user_data["stk_product_name"] = name

    kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Batal", callback_data="stk_cancel")]])
    await query.edit_message_text(
        f"📥 *Barang Masuk*\n\n"
        f"Produk: *{name}*\n"
        f"Stok saat ini: *{current_stock}*\n\n"
        f"Ketik jumlah barang yang masuk (angka):",
        reply_markup=kb, parse_mode="Markdown"
    )
    return STOCK_IN_QTY


async def stock_in_qty(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    try:
        qty = int(text)
        if qty <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("⚠️ Masukkan angka positif. Coba lagi:")
        return STOCK_IN_QTY

    product_id = context.user_data.get("stk_product_id")
    product_name = context.user_data.get("stk_product_name", "?")
    user_id = update.effective_user.id
    tenant_id = get_tenant_id(user_id)

    db = SessionLocal()
    product = db.query(Product).filter(Product.id == product_id).first()
    if product:
        product.stock += qty
        movement = StockMovement(
            product_id=product_id,
            tenant_id=tenant_id,
            movement_type="in",
            quantity=qty,
            reference="Manual",
            notes=f"Barang masuk via bot",
            created_by=user_id,
        )
        db.add(movement)
        db.commit()
        new_stock = product.stock
    else:
        new_stock = 0
    db.close()

    await update.message.reply_text(
        f"✅ *Barang Masuk Berhasil!*\n\n"
        f"Produk: *{product_name}*\n"
        f"Jumlah masuk: *+{qty}*\n"
        f"Stok sekarang: *{new_stock}*",
        reply_markup=_stock_menu_keyboard(),
        parse_mode="Markdown"
    )
    return STOCK_MENU


# ══════════════════════════════════════════════════════════════════════════════
# BARANG KELUAR (Stock Out) — non-sale deduction
# ══════════════════════════════════════════════════════════════════════════════

async def stock_out_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    kb = _categories_keyboard("sout")
    await query.edit_message_text(
        "📤 *Barang Keluar*\n\nPilih kategori produk:",
        reply_markup=kb, parse_mode="Markdown"
    )
    return STOCK_OUT_CAT


async def stock_out_cat_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("sout_page_"):
        page = int(data.split("_")[-1])
        kb = _categories_keyboard("sout", page)
        await query.edit_message_text("📤 *Barang Keluar*\n\nPilih kategori:", reply_markup=kb, parse_mode="Markdown")
        return STOCK_OUT_CAT

    cat_short = data[5:]  # strip "sout_"
    context.user_data["stk_cat"] = cat_short
    kb, full_cat = _products_keyboard("sout", cat_short)
    await query.edit_message_text(
        f"📤 *Barang Keluar — {full_cat}*\n\nPilih produk:",
        reply_markup=kb, parse_mode="Markdown"
    )
    return STOCK_OUT_PRODUCT


async def stock_out_product_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "sout_back":
        kb = _categories_keyboard("sout")
        await query.edit_message_text("📤 *Barang Keluar*\n\nPilih kategori:", reply_markup=kb, parse_mode="Markdown")
        return STOCK_OUT_CAT

    if "_pg_" in data:
        parts = data.replace("sout_", "").split("_pg_")
        cat_short = parts[0]
        page = int(parts[1])
        kb, full_cat = _products_keyboard("sout", cat_short, page)
        await query.edit_message_text(
            f"📤 *Barang Keluar — {full_cat}*\n\nPilih produk:",
            reply_markup=kb, parse_mode="Markdown"
        )
        return STOCK_OUT_PRODUCT

    product_id = int(data.split("_p_")[1])
    context.user_data["stk_product_id"] = product_id

    db = SessionLocal()
    product = db.query(Product).filter(Product.id == product_id).first()
    name = product.item_name if product else "?"
    current_stock = product.stock if product else 0
    db.close()

    context.user_data["stk_product_name"] = name

    kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Batal", callback_data="stk_cancel")]])
    await query.edit_message_text(
        f"📤 *Barang Keluar*\n\n"
        f"Produk: *{name}*\n"
        f"Stok saat ini: *{current_stock}*\n\n"
        f"Ketik jumlah barang yang keluar (angka):",
        reply_markup=kb, parse_mode="Markdown"
    )
    return STOCK_OUT_QTY


async def stock_out_qty(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    try:
        qty = int(text)
        if qty <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("⚠️ Masukkan angka positif. Coba lagi:")
        return STOCK_OUT_QTY

    product_id = context.user_data.get("stk_product_id")
    product_name = context.user_data.get("stk_product_name", "?")
    user_id = update.effective_user.id
    tenant_id = get_tenant_id(user_id)

    db = SessionLocal()
    product = db.query(Product).filter(Product.id == product_id).first()
    if product:
        product.stock = max(0, product.stock - qty)
        movement = StockMovement(
            product_id=product_id,
            tenant_id=tenant_id,
            movement_type="out",
            quantity=-qty,
            reference="Manual",
            notes=f"Barang keluar via bot",
            created_by=user_id,
        )
        db.add(movement)
        db.commit()
        new_stock = product.stock
    else:
        new_stock = 0
    db.close()

    warning = ""
    if new_stock == 0:
        warning = "\n⚠️ *Stok habis!*"

    await update.message.reply_text(
        f"✅ *Barang Keluar Berhasil!*\n\n"
        f"Produk: *{product_name}*\n"
        f"Jumlah keluar: *-{qty}*\n"
        f"Stok sekarang: *{new_stock}*{warning}",
        reply_markup=_stock_menu_keyboard(),
        parse_mode="Markdown"
    )
    return STOCK_MENU


# ══════════════════════════════════════════════════════════════════════════════
# LIHAT STOK
# ══════════════════════════════════════════════════════════════════════════════

async def stock_view_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    kb = _categories_keyboard("sview")
    await query.edit_message_text(
        "📋 *Lihat Stok*\n\nPilih kategori:",
        reply_markup=kb, parse_mode="Markdown"
    )
    return STOCK_VIEW_CAT


async def stock_view_cat_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("sview_page_"):
        page = int(data.split("_")[-1])
        kb = _categories_keyboard("sview", page)
        await query.edit_message_text("📋 *Lihat Stok*\n\nPilih kategori:", reply_markup=kb, parse_mode="Markdown")
        return STOCK_VIEW_CAT

    if data == "stock_menu":
        await query.edit_message_text(
            "📦 *Manajemen Stok*\n\nPilih menu:",
            reply_markup=_stock_menu_keyboard(),
            parse_mode="Markdown"
        )
        return STOCK_MENU

    cat_short = data[6:]  # strip "sview_"

    db = SessionLocal()
    category = db.query(Product.category).filter(
        Product.category.like(f"{cat_short}%")
    ).first()
    full_cat = category[0] if category else cat_short
    products = db.query(Product).filter(
        Product.category == full_cat
    ).order_by(Product.item_name).all()
    db.close()

    text = f"📋 *Stok — {full_cat}*\n\n"
    for p in products:
        consign = "🤝" if p.is_consignment else ""
        low = "⚠️" if p.stock <= p.min_stock and p.min_stock > 0 else ""
        text += f"▪️ {consign}{p.item_name}: *{p.stock}* {low}\n"

    if not products:
        text += "_Tidak ada produk._"

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 Pilih Kategori", callback_data="stk_view")],
        [InlineKeyboardButton("🔙 Menu Stok", callback_data="stock_menu")],
    ])
    await query.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")
    return STOCK_VIEW_CAT


# ══════════════════════════════════════════════════════════════════════════════
# STOK RENDAH
# ══════════════════════════════════════════════════════════════════════════════

async def stock_low_alert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    db = SessionLocal()
    # Products with stock <= min_stock (and min_stock > 0) OR stock == 0
    low_products = db.query(Product).filter(
        (Product.stock <= Product.min_stock) | (Product.stock == 0)
    ).order_by(Product.category, Product.item_name).all()
    db.close()

    if not low_products:
        text = "✅ *Stok Aman!*\n\nSemua produk memiliki stok yang cukup."
    else:
        text = f"⚠️ *Stok Rendah / Habis* ({len(low_products)} produk)\n\n"
        for p in low_products:
            consign = "🤝" if p.is_consignment else ""
            if p.stock == 0:
                text += f"🔴 {consign}{p.item_name}: *HABIS*\n"
            else:
                text += f"🟡 {consign}{p.item_name}: *{p.stock}* (min: {p.min_stock})\n"

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 Menu Stok", callback_data="stock_menu")],
    ])
    await query.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")
    return STOCK_MENU


# ══════════════════════════════════════════════════════════════════════════════
# KONSINYASI (Consignment Toggle)
# ══════════════════════════════════════════════════════════════════════════════

async def consign_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not is_owner(update.effective_user.id):
        await query.edit_message_text(
            "⛔ Hanya owner yang bisa mengatur konsinyasi.",
            reply_markup=_stock_menu_keyboard()
        )
        return STOCK_MENU

    kb = _categories_keyboard("scon")
    await query.edit_message_text(
        "🤝 *Konsinyasi / Titipan*\n\nPilih kategori produk:",
        reply_markup=kb, parse_mode="Markdown"
    )
    return CONSIGN_CAT


async def consign_cat_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("scon_page_"):
        page = int(data.split("_")[-1])
        kb = _categories_keyboard("scon", page)
        await query.edit_message_text("🤝 *Konsinyasi*\n\nPilih kategori:", reply_markup=kb, parse_mode="Markdown")
        return CONSIGN_CAT

    cat_short = data[5:]  # strip "scon_"
    context.user_data["stk_cat"] = cat_short
    kb, full_cat = _products_keyboard("scon", cat_short, show_stock=False)
    await query.edit_message_text(
        f"🤝 *Konsinyasi — {full_cat}*\n\nPilih produk:",
        reply_markup=kb, parse_mode="Markdown"
    )
    return CONSIGN_PRODUCT


async def consign_product_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "scon_back":
        kb = _categories_keyboard("scon")
        await query.edit_message_text("🤝 *Konsinyasi*\n\nPilih kategori:", reply_markup=kb, parse_mode="Markdown")
        return CONSIGN_CAT

    if "_pg_" in data:
        parts = data.replace("scon_", "").split("_pg_")
        cat_short = parts[0]
        page = int(parts[1])
        kb, full_cat = _products_keyboard("scon", cat_short, page, show_stock=False)
        await query.edit_message_text(
            f"🤝 *Konsinyasi — {full_cat}*\n\nPilih produk:",
            reply_markup=kb, parse_mode="Markdown"
        )
        return CONSIGN_PRODUCT

    product_id = int(data.split("_p_")[1])
    context.user_data["stk_product_id"] = product_id

    db = SessionLocal()
    product = db.query(Product).filter(Product.id == product_id).first()
    db.close()

    if not product:
        await query.edit_message_text("Produk tidak ditemukan.", reply_markup=_stock_menu_keyboard())
        return STOCK_MENU

    context.user_data["stk_product_name"] = product.item_name
    is_con = product.is_consignment
    supplier = product.consignment_supplier or "-"

    status = "✅ Konsinyasi" if is_con else "❌ Bukan Konsinyasi"
    toggle_label = "❌ Hapus Status Konsinyasi" if is_con else "✅ Tandai Sebagai Konsinyasi"
    toggle_data = f"con_toggle_{product_id}_off" if is_con else f"con_toggle_{product_id}_on"

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(toggle_label, callback_data=toggle_data)],
        [InlineKeyboardButton("✏️ Ubah Supplier", callback_data=f"con_supplier_{product_id}")],
        [InlineKeyboardButton("🔙 Menu Stok", callback_data="stock_menu")],
    ])

    await query.edit_message_text(
        f"🤝 *Detail Konsinyasi*\n\n"
        f"Produk: *{product.item_name}*\n"
        f"Status: {status}\n"
        f"Supplier: {supplier}",
        reply_markup=kb, parse_mode="Markdown"
    )
    return CONSIGN_PRODUCT


async def consign_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    # Handle "Set Supplier" button
    if data.startswith("con_supplier_"):
        product_id = int(data.split("_")[2])
        context.user_data["stk_product_id"] = product_id
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Batal", callback_data="stk_cancel")]])
        await query.edit_message_text(
            "✏️ Ketik nama supplier untuk produk ini:",
            reply_markup=kb, parse_mode="Markdown"
        )
        return CONSIGN_SUPPLIER

    # Handle toggle on/off
    parts = data.split("_")
    product_id = int(parts[2])
    action = parts[3]

    db = SessionLocal()
    product = db.query(Product).filter(Product.id == product_id).first()
    if product:
        if action == "on":
            product.is_consignment = True
            msg = f"✅ *{product.item_name}* ditandai sebagai *konsinyasi*."
        else:
            product.is_consignment = False
            product.consignment_supplier = None
            msg = f"❌ Status konsinyasi *{product.item_name}* dihapus."
        db.commit()
    else:
        msg = "Produk tidak ditemukan."
    db.close()

    await query.edit_message_text(
        msg, reply_markup=_stock_menu_keyboard(), parse_mode="Markdown"
    )
    return STOCK_MENU


async def consign_supplier_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    supplier_name = update.message.text.strip()
    product_id = context.user_data.get("stk_product_id")

    db = SessionLocal()
    product = db.query(Product).filter(Product.id == product_id).first()
    if product:
        product.consignment_supplier = supplier_name
        product.is_consignment = True
        db.commit()
        msg = f"✅ Supplier *{supplier_name}* disimpan untuk *{product.item_name}*."
    else:
        msg = "Produk tidak ditemukan."
    db.close()

    await update.message.reply_text(
        msg, reply_markup=_stock_menu_keyboard(), parse_mode="Markdown"
    )
    return STOCK_MENU


# ══════════════════════════════════════════════════════════════════════════════
# CANCEL — shared fallback
# ══════════════════════════════════════════════════════════════════════════════

async def stock_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "📦 *Manajemen Stok*\n\nPilih menu:",
        reply_markup=_stock_menu_keyboard(),
        parse_mode="Markdown"
    )
    return STOCK_MENU


async def stock_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle 'stock_menu' callback from within the conversation."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "📦 *Manajemen Stok*\n\nPilih menu:",
        reply_markup=_stock_menu_keyboard(),
        parse_mode="Markdown"
    )
    return STOCK_MENU


async def main_menu_return(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Return to main menu — ends stock conversation."""
    query = update.callback_query
    await query.answer()
    return ConversationHandler.END


# ══════════════════════════════════════════════════════════════════════════════
# BUILD CONVERSATION HANDLER
# ══════════════════════════════════════════════════════════════════════════════

def get_stock_handler():
    """Build and return the stock management ConversationHandler."""
    stock_menu_cb = CallbackQueryHandler(stock_menu_callback, pattern="^stock_menu$")
    cancel_cb = CallbackQueryHandler(stock_cancel, pattern="^stk_cancel$")

    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(stock_menu_entry, pattern="^stk_menu$"),
            CommandHandler("stok", stock_menu_entry),
        ],
        states={
            STOCK_MENU: [
                CallbackQueryHandler(stock_in_start, pattern="^stk_in$"),
                CallbackQueryHandler(stock_out_start, pattern="^stk_out$"),
                CallbackQueryHandler(stock_view_start, pattern="^stk_view$"),
                CallbackQueryHandler(stock_low_alert, pattern="^stk_low$"),
                CallbackQueryHandler(consign_start, pattern="^stk_consign$"),
                CallbackQueryHandler(main_menu_return, pattern="^main_menu$"),
            ],
            STOCK_IN_CAT: [
                CallbackQueryHandler(stock_in_cat_select, pattern="^sin_"),
                stock_menu_cb, cancel_cb,
            ],
            STOCK_IN_PRODUCT: [
                CallbackQueryHandler(stock_in_product_select, pattern="^sin_"),
                stock_menu_cb, cancel_cb,
            ],
            STOCK_IN_QTY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, stock_in_qty),
                cancel_cb,
            ],
            STOCK_OUT_CAT: [
                CallbackQueryHandler(stock_out_cat_select, pattern="^sout_"),
                stock_menu_cb, cancel_cb,
            ],
            STOCK_OUT_PRODUCT: [
                CallbackQueryHandler(stock_out_product_select, pattern="^sout_"),
                stock_menu_cb, cancel_cb,
            ],
            STOCK_OUT_QTY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, stock_out_qty),
                cancel_cb,
            ],
            STOCK_VIEW_CAT: [
                CallbackQueryHandler(stock_view_cat_select, pattern="^sview_"),
                CallbackQueryHandler(stock_view_start, pattern="^stk_view$"),
                stock_menu_cb, cancel_cb,
            ],
            CONSIGN_CAT: [
                CallbackQueryHandler(consign_cat_select, pattern="^scon_"),
                stock_menu_cb, cancel_cb,
            ],
            CONSIGN_PRODUCT: [
                CallbackQueryHandler(consign_product_select, pattern="^scon_"),
                CallbackQueryHandler(consign_toggle, pattern="^con_"),
                stock_menu_cb, cancel_cb,
            ],
            CONSIGN_SUPPLIER: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, consign_supplier_input),
                cancel_cb,
            ],
        },
        fallbacks=[
            CallbackQueryHandler(main_menu_return, pattern="^main_menu$"),
            CommandHandler("cancel", lambda u, c: ConversationHandler.END),
            CommandHandler("stok", stock_menu_entry),
        ],
        allow_reentry=True,
        per_message=False,
    )
