"""
Admin Handlers — Telegram ConversationHandler for promotion CRUD.
All admin flows use inline keyboards with 'ap_' callback data prefix.
"""

import logging
import math
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes, CommandHandler, CallbackQueryHandler,
    MessageHandler, ConversationHandler, filters
)

from auth import is_kasir as _is_kasir
from database import SessionLocal, Product
from promotion_service import (
    create_promotion, list_promotions, delete_promotion,
    update_promotion, format_date_indo
)

logger = logging.getLogger(__name__)

# --- Conversation States ---
(PROMO_MENU,
 ADD_CAT, ADD_PROD, ADD_DTYPE, ADD_DVAL, ADD_SDATE, ADD_EDATE, ADD_TCAT, ADD_CONFIRM,
 EDIT_SEL, EDIT_FIELD, EDIT_VAL,
 DEL_SEL, DEL_CONFIRM) = range(14)


# =============================================================================
# HELPERS
# =============================================================================

def is_admin(update: Update) -> bool:
    """Check if the user has admin-level access (kasir, vendor, or developer)."""
    return _is_kasir(update.effective_user.id)


def get_categories():
    """Get list of product categories from database."""
    db = SessionLocal()
    cats = db.query(Product.category).distinct().order_by(Product.category).all()
    db.close()
    return [c[0] for c in cats]


# =============================================================================
# MAIN MENU
# =============================================================================

async def promo_menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Entry point: /promo command — shows admin promotion menu."""
    if not is_admin(update):
        if update.message:
            await update.message.reply_text("⛔ Akses ditolak. Hanya admin yang bisa mengelola promosi.")
        return ConversationHandler.END

    keyboard = [
        [InlineKeyboardButton("➕ Tambah Promosi", callback_data="ap_add")],
        [InlineKeyboardButton("✏️ Edit Promosi", callback_data="ap_edit")],
        [InlineKeyboardButton("📋 Daftar Promosi", callback_data="ap_list")],
        [InlineKeyboardButton("🗑 Hapus Promosi", callback_data="ap_del")],
    ]

    text = "🏷️ *Menu Promosi*\n\nPilih aksi di bawah:"

    if update.callback_query:
        await update.callback_query.edit_message_text(
            text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
        )

    return PROMO_MENU


async def handle_promo_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Route main menu button clicks to the correct flow."""
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "ap_add":
        return await show_add_categories(update, context)
    elif data == "ap_edit":
        return await show_edit_list(update, context)
    elif data == "ap_list":
        return await show_promo_list(update, context)
    elif data == "ap_del":
        return await show_delete_list(update, context)
    elif data == "ap_menu":
        return await promo_menu_command(update, context)

    return PROMO_MENU


# =============================================================================
# ADD FLOW — Step 1: Select Category
# =============================================================================

async def show_add_categories(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show product categories for browsing."""
    categories = get_categories()
    context.user_data["promo_categories"] = categories

    keyboard = []
    row = []
    for i, cat in enumerate(categories):
        row.append(InlineKeyboardButton(cat, callback_data=f"ap_acat_{i}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("❌ Batal", callback_data="ap_menu")])

    text = "➕ *Tambah Promosi*\n\n📦 Pilih kategori produk:"
    await update.callback_query.edit_message_text(
        text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
    )
    return ADD_CAT


async def handle_add_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle category selection — show products in that category."""
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "ap_menu":
        return await promo_menu_command(update, context)

    if data.startswith("ap_acat_"):
        cat_idx = int(data.split("_")[2])
        categories = context.user_data.get("promo_categories", get_categories())
        category = categories[cat_idx]
        context.user_data["add_cat_idx"] = cat_idx
        return await show_add_products(update, context, category, page=1)

    # Handle pagination callbacks that arrive in this state
    if data.startswith("ap_app_"):
        parts = data.split("_")
        cat_idx = int(parts[2])
        page = int(parts[3])
        categories = context.user_data.get("promo_categories", get_categories())
        return await show_add_products(update, context, categories[cat_idx], page=page)

    return ADD_CAT


# =============================================================================
# ADD FLOW — Step 2: Select Product
# =============================================================================

async def show_add_products(update: Update, context: ContextTypes.DEFAULT_TYPE, category, page=1):
    """Show products in a category for selection (paginated)."""
    db = SessionLocal()
    per_page = 5
    total = db.query(Product).filter(Product.category == category).count()
    total_pages = math.ceil(total / per_page)
    offset = (page - 1) * per_page
    products = db.query(Product).filter(
        Product.category == category
    ).offset(offset).limit(per_page).all()
    db.close()

    cat_idx = context.user_data.get("add_cat_idx", 0)

    keyboard = []
    for p in products:
        keyboard.append([InlineKeyboardButton(
            f"{p.item_name} — Rp{p.price:,}",
            callback_data=f"ap_aprd_{p.id}"
        )])

    # Pagination
    nav_row = []
    if page > 1:
        nav_row.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"ap_app_{cat_idx}_{page-1}"))
    if page < total_pages:
        nav_row.append(InlineKeyboardButton("Next ➡️", callback_data=f"ap_app_{cat_idx}_{page+1}"))
    if nav_row:
        keyboard.append(nav_row)

    keyboard.append([InlineKeyboardButton("🔙 Kategori", callback_data="ap_aback")])
    keyboard.append([InlineKeyboardButton("❌ Batal", callback_data="ap_menu")])

    text = f"➕ *Tambah Promosi*\n\n📦 *{category}* (hal {page}/{total_pages})\nPilih produk:"
    await update.callback_query.edit_message_text(
        text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
    )
    return ADD_PROD


async def handle_add_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle product selection — show discount type options."""
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "ap_menu":
        return await promo_menu_command(update, context)
    if data == "ap_aback":
        return await show_add_categories(update, context)

    # Pagination
    if data.startswith("ap_app_"):
        parts = data.split("_")
        cat_idx = int(parts[2])
        page = int(parts[3])
        categories = context.user_data.get("promo_categories", get_categories())
        return await show_add_products(update, context, categories[cat_idx], page=page)

    # Product selected
    if data.startswith("ap_aprd_"):
        product_id = int(data.split("_")[2])

        db = SessionLocal()
        product = db.query(Product).filter(Product.id == product_id).first()
        db.close()

        if not product:
            await query.edit_message_text("❌ Produk tidak ditemukan.")
            return ConversationHandler.END

        context.user_data["promo_add"] = {
            "product_id": product.id,
            "product_name": product.item_name,
            "product_price": product.price,
            "product_category": product.category,
        }

        keyboard = [
            [InlineKeyboardButton("📊 Persentase (%)", callback_data="ap_adt_pct")],
            [InlineKeyboardButton("💰 Potongan Harga (Rp)", callback_data="ap_adt_fix")],
            [InlineKeyboardButton("❌ Batal", callback_data="ap_menu")],
        ]

        text = (
            f"➕ *Tambah Promosi*\n\n"
            f"📦 Produk: *{product.item_name}*\n"
            f"💰 Harga: Rp{product.price:,}\n\n"
            f"Pilih tipe diskon:"
        )
        await query.edit_message_text(
            text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
        )
        return ADD_DTYPE

    return ADD_PROD


# =============================================================================
# ADD FLOW — Step 3: Discount Type
# =============================================================================

async def handle_add_discount_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle discount type selection — ask for value."""
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "ap_menu":
        return await promo_menu_command(update, context)

    add_data = context.user_data["promo_add"]

    if data == "ap_adt_pct":
        add_data["discount_type"] = "percentage"
        hint = "Contoh: 10 untuk diskon 10%"
    elif data == "ap_adt_fix":
        add_data["discount_type"] = "fixed_amount"
        hint = "Contoh: 5000 untuk potongan Rp5.000"
    else:
        return ADD_DTYPE

    text = (
        f"➕ *Tambah Promosi*\n\n"
        f"📦 Produk: *{add_data['product_name']}*\n\n"
        f"Masukkan nilai diskon (angka saja):\n"
        f"_{hint}_"
    )
    await query.edit_message_text(text, parse_mode="Markdown")
    return ADD_DVAL


# =============================================================================
# ADD FLOW — Step 4: Discount Value (text input)
# =============================================================================

async def handle_add_discount_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle discount value text input — ask for start date."""
    text_input = update.message.text.strip()

    try:
        value = int(text_input)
        if value <= 0:
            raise ValueError()
    except ValueError:
        await update.message.reply_text("❌ Masukkan angka positif yang valid.\nCoba lagi:")
        return ADD_DVAL

    add_data = context.user_data["promo_add"]

    # Validate bounds
    if add_data["discount_type"] == "percentage" and value > 100:
        await update.message.reply_text("❌ Persentase tidak boleh lebih dari 100%.\nCoba lagi:")
        return ADD_DVAL

    if add_data["discount_type"] == "fixed_amount" and value > add_data["product_price"]:
        await update.message.reply_text(
            f"❌ Potongan tidak boleh lebih dari harga produk (Rp{add_data['product_price']:,}).\nCoba lagi:"
        )
        return ADD_DVAL

    add_data["discount_value"] = value

    await update.message.reply_text(
        f"✅ Nilai diskon: *{value}*\n\n"
        f"📅 Masukkan tanggal mulai promo:\n"
        f"_Format: DD/MM/YYYY (contoh: 01/07/2026)_",
        parse_mode="Markdown"
    )
    return ADD_SDATE


# =============================================================================
# ADD FLOW — Step 5: Start Date (text input)
# =============================================================================

async def handle_add_start_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle start date input — ask for end date."""
    text_input = update.message.text.strip()

    try:
        start_date = datetime.strptime(text_input, "%d/%m/%Y").date()
    except ValueError:
        await update.message.reply_text(
            "❌ Format tanggal salah.\nGunakan DD/MM/YYYY (contoh: 01/07/2026):"
        )
        return ADD_SDATE

    context.user_data["promo_add"]["start_date"] = start_date

    await update.message.reply_text(
        f"✅ Tanggal mulai: *{format_date_indo(start_date)}*\n\n"
        f"📅 Masukkan tanggal selesai promo:\n"
        f"_Format: DD/MM/YYYY_",
        parse_mode="Markdown"
    )
    return ADD_EDATE


# =============================================================================
# ADD FLOW — Step 6: End Date (text input)
# =============================================================================

async def handle_add_end_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle end date input — show target category selection."""
    text_input = update.message.text.strip()

    try:
        end_date = datetime.strptime(text_input, "%d/%m/%Y").date()
    except ValueError:
        await update.message.reply_text(
            "❌ Format tanggal salah.\nGunakan DD/MM/YYYY (contoh: 31/07/2026):"
        )
        return ADD_EDATE

    add_data = context.user_data["promo_add"]

    if end_date <= add_data["start_date"]:
        await update.message.reply_text(
            "❌ Tanggal selesai harus setelah tanggal mulai.\nCoba lagi:"
        )
        return ADD_EDATE

    add_data["end_date"] = end_date

    # Show target category selection
    categories = get_categories()
    context.user_data["promo_categories"] = categories

    keyboard = []
    row = []
    for i, cat in enumerate(categories):
        row.append(InlineKeyboardButton(cat, callback_data=f"ap_atc_{i}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("⏭ Tidak Ada / Skip", callback_data="ap_atc_none")])

    await update.message.reply_text(
        f"✅ Tanggal selesai: *{format_date_indo(end_date)}*\n\n"
        f"🎯 Pilih target kategori untuk rekomendasi:\n"
        f"_(Pelanggan yang beli dari kategori ini akan lihat promo ini di struk)_",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return ADD_TCAT


# =============================================================================
# ADD FLOW — Step 7: Target Category
# =============================================================================

async def handle_add_target_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle target category selection — show confirmation."""
    query = update.callback_query
    await query.answer()
    data = query.data

    add_data = context.user_data["promo_add"]

    if data == "ap_atc_none":
        add_data["target_category"] = None
    elif data.startswith("ap_atc_"):
        cat_idx = int(data.split("_")[2])
        categories = context.user_data.get("promo_categories", get_categories())
        add_data["target_category"] = categories[cat_idx]
    else:
        return ADD_TCAT

    # Build confirmation text
    if add_data["discount_type"] == "percentage":
        disc_text = f"{add_data['discount_value']}%"
    else:
        disc_text = f"Rp{add_data['discount_value']:,}"

    text = (
        f"📋 *Konfirmasi Promosi Baru*\n\n"
        f"📦 Produk: *{add_data['product_name']}*\n"
        f"💰 Harga Normal: Rp{add_data['product_price']:,}\n"
        f"🏷️ Diskon: {disc_text}\n"
        f"📅 Mulai: {format_date_indo(add_data['start_date'])}\n"
        f"📅 Selesai: {format_date_indo(add_data['end_date'])}\n"
        f"🎯 Target: {add_data['target_category'] or 'Tidak ada'}\n\n"
        f"Simpan promosi ini?"
    )

    keyboard = [
        [InlineKeyboardButton("✅ Simpan", callback_data="ap_asave")],
        [InlineKeyboardButton("❌ Batal", callback_data="ap_menu")],
    ]

    await query.edit_message_text(
        text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
    )
    return ADD_CONFIRM


# =============================================================================
# ADD FLOW — Step 8: Confirm & Save
# =============================================================================

async def handle_add_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Save the new promotion to database."""
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "ap_menu":
        return await promo_menu_command(update, context)

    if data == "ap_asave":
        add_data = context.user_data["promo_add"]

        promo_id, message = create_promotion(
            product_id=add_data["product_id"],
            discount_type=add_data["discount_type"],
            discount_value=add_data["discount_value"],
            start_date=add_data["start_date"],
            end_date=add_data["end_date"],
            target_category=add_data["target_category"],
        )

        icon = "✅" if promo_id else "❌"
        extra = f"\nPromo ID: *#{promo_id}*" if promo_id else ""
        text = f"{icon} {message}{extra}"

        keyboard = [[InlineKeyboardButton("🔙 Menu Promosi", callback_data="ap_menu")]]
        await query.edit_message_text(
            text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
        )
        return PROMO_MENU

    return ADD_CONFIRM


# =============================================================================
# LIST FLOW
# =============================================================================

async def show_promo_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show all active promotions as a formatted list."""
    promos = list_promotions(active_only=True)

    if not promos:
        text = "📋 *Daftar Promosi*\n\n_Belum ada promosi aktif._"
    else:
        text = f"📋 *Daftar Promosi Aktif* ({len(promos)})\n\n"
        for p in promos:
            text += (
                f"*#{p['id']}* — {p['product_name']}\n"
                f"   🏷️ Diskon: {p['discount_text']}\n"
                f"   📅 {p['start_date_str']} — {p['end_date_str']}\n"
                f"   🎯 Target: {p['target_category']}\n"
                f"   {p['status']}\n\n"
            )

    keyboard = [[InlineKeyboardButton("🔙 Menu Promosi", callback_data="ap_menu")]]

    if update.callback_query:
        await update.callback_query.edit_message_text(
            text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
        )

    return PROMO_MENU


# =============================================================================
# DELETE FLOW
# =============================================================================

async def show_delete_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show promos for deletion selection."""
    promos = list_promotions(active_only=True)

    if not promos:
        text = "🗑 *Hapus Promosi*\n\n_Belum ada promosi aktif._"
        keyboard = [[InlineKeyboardButton("🔙 Menu Promosi", callback_data="ap_menu")]]
        await update.callback_query.edit_message_text(
            text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
        )
        return PROMO_MENU

    text = "🗑 *Hapus Promosi*\n\nPilih promosi yang akan dihapus:"

    keyboard = []
    for p in promos:
        label = f"#{p['id']} {p['product_name'][:20]} ({p['discount_text']})"
        keyboard.append([InlineKeyboardButton(label, callback_data=f"ap_dsel_{p['id']}")])
    keyboard.append([InlineKeyboardButton("🔙 Menu Promosi", callback_data="ap_menu")])

    await update.callback_query.edit_message_text(
        text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
    )
    return DEL_SEL


async def handle_delete_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle promo selection for deletion — show confirmation."""
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "ap_menu":
        return await promo_menu_command(update, context)

    if data.startswith("ap_dsel_"):
        promo_id = int(data.split("_")[2])

        promos = list_promotions(active_only=True)
        promo = next((p for p in promos if p["id"] == promo_id), None)

        if not promo:
            await query.edit_message_text("❌ Promosi tidak ditemukan.")
            return PROMO_MENU

        text = (
            f"🗑 *Konfirmasi Hapus*\n\n"
            f"*#{promo['id']}* — {promo['product_name']}\n"
            f"🏷️ Diskon: {promo['discount_text']}\n"
            f"📅 {promo['start_date_str']} — {promo['end_date_str']}\n\n"
            f"Yakin ingin menghapus promosi ini?"
        )

        keyboard = [
            [InlineKeyboardButton("✅ Ya, Hapus", callback_data=f"ap_dok_{promo_id}")],
            [InlineKeyboardButton("❌ Batal", callback_data="ap_menu")],
        ]

        await query.edit_message_text(
            text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
        )
        return DEL_CONFIRM

    return DEL_SEL


async def handle_delete_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Execute the deletion."""
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "ap_menu":
        return await promo_menu_command(update, context)

    if data.startswith("ap_dok_"):
        promo_id = int(data.split("_")[2])
        success, message = delete_promotion(promo_id)

        text = f"{'✅' if success else '❌'} {message}"
        keyboard = [[InlineKeyboardButton("🔙 Menu Promosi", callback_data="ap_menu")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
        return PROMO_MENU

    return DEL_CONFIRM


# =============================================================================
# EDIT FLOW
# =============================================================================

async def show_edit_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show promos for editing selection."""
    promos = list_promotions(active_only=True)

    if not promos:
        text = "✏️ *Edit Promosi*\n\n_Belum ada promosi aktif._"
        keyboard = [[InlineKeyboardButton("🔙 Menu Promosi", callback_data="ap_menu")]]
        await update.callback_query.edit_message_text(
            text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
        )
        return PROMO_MENU

    text = "✏️ *Edit Promosi*\n\nPilih promosi yang akan diedit:"

    keyboard = []
    for p in promos:
        label = f"#{p['id']} {p['product_name'][:20]} ({p['discount_text']})"
        keyboard.append([InlineKeyboardButton(label, callback_data=f"ap_esel_{p['id']}")])
    keyboard.append([InlineKeyboardButton("🔙 Menu Promosi", callback_data="ap_menu")])

    await update.callback_query.edit_message_text(
        text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
    )
    return EDIT_SEL


async def handle_edit_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle promo selection — show editable fields."""
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "ap_menu":
        return await promo_menu_command(update, context)

    if data.startswith("ap_esel_"):
        promo_id = int(data.split("_")[2])
        context.user_data["edit_promo_id"] = promo_id
        return await show_edit_fields(update, context, promo_id)

    return EDIT_SEL


async def show_edit_fields(update: Update, context: ContextTypes.DEFAULT_TYPE, promo_id):
    """Show the promo details with buttons for each editable field."""
    promos = list_promotions(active_only=False)
    promo = next((p for p in promos if p["id"] == promo_id), None)

    if not promo:
        keyboard = [[InlineKeyboardButton("🔙 Menu Promosi", callback_data="ap_menu")]]
        await update.callback_query.edit_message_text(
            "❌ Promosi tidak ditemukan.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return PROMO_MENU

    dtype_label = "Persentase" if promo["discount_type"] == "percentage" else "Potongan Harga"

    text = (
        f"✏️ *Edit Promosi #{promo_id}*\n\n"
        f"📦 Produk: {promo['product_name']}\n"
        f"🏷️ Tipe: {dtype_label}\n"
        f"🏷️ Nilai: {promo['discount_text']}\n"
        f"📅 Mulai: {promo['start_date_str']}\n"
        f"📅 Selesai: {promo['end_date_str']}\n"
        f"🎯 Target: {promo['target_category']}\n\n"
        f"Pilih field yang ingin diedit:"
    )

    keyboard = [
        [InlineKeyboardButton("🏷️ Tipe Diskon", callback_data="ap_ef_dt")],
        [InlineKeyboardButton("💰 Nilai Diskon", callback_data="ap_ef_dv")],
        [InlineKeyboardButton("📅 Tanggal Mulai", callback_data="ap_ef_sd")],
        [InlineKeyboardButton("📅 Tanggal Selesai", callback_data="ap_ef_ed")],
        [InlineKeyboardButton("🎯 Target Kategori", callback_data="ap_ef_tc")],
        [InlineKeyboardButton("🔙 Menu Promosi", callback_data="ap_menu")],
    ]

    await update.callback_query.edit_message_text(
        text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
    )
    return EDIT_FIELD


async def handle_edit_field(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle field selection — prompt for new value."""
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "ap_menu":
        return await promo_menu_command(update, context)

    promo_id = context.user_data.get("edit_promo_id")

    if data == "ap_ef_dt":
        context.user_data["editing_field"] = "discount_type"
        keyboard = [
            [InlineKeyboardButton("📊 Persentase (%)", callback_data="ap_evt_pct")],
            [InlineKeyboardButton("💰 Potongan Harga (Rp)", callback_data="ap_evt_fix")],
            [InlineKeyboardButton("🔙 Kembali", callback_data=f"ap_esel_{promo_id}")],
        ]
        await query.edit_message_text(
            "Pilih tipe diskon baru:", reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return EDIT_VAL

    elif data == "ap_ef_dv":
        context.user_data["editing_field"] = "discount_value"
        await query.edit_message_text("Masukkan nilai diskon baru (angka saja):")
        return EDIT_VAL

    elif data == "ap_ef_sd":
        context.user_data["editing_field"] = "start_date"
        await query.edit_message_text("Masukkan tanggal mulai baru (DD/MM/YYYY):")
        return EDIT_VAL

    elif data == "ap_ef_ed":
        context.user_data["editing_field"] = "end_date"
        await query.edit_message_text("Masukkan tanggal selesai baru (DD/MM/YYYY):")
        return EDIT_VAL

    elif data == "ap_ef_tc":
        context.user_data["editing_field"] = "target_category"
        categories = get_categories()
        context.user_data["promo_categories"] = categories

        keyboard = []
        row = []
        for i, cat in enumerate(categories):
            row.append(InlineKeyboardButton(cat, callback_data=f"ap_evtc_{i}"))
            if len(row) == 2:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)
        keyboard.append([InlineKeyboardButton("⏭ Tidak Ada", callback_data="ap_evtc_none")])
        keyboard.append([InlineKeyboardButton("🔙 Kembali", callback_data=f"ap_esel_{promo_id}")])

        await query.edit_message_text(
            "Pilih target kategori baru:", reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return EDIT_VAL

    return EDIT_FIELD


async def handle_edit_value_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text input for edit value (discount_value, dates)."""
    field = context.user_data.get("editing_field")
    promo_id = context.user_data.get("edit_promo_id")
    text_input = update.message.text.strip()

    success = False
    msg = ""

    if field == "discount_value":
        try:
            value = int(text_input)
            if value <= 0:
                raise ValueError()
        except ValueError:
            await update.message.reply_text("❌ Masukkan angka positif. Coba lagi:")
            return EDIT_VAL
        success, msg = update_promotion(promo_id, discount_value=value)

    elif field in ("start_date", "end_date"):
        try:
            date_val = datetime.strptime(text_input, "%d/%m/%Y").date()
        except ValueError:
            await update.message.reply_text("❌ Format salah. Gunakan DD/MM/YYYY:")
            return EDIT_VAL
        success, msg = update_promotion(promo_id, **{field: date_val})

    else:
        await update.message.reply_text("❌ Field tidak dikenali.")
        return PROMO_MENU

    # Show result and offer to continue editing
    icon = "✅" if success else "❌"
    keyboard = [
        [InlineKeyboardButton("🔙 Lanjut Edit", callback_data=f"ap_esel_{promo_id}")],
        [InlineKeyboardButton("🔙 Menu Promosi", callback_data="ap_menu")],
    ]
    await update.message.reply_text(
        f"{icon} {msg}", reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return EDIT_SEL


async def handle_edit_value_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle callback input for edit value (discount_type, target_category)."""
    query = update.callback_query
    await query.answer()
    data = query.data

    promo_id = context.user_data.get("edit_promo_id")
    field = context.user_data.get("editing_field")

    # Handle back navigation
    if data.startswith("ap_esel_"):
        new_id = int(data.split("_")[2])
        context.user_data["edit_promo_id"] = new_id
        return await show_edit_fields(update, context, new_id)

    if data == "ap_menu":
        return await promo_menu_command(update, context)

    success = False
    msg = ""

    if field == "discount_type":
        if data == "ap_evt_pct":
            success, msg = update_promotion(promo_id, discount_type="percentage")
        elif data == "ap_evt_fix":
            success, msg = update_promotion(promo_id, discount_type="fixed_amount")
        else:
            return EDIT_VAL

    elif field == "target_category":
        if data == "ap_evtc_none":
            success, msg = update_promotion(promo_id, target_category=None)
        elif data.startswith("ap_evtc_"):
            cat_idx = int(data.split("_")[2])
            categories = context.user_data.get("promo_categories", get_categories())
            success, msg = update_promotion(promo_id, target_category=categories[cat_idx])
        else:
            return EDIT_VAL

    if success:
        return await show_edit_fields(update, context, promo_id)
    else:
        keyboard = [[InlineKeyboardButton("🔙 Menu Promosi", callback_data="ap_menu")]]
        await query.edit_message_text(f"❌ {msg}", reply_markup=InlineKeyboardMarkup(keyboard))
        return PROMO_MENU


# =============================================================================
# CANCEL
# =============================================================================

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel the current operation and exit the conversation."""
    await update.message.reply_text("❌ Operasi promosi dibatalkan.")
    return ConversationHandler.END


# =============================================================================
# CONVERSATION HANDLER FACTORY
# =============================================================================

def get_admin_conv_handler():
    """Create and return the admin promotion ConversationHandler."""
    return ConversationHandler(
        entry_points=[
            CommandHandler("promo", promo_menu_command),
        ],
        states={
            PROMO_MENU: [
                CallbackQueryHandler(handle_promo_menu, pattern="^ap_"),
            ],
            ADD_CAT: [
                CallbackQueryHandler(handle_add_category, pattern="^ap_"),
            ],
            ADD_PROD: [
                CallbackQueryHandler(handle_add_product, pattern="^ap_"),
            ],
            ADD_DTYPE: [
                CallbackQueryHandler(handle_add_discount_type, pattern="^ap_"),
            ],
            ADD_DVAL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_add_discount_value),
            ],
            ADD_SDATE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_add_start_date),
            ],
            ADD_EDATE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_add_end_date),
            ],
            ADD_TCAT: [
                CallbackQueryHandler(handle_add_target_category, pattern="^ap_"),
            ],
            ADD_CONFIRM: [
                CallbackQueryHandler(handle_add_confirm, pattern="^ap_"),
            ],
            EDIT_SEL: [
                CallbackQueryHandler(handle_edit_select, pattern="^ap_"),
            ],
            EDIT_FIELD: [
                CallbackQueryHandler(handle_edit_field, pattern="^ap_"),
            ],
            EDIT_VAL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_edit_value_text),
                CallbackQueryHandler(handle_edit_value_cb, pattern="^ap_"),
            ],
            DEL_SEL: [
                CallbackQueryHandler(handle_delete_select, pattern="^ap_"),
            ],
            DEL_CONFIRM: [
                CallbackQueryHandler(handle_delete_confirm, pattern="^ap_"),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_command),
            CommandHandler("promo", promo_menu_command),
        ],
        per_user=True,
        per_chat=True,
    )
