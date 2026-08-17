from telegram import Update, BotCommand
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters, CallbackQueryHandler
from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import func
from database import SessionLocal, CartItem, Product, Transaction, TransactionItem
from receipt_generator import generate_receipt_image
from config import BOT_TOKEN, WHATSAPP_NUMBER, DEVELOPER_TELEGRAM_ID
from promotion_service import get_active_promos_for_products, calculate_cart_with_discounts, get_recommendations
from admin_handlers import get_admin_conv_handler
from admin_schedule_handlers import get_admin_schedule_handler
from admin_report_handlers import (
    get_report_conv_handler, get_void_conv_handler,
    riwayat_command, handle_trx_detail_callback
)
from schedule_service import get_today_schedule_status, get_upcoming_schedules_receipt
from voice_ai_handler import handle_voice, handle_voice_callback, handle_voice_text_correction
from dev_handlers import get_dev_handler
from vendor_handlers import get_vendor_handler
from auth import bootstrap_developer, sync_user_info
import math
import datetime
import os
import random
import time
import logging

logger = logging.getLogger(__name__)


# --- Keyboard Layouts (Global Constants) ---

START_KEYBOARD = [
    [KeyboardButton("🚀 Mulai")]
]

# Denomination list for cash payment
CASH_DENOMINATIONS = [500, 1000, 2000, 5000, 10000, 20000, 50000, 100000]

# Labels for denominations
DENOM_LABELS = {
    500: "500",
    1000: "1rb",
    2000: "2rb",
    5000: "5rb",
    10000: "10rb",
    20000: "20rb",
    50000: "50rb",
    100000: "100rb",
}


# =============================================================================
# --- Product Cache (avoid re-querying DB on every button click) ---
# =============================================================================

_product_cache = {}       # {product_id: {"id", "item_name", "price", "category", ...}}
_category_cache = []      # list of category names
_cache_timestamp = 0
CACHE_TTL = 60            # seconds — refresh every 60s


def _refresh_cache_if_needed():
    """Refresh product/category cache if stale."""
    global _product_cache, _category_cache, _cache_timestamp
    now = time.time()
    if now - _cache_timestamp < CACHE_TTL and _product_cache:
        return
    db = SessionLocal()
    products = db.query(Product).all()
    _product_cache = {
        p.id: {"id": p.id, "item_name": p.item_name, "price": p.price, "category": p.category}
        for p in products
    }
    _category_cache = list(db.query(Product.category).distinct().all())
    db.close()
    _cache_timestamp = now


def invalidate_product_cache():
    """Call this after admin adds/edits/removes products to force refresh."""
    global _cache_timestamp
    _cache_timestamp = 0


def get_cached_products_by_category(category, offset=0, limit=5):
    """Get products from cache filtered by category with pagination."""
    _refresh_cache_if_needed()
    all_products = [p for p in _product_cache.values() if p["category"] == category]
    return all_products[offset:offset + limit], len(all_products)


def get_cached_categories():
    """Get distinct categories from cache."""
    _refresh_cache_if_needed()
    return _category_cache


def get_full_category_name(prefix):
    """Get full category name from prefix using cache."""
    _refresh_cache_if_needed()
    for cat in _category_cache:
        if cat[0].startswith(prefix):
            return cat[0]
    return prefix


# =============================================================================
# --- In-Memory Cart (avoid DB round-trip on every +/- click) ---
# =============================================================================

def get_memory_cart(context):
    """Get cart from user memory. Returns dict {product_id: qty}."""
    return context.user_data.get("mem_cart", {})


def set_memory_cart(context, cart):
    """Save cart to user memory."""
    context.user_data["mem_cart"] = cart


def add_to_memory_cart(context, product_id):
    """Add one item to the in-memory cart."""
    cart = get_memory_cart(context)
    cart[product_id] = cart.get(product_id, 0) + 1
    set_memory_cart(context, cart)


def remove_from_memory_cart(context, product_id):
    """Remove one item from the in-memory cart."""
    cart = get_memory_cart(context)
    if product_id in cart:
        cart[product_id] -= 1
        if cart[product_id] <= 0:
            del cart[product_id]
    set_memory_cart(context, cart)


def memory_cart_to_summary(context):
    """Convert in-memory cart to the same format as get_cart_summary().
    Returns list of tuples: (product_id, item_name, price, qty)
    """
    _refresh_cache_if_needed()
    cart = get_memory_cart(context)
    items = []
    for product_id, qty in cart.items():
        product = _product_cache.get(product_id)
        if product and qty > 0:
            items.append((product["id"], product["item_name"], product["price"], qty))
    return items


def sync_memory_cart_to_db(user_id, context):
    """Write in-memory cart to database (called at checkout)."""
    cart = get_memory_cart(context)
    db = SessionLocal()
    # Clear old cart items
    db.query(CartItem).filter(CartItem.user_id == user_id).delete()
    # Insert new
    for product_id, qty in cart.items():
        if qty > 0:
            for _ in range(qty):
                db.add(CartItem(user_id=user_id, product_id=product_id))
    db.commit()
    db.close()


def load_db_cart_to_memory(user_id, context):
    """Load cart from DB into memory (called on first interaction)."""
    db = SessionLocal()
    items = db.query(
        CartItem.product_id,
        func.count(CartItem.id).label("qty")
    ).filter(
        CartItem.user_id == user_id
    ).group_by(CartItem.product_id).all()
    db.close()

    cart = {}
    for product_id, qty in items:
        cart[product_id] = qty
    set_memory_cart(context, cart)
    # Mark as loaded so we don't reload unnecessarily
    context.user_data["cart_loaded"] = True


def ensure_cart_loaded(user_id, context):
    """Make sure the in-memory cart is loaded from DB (first time only)."""
    if not context.user_data.get("cart_loaded"):
        load_db_cart_to_memory(user_id, context)


# =============================================================================
# --- Helper Functions ---
# =============================================================================

def get_cart_summary(user_id):
    """Get cart items joined with products for a user (DB version for checkout)."""
    db = SessionLocal()
    items = db.query(
        Product.id,
        Product.item_name,
        Product.price,
        func.count(CartItem.id).label("qty")
    ).join(
        Product, CartItem.product_id == Product.id
    ).filter(
        CartItem.user_id == user_id
    ).group_by(Product.id).all()
    db.close()
    return items


def build_cart_text_from_memory(context, prepend_text=""):
    """Build cart summary text using in-memory cart (fast, no DB hit)."""
    cart_items = memory_cart_to_summary(context)

    text = prepend_text + "\n"

    if cart_items:
        text += "━━━━━━━━━━━━━━━━━━━━\n"
        text += "🛒 *Keranjang kamu:*\n\n"
        calc = calculate_cart_with_discounts(cart_items)
        for item in calc["items"]:
            text += f"▪️ {item['item_name']} x{item['qty']} — Rp{item['subtotal']:,}\n"
            if item['discount_amount'] > 0:
                text += f"   🏷️ Diskon — -Rp{item['discount_amount']:,}\n"
        text += f"\n💰 *Subtotal: Rp{calc['subtotal']:,}*\n"
        if calc["total_discount"] > 0:
            text += f"🏷️ *Total Diskon: -Rp{calc['total_discount']:,}*\n"
            text += f"💵 *Grand Total: Rp{calc['grand_total']:,}*\n"
        text += "━━━━━━━━━━━━━━━━━━━━"
    else:
        text += "_Keranjang masih kosong_"

    return text


def build_cart_text(user_id, prepend_text=""):
    """Build the cart summary text (legacy DB version)."""
    cart_items = get_cart_summary(user_id)

    text = prepend_text + "\n"

    if cart_items:
        text += "━━━━━━━━━━━━━━━━━━━━\n"
        text += "🛒 *Keranjang kamu:*\n\n"
        calc = calculate_cart_with_discounts(cart_items)
        for item in calc["items"]:
            text += f"▪️ {item['item_name']} x{item['qty']} — Rp{item['subtotal']:,}\n"
            if item['discount_amount'] > 0:
                text += f"   🏷️ Diskon — -Rp{item['discount_amount']:,}\n"
        text += f"\n💰 *Subtotal: Rp{calc['subtotal']:,}*\n"
        if calc["total_discount"] > 0:
            text += f"🏷️ *Total Diskon: -Rp{calc['total_discount']:,}*\n"
            text += f"💵 *Grand Total: Rp{calc['grand_total']:,}*\n"
        text += "━━━━━━━━━━━━━━━━━━━━"
    else:
        text += "_Keranjang masih kosong_"

    return text


def get_cash_total(cash_data):
    """Calculate total cash from denomination counts."""
    total = 0
    for denom in CASH_DENOMINATIONS:
        total += denom * cash_data.get(str(denom), 0)
    return total


def build_change_breakdown(change_amount):
    """Break down the change amount into bill denominations (greedy, largest first)."""
    if change_amount <= 0:
        return []
    breakdown = []
    remaining = change_amount
    for denom in reversed(CASH_DENOMINATIONS):
        if remaining >= denom:
            count = remaining // denom
            breakdown.append((denom, count))
            remaining -= denom * count
    # Handle Rp1000 coins if any remainder
    if remaining >= 1000:
        breakdown.append((1000, remaining // 1000))
        remaining -= 1000 * (remaining // 1000)
    if remaining >= 500:
        breakdown.append((500, remaining // 500))
        remaining -= 500 * (remaining // 500)
    if remaining >= 100:
        breakdown.append((100, remaining // 100))
        remaining -= 100 * (remaining // 100)
    return breakdown


def build_cash_keyboard(cash_data):
    """Build the inline keyboard for cash denomination selector."""
    keyboard = []
    for denom in CASH_DENOMINATIONS:
        count = cash_data.get(str(denom), 0)
        label = DENOM_LABELS[denom]
        keyboard.append([
            InlineKeyboardButton("➖", callback_data=f"csub_{denom}"),
            InlineKeyboardButton(f" {label} x {count} lbr", callback_data="noop"),
            InlineKeyboardButton("➕", callback_data=f"cadd_{denom}"),
        ])
    keyboard.append([
        InlineKeyboardButton("🔄 Reset", callback_data="cash_reset"),
    ])
    keyboard.append([
        InlineKeyboardButton("✅ Konfirmasi Bayar", callback_data="cash_confirm"),
    ])
    keyboard.append([
        InlineKeyboardButton("🔙 Kembali", callback_data="cash_cancel"),
    ])
    return InlineKeyboardMarkup(keyboard)


def build_cash_text(grand_total, cash_data):
    """Build the text display for cash payment with denominations and change."""
    cash_total = get_cash_total(cash_data)
    change = cash_total - grand_total

    text = "💵 *PEMBAYARAN TUNAI*\n"
    text += "━━━━━━━━━━━━━━━━━━━━\n"
    text += f"🏷️ Total Belanja: *Rp{grand_total:,}*\n"
    text += f"💰 Uang Diterima: *Rp{cash_total:,}*\n"
    text += "━━━━━━━━━━━━━━━━━━━━\n\n"

    if cash_total == 0:
        text += "⬇️ _Pilih nominal uang yang diberikan pembeli:_\n"
    elif change < 0:
        text += f"⚠️ *Kurang: Rp{abs(change):,}*\n"
        text += "_Tambah uang lagi hingga cukup._\n"
    elif change == 0:
        text += "✅ *Uang Pas!* Tidak ada kembalian.\n"
    else:
        text += f"✅ *Kembalian: Rp{change:,}*\n\n"
        breakdown = build_change_breakdown(change)
        if breakdown:
            text += "📋 *Rincian Kembalian:*\n"
            for denom, count in breakdown:
                if denom >= 1000:
                    denom_label = f"Rp{denom:,}"
                else:
                    denom_label = f"Rp{denom}"
                text += f"   💵 {denom_label} × {count} lembar\n"

    text += "\n━━━━━━━━━━━━━━━━━━━━\n"
    text += "_Tekan ➕/➖ untuk atur jumlah lembar uang_"
    return text


def build_categories_keyboard():
    """Build the inline keyboard for categories (uses cache)."""
    categories = get_cached_categories()

    keyboard = []
    # Display 2 categories per row
    row = []
    for cat in categories:
        cat_name = cat[0]
        # Using a short callback data to avoid Telegram's 64 byte limit
        cb_data = f"cat_{cat_name[:20]}"
        row.append(InlineKeyboardButton(cat_name, callback_data=cb_data))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    keyboard.append([InlineKeyboardButton(
        "✅ Selesai Memilih", callback_data="done_ordering")])
    return InlineKeyboardMarkup(keyboard)


def build_products_keyboard(category_prefix, page=1):
    """Build the inline keyboard for products in a category with pagination (uses cache)."""
    category = get_full_category_name(category_prefix)

    per_page = 5
    offset = (page - 1) * per_page
    products, total_products = get_cached_products_by_category(category, offset, per_page)
    total_pages = math.ceil(total_products / per_page)

    product_ids = [p["id"] for p in products]
    promos = get_active_promos_for_products(product_ids)

    keyboard = []

    # Product Rows
    for p in products:
        promo = promos.get(p["id"])
        if promo:
            if promo["discount_type"] == "percentage":
                label = f"🏷️ {p['item_name']} - Rp{p['price']:,} (-{promo['discount_value']}%)"
            else:
                label = f"🏷️ {p['item_name']} - Rp{p['price']:,} (-Rp{promo['discount_value']:,})"
        else:
            label = f"{p['item_name']} - Rp{p['price']:,}"
            
        keyboard.append([InlineKeyboardButton(label, callback_data=f"noop")])
        keyboard.append([
            InlineKeyboardButton(
                "➖", callback_data=f"rem_{p['id']}_{category_prefix}_{page}"),
            InlineKeyboardButton(
                "➕ Tambah", callback_data=f"add_{p['id']}_{category_prefix}_{page}")
        ])

    # Pagination Row
    nav_row = []
    if page > 1:
        nav_row.append(InlineKeyboardButton(
            "⬅️ Prev", callback_data=f"page_{category_prefix}_{page-1}"))
    if page < total_pages:
        nav_row.append(InlineKeyboardButton(
            "Next ➡️", callback_data=f"page_{category_prefix}_{page+1}"))
    if nav_row:
        keyboard.append(nav_row)

    # Back to Categories Row
    keyboard.append([InlineKeyboardButton(
        "🔙 Kembali ke Kategori", callback_data="back_to_cat")])
    keyboard.append([InlineKeyboardButton(
        "✅ Selesai Memilih", callback_data="done_ordering")])

    return InlineKeyboardMarkup(keyboard), category


# --- Handler Functions ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /start command."""
    # Pre-load cart and cache on start
    user_id = update.effective_user.id
    _refresh_cache_if_needed()
    load_db_cart_to_memory(user_id, context)

    # Keep username/full_name up-to-date for registered users
    tg_user = update.effective_user
    sync_user_info(tg_user.id, tg_user.username, tg_user.full_name)

    reply_markup = ReplyKeyboardMarkup(
        START_KEYBOARD,
        resize_keyboard=True,
        one_time_keyboard=True
    )
    await update.message.reply_text(
        "Halo! Selamat datang di Toko Kelontong 🏪\nTekan tombol di bawah untuk mulai.",
        reply_markup=reply_markup
    )


async def handler_mulai(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for the 'Mulai' button — goes directly to catalog."""
    user_id = update.effective_user.id
    ensure_cart_loaded(user_id, context)

    # Remove the reply keyboard
    await update.message.reply_text(
        "Selamat datang di Toko Kelontong! 🏪",
        reply_markup=ReplyKeyboardRemove()
    )

    # Show catalog directly
    text = build_cart_text_from_memory(
        context, "🏪 *Katalog Produk*\n\nSilakan pilih kategori:")
    reply_markup = build_categories_keyboard()
    await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")


async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for inline keyboard button clicks."""
    query = update.callback_query
    user_id = update.effective_user.id
    data = query.data

    # Ensure cart is loaded into memory
    ensure_cart_loaded(user_id, context)

    if data == "noop":
        await query.answer()
        return

    # Handle "done ordering" — go directly to payment options
    if data == "done_ordering":
        await query.answer()
        cart_items = memory_cart_to_summary(context)
        if not cart_items:
            await query.edit_message_text("Keranjang kamu masih kosong. Silakan tambah produk dulu.")
            return

        # Sync to DB in background
        sync_memory_cart_to_db(user_id, context)

        calc = calculate_cart_with_discounts(cart_items)
        order_text = "🧾 *Ringkasan Transaksi:*\n\n"
        for item in calc["items"]:
            order_text += f"▪️ {item['item_name']} x{item['qty']} — Rp{item['subtotal']:,}\n"
            if item['discount_amount'] > 0:
                order_text += f"   🏷️ Diskon — -Rp{item['discount_amount']:,}\n"
        order_text += f"\n💰 *Subtotal: Rp{calc['subtotal']:,}*\n"
        if calc["total_discount"] > 0:
            order_text += f"🏷️ *Total Diskon: -Rp{calc['total_discount']:,}*\n"
            order_text += f"💵 *Grand Total: Rp{calc['grand_total']:,}*"
        order_text += "\n\nPilih metode pembayaran:"

        keyboard = [
            [InlineKeyboardButton("💵 Tunai (Cash)", callback_data="pay_cash")],
            [InlineKeyboardButton("📱 QRIS", callback_data="pay_qris")],
            [InlineKeyboardButton("🔙 Kembali ke Katalog", callback_data="back_to_catalog")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(order_text, reply_markup=reply_markup, parse_mode="Markdown")
        return

    # Handle "back to categories"
    if data in ("back_to_cat", "back_to_catalog"):
        await query.answer()
        text = build_cart_text_from_memory(
            context, "🏪 *Katalog Produk*\n\nSilakan pilih kategori:")
        reply_markup = build_categories_keyboard()
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
        return

    # Handle category click (cat_<category_prefix>)
    if data.startswith("cat_"):
        await query.answer()
        cat_prefix = data[4:]
        reply_markup, full_cat_name = build_products_keyboard(
            cat_prefix, page=1)
        text = build_cart_text_from_memory(
            context, f"📦 *Kategori: {full_cat_name}*\n\nPilih produk:")
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
        return

    # Handle cash payment — show denomination selector
    if data == "pay_cash":
        await query.answer()
        cart_items = memory_cart_to_summary(context)
        if not cart_items:
            await query.edit_message_text("Keranjang kamu masih kosong.")
            return

        calc = calculate_cart_with_discounts(cart_items)
        # Initialize cash data in user context
        cash_data = {str(d): 0 for d in CASH_DENOMINATIONS}
        context.user_data["cash_data"] = cash_data
        context.user_data["cash_grand_total"] = calc["grand_total"]

        text = build_cash_text(calc["grand_total"], cash_data)
        reply_markup = build_cash_keyboard(cash_data)
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
        return

    # Handle cash denomination add (cadd_<denom>) — PURE MEMORY, no DB
    if data.startswith("cadd_"):
        denom = data[5:]
        cash_data = context.user_data.get("cash_data", {})
        cash_data[denom] = cash_data.get(denom, 0) + 1
        context.user_data["cash_data"] = cash_data
        grand_total = context.user_data.get("cash_grand_total", 0)

        # Answer with quick feedback
        await query.answer(f"➕ {DENOM_LABELS.get(int(denom), denom)}")

        text = build_cash_text(grand_total, cash_data)
        reply_markup = build_cash_keyboard(cash_data)
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
        return

    # Handle cash denomination subtract (csub_<denom>) — PURE MEMORY, no DB
    if data.startswith("csub_"):
        denom = data[5:]
        cash_data = context.user_data.get("cash_data", {})
        if cash_data.get(denom, 0) > 0:
            cash_data[denom] -= 1
            await query.answer(f"➖ {DENOM_LABELS.get(int(denom), denom)}")
        else:
            await query.answer("Sudah 0")
            return
        context.user_data["cash_data"] = cash_data
        grand_total = context.user_data.get("cash_grand_total", 0)

        text = build_cash_text(grand_total, cash_data)
        reply_markup = build_cash_keyboard(cash_data)
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
        return

    # Handle cash reset
    if data == "cash_reset":
        await query.answer("🔄 Reset")
        cash_data = {str(d): 0 for d in CASH_DENOMINATIONS}
        context.user_data["cash_data"] = cash_data
        grand_total = context.user_data.get("cash_grand_total", 0)

        text = build_cash_text(grand_total, cash_data)
        reply_markup = build_cash_keyboard(cash_data)
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
        return

    # Handle cash cancel — back to payment method selection
    if data == "cash_cancel":
        await query.answer()
        context.user_data.pop("cash_data", None)
        context.user_data.pop("cash_grand_total", None)

        cart_items = memory_cart_to_summary(context)
        if not cart_items:
            await query.edit_message_text("Keranjang kamu masih kosong.")
            return

        calc = calculate_cart_with_discounts(cart_items)
        order_text = "🧾 *Ringkasan Transaksi:*\n\n"
        for item in calc["items"]:
            order_text += f"▪️ {item['item_name']} x{item['qty']} — Rp{item['subtotal']:,}\n"
            if item['discount_amount'] > 0:
                order_text += f"   🏷️ Diskon — -Rp{item['discount_amount']:,}\n"
        order_text += f"\n💰 *Subtotal: Rp{calc['subtotal']:,}*\n"
        if calc["total_discount"] > 0:
            order_text += f"🏷️ *Total Diskon: -Rp{calc['total_discount']:,}*\n"
            order_text += f"💵 *Grand Total: Rp{calc['grand_total']:,}*"
        order_text += "\n\nPilih metode pembayaran:"

        keyboard = [
            [InlineKeyboardButton("💵 Tunai (Cash)", callback_data="pay_cash")],
            [InlineKeyboardButton("📱 QRIS", callback_data="pay_qris")],
            [InlineKeyboardButton("🔙 Kembali ke Katalog", callback_data="back_to_catalog")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(order_text, reply_markup=reply_markup, parse_mode="Markdown")
        return

    # Handle cash confirm — process cash transaction
    if data == "cash_confirm":
        cash_data = context.user_data.get("cash_data", {})
        grand_total = context.user_data.get("cash_grand_total", 0)
        cash_total = get_cash_total(cash_data)

        if cash_total < grand_total:
            await query.answer("⚠️ Uang belum cukup! Tambah lagi.", show_alert=True)
            return

        await query.answer("✅ Memproses...")

        # Sync cart to DB first
        sync_memory_cart_to_db(user_id, context)

        cart_items = get_cart_summary(user_id)
        if not cart_items:
            await query.edit_message_text("Keranjang kamu masih kosong.")
            return

        now = datetime.datetime.now()
        date_str = now.strftime("%d %B %Y %H:%M:%S")
        calc = calculate_cart_with_discounts(cart_items)
        payment_method = "Tunai (Cash)"
        change = cash_total - grand_total

        db = SessionLocal()
        new_trx = Transaction(
            user_id=user_id,
            payment_method=payment_method,
            total_amount=calc["grand_total"],   # legacy compat
            subtotal=calc["subtotal"],
            total_discount=calc["total_discount"],
            grand_total=calc["grand_total"],
            cash_received=cash_total,
            cash_change=change if change > 0 else 0,
            status="completed",
            created_at=now
        )
        db.add(new_trx)
        db.commit()
        db.refresh(new_trx)
        trx_no = f"INV-{new_trx.id:06d}"

        # Save invoice_no back to the transaction
        new_trx.invoice_no = trx_no

        # Save transaction items (line-item snapshots)
        for item in calc["items"]:
            trx_item = TransactionItem(
                transaction_id=new_trx.id,
                product_id=item["product_id"],
                product_name=item["item_name"],
                unit_price=item["price"],
                quantity=item["qty"],
                discount_type=item["discount_type"],
                discount_value=item["discount_value"] or 0,
                discount_amount=item["discount_amount"],
                subtotal=item["final_subtotal"]
            )
            db.add(trx_item)
        db.commit()

        recommendations = get_recommendations(calc["purchased_categories"])
        store_schedule = get_upcoming_schedules_receipt()
        receipt_io = generate_receipt_image(
            trx_no=trx_no,
            date_str=date_str,
            cart_items=cart_items,
            total=calc["subtotal"],
            payment_method=payment_method,
            discount_details=calc["discount_details"],
            total_discount=calc["total_discount"],
            grand_total=calc["grand_total"],
            recommendations=recommendations,
            whatsapp_number=WHATSAPP_NUMBER,
            store_schedule=store_schedule
        )

        db.query(CartItem).filter(CartItem.user_id == user_id).delete()
        db.commit()
        db.close()

        # Clear in-memory cart too
        set_memory_cart(context, {})

        # Build change info for the success message
        change = cash_total - grand_total
        change_text = ""
        if change > 0:
            change_text = f"\n💰 Kembalian: *Rp{change:,}*"
            breakdown = build_change_breakdown(change)
            if breakdown:
                change_text += "\n📋 Rincian:"
                for denom, count in breakdown:
                    change_text += f" Rp{denom:,}×{count}"

        await query.edit_message_text(
            f"✅ Pembayaran tunai berhasil!\n"
            f"🧾 Invoice: {trx_no}\n"
            f"💵 Dibayar: Rp{cash_total:,}"
            f"{change_text}\n\n"
            f"Sedang mengirim struk...",
            parse_mode="Markdown"
        )

        await context.bot.send_photo(
            chat_id=user_id,
            photo=receipt_io,
            caption="🧾 *STRUK TRANSAKSI*\nSilakan klik Share dan cetak via RawBT.",
            parse_mode="Markdown"
        )

        # Cleanup user data
        context.user_data.pop("cash_data", None)
        context.user_data.pop("cash_grand_total", None)
        return

    # Handle QRIS payment — process immediately
    if data == "pay_qris":
        await query.answer("✅ Memproses...")

        # Sync cart to DB first
        sync_memory_cart_to_db(user_id, context)

        cart_items = get_cart_summary(user_id)
        if not cart_items:
            await query.edit_message_text("Keranjang kamu masih kosong.")
            return

        now = datetime.datetime.now()
        date_str = now.strftime("%d %B %Y %H:%M:%S")

        calc = calculate_cart_with_discounts(cart_items)
        payment_method = "QRIS"

        db = SessionLocal()

        # Save transaction with full breakdown
        new_trx = Transaction(
            user_id=user_id,
            payment_method=payment_method,
            total_amount=calc["grand_total"],   # legacy compat
            subtotal=calc["subtotal"],
            total_discount=calc["total_discount"],
            grand_total=calc["grand_total"],
            status="completed",
            created_at=now
        )
        db.add(new_trx)
        db.commit()
        db.refresh(new_trx)

        # Generate sequential transaction number (e.g. INV-000001)
        trx_no = f"INV-{new_trx.id:06d}"
        new_trx.invoice_no = trx_no

        # Save transaction items (line-item snapshots)
        for item in calc["items"]:
            trx_item = TransactionItem(
                transaction_id=new_trx.id,
                product_id=item["product_id"],
                product_name=item["item_name"],
                unit_price=item["price"],
                quantity=item["qty"],
                discount_type=item["discount_type"],
                discount_value=item["discount_value"] or 0,
                discount_amount=item["discount_amount"],
                subtotal=item["final_subtotal"]
            )
            db.add(trx_item)
        db.commit()

        # Get recommendations
        recommendations = get_recommendations(calc["purchased_categories"])

        # Generate Image receipt
        store_schedule = get_upcoming_schedules_receipt()
        receipt_io = generate_receipt_image(
            trx_no=trx_no,
            date_str=date_str,
            cart_items=cart_items,
            total=calc["subtotal"],
            payment_method=payment_method,
            discount_details=calc["discount_details"],
            total_discount=calc["total_discount"],
            grand_total=calc["grand_total"],
            recommendations=recommendations,
            whatsapp_number=WHATSAPP_NUMBER,
            store_schedule=store_schedule
        )

        # Clear cart (DB + memory)
        db.query(CartItem).filter(CartItem.user_id == user_id).delete()
        db.commit()
        db.close()
        set_memory_cart(context, {})

        # Update the inline keyboard message to show success
        await query.edit_message_text("✅ Pembayaran berhasil diproses. Sedang mengirim struk...")

        # Send the generated receipt as a photo
        await context.bot.send_photo(
            chat_id=user_id,
            photo=receipt_io,
            caption="🧾 *STRUK TRANSAKSI*\nSilakan klik Share dan cetak via RawBT.",
            parse_mode="Markdown"
        )
        return

    # Handle pagination (page_<category_prefix>_<page>)
    if data.startswith("page_"):
        await query.answer()
        parts = data.split("_")
        cat_prefix = parts[1]
        page = int(parts[2])
        reply_markup, full_cat_name = build_products_keyboard(
            cat_prefix, page=page)
        text = build_cart_text_from_memory(
            context, f"📦 *Kategori: {full_cat_name}*\n\nPilih produk:")
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
        return

    # Handle add item (add_<product_id>_<category_prefix>_<page>) — IN-MEMORY, no DB hit!
    if data.startswith("add_"):
        parts = data.split("_")
        product_id = int(parts[1])
        cat_prefix = parts[2]
        page = int(parts[3])

        # Update in-memory cart (instant!)
        add_to_memory_cart(context, product_id)

        # Quick feedback via callback answer
        _refresh_cache_if_needed()
        product_name = _product_cache.get(product_id, {}).get("item_name", "")
        await query.answer(f"➕ {product_name}")

        reply_markup, full_cat_name = build_products_keyboard(
            cat_prefix, page=page)
        text = build_cart_text_from_memory(
            context, f"📦 *Kategori: {full_cat_name}*\n\nPilih produk:")
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
        return

    # Handle remove item (rem_<product_id>_<category_prefix>_<page>) — IN-MEMORY, no DB hit!
    if data.startswith("rem_"):
        parts = data.split("_")
        product_id = int(parts[1])
        cat_prefix = parts[2]
        page = int(parts[3])

        # Update in-memory cart (instant!)
        remove_from_memory_cart(context, product_id)

        _refresh_cache_if_needed()
        product_name = _product_cache.get(product_id, {}).get("item_name", "")
        await query.answer(f"➖ {product_name}")

        reply_markup, full_cat_name = build_products_keyboard(
            cat_prefix, page=page)
        text = build_cart_text_from_memory(
            context, f"📦 *Kategori: {full_cat_name}*\n\nPilih produk:")
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
        return

    # Fallback — unknown callback
    await query.answer()





async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Catch-all for text messages. Routes to voice correction if active."""
    # Check if admin is in voice correction mode
    if context.user_data.get("voice_correction_mode"):
        handled = await handle_voice_text_correction(update, context)
        if handled:
            return
    await update.message.reply_text("Silakan gunakan tombol menu di bawah.")


async def handler_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /help command."""
    text = (
        "📖 *Panduan Penggunaan Bot Toko Kelontong*\n\n"
        "🛒 *Untuk Pelanggan:*\n"
        "▪️ Tekan 🚀 Mulai untuk mulai belanja\n"
        "▪️ Pilih kategori → pilih produk → ✅ Selesai Memilih\n"
        "▪️ Pilih metode bayar (Tunai/QRIS) → terima struk\n"
        "▪️ /riwayat — Lihat riwayat transaksi kamu\n\n"
        "🔧 *Untuk Admin:*\n"
        "▪️ /laporan — Laporan penjualan (harian/mingguan/bulanan)\n"
        "▪️ /void — Void/batalkan transaksi hari ini\n"
        "▪️ /promo — Kelola promosi (tambah/edit/hapus)\n"
        "▪️ /jadwal — Kelola jadwal operasional toko\n"
        "▪️ 🎤 *Voice Note* — Kirim perintah suara untuk:\n"
        "   • Ubah harga produk\n"
        "   • Tambah/hapus produk\n"
        "   • Buat/hapus promosi\n"
        "   • Atur jadwal toko\n"
        "   • Lihat daftar produk/promo\n\n"
        "💡 *Contoh perintah suara:*\n"
        '   _"Ubah harga Indomie Goreng jadi 4000"_\n'
        '   _"Tambah produk Sabun Cair harga 15000 kategori Perawatan Tubuh"_\n'
        '   _"Buat promo diskon 10% untuk Chitato mulai 1 Juli sampai 31 Juli"_\n'
        '   _"Tampilkan semua produk Sembako"_\n\n'
        "▪️ /cancel — Batalkan operasi yang sedang berjalan"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def post_init(application):
    """Register bot commands and bootstrap the developer on startup."""
    # Bootstrap developer account in DB (safe to call every start)
    bootstrap_developer(
        telegram_id=DEVELOPER_TELEGRAM_ID,
        username="merkava1945",
        full_name="Admiral Kuznetsov"
    )

    commands = [
        BotCommand("start",   "🚀 Mulai bot"),
        BotCommand("help",    "📖 Panduan penggunaan"),
        BotCommand("riwayat", "📜 Riwayat transaksi"),
        BotCommand("laporan", "📊 Laporan penjualan (kasir/vendor)"),
        BotCommand("void",    "❌ Void transaksi (kasir/vendor)"),
        BotCommand("promo",   "🏷️ Kelola promosi (kasir/vendor)"),
        BotCommand("jadwal",  "🗓️ Kelola jadwal toko (kasir/vendor)"),
        BotCommand("panel",   "🏤 Panel vendor (pemilik toko)"),
        BotCommand("dev",     "👨‍💻 Panel developer (sistem)"),
        BotCommand("cancel",  "❌ Batalkan operasi"),
    ]
    await application.bot.set_my_commands(commands)
    # Pre-load product cache at startup
    _refresh_cache_if_needed()


# --- Main Entry Point ---

if __name__ == "__main__":
    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .concurrent_updates(True)    # ⚡ Process multiple callbacks in parallel!
        .build()
    )

    # ConversationHandlers — order matters: more specific first
    app.add_handler(get_dev_handler())           # /dev    — Developer panel (TOTP)
    app.add_handler(get_vendor_handler())        # /panel  — Vendor panel
    app.add_handler(get_admin_conv_handler())    # /promo  — Promotions CRUD
    app.add_handler(get_admin_schedule_handler()) # /jadwal — Schedule CRUD
    app.add_handler(get_report_conv_handler())   # /laporan — Sales reports
    app.add_handler(get_void_conv_handler())     # /void   — Void transaction

    app.add_handler(CommandHandler("start",    start))
    app.add_handler(CommandHandler("help",     handler_help))
    app.add_handler(CommandHandler("riwayat",  riwayat_command))

    # Voice confirmation callback handler (must be before generic button_click)
    app.add_handler(CallbackQueryHandler(handle_voice_callback, pattern="^vc_"))
    # Transaction detail callback handler
    app.add_handler(CallbackQueryHandler(handle_trx_detail_callback, pattern="^trx_detail_"))
    app.add_handler(CallbackQueryHandler(button_click))

    app.add_handler(MessageHandler(filters.Regex("^🚀 Mulai$"), handler_mulai))

    # Voice note handler — AI-powered CRUD via voice commands (admin only)
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))

    # Text catch-all (also handles voice text correction mode)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))

    print("Bot is running...")
    app.run_polling()
