from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters, CallbackQueryHandler
from telegram import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import func
from database import SessionLocal, CartItem, Product, Transaction
from receipt_generator import generate_receipt_image
import math
import datetime
import os
import random


# --- Keyboard Layouts (Global Constants) ---

START_KEYBOARD = [
    [KeyboardButton("🚀 Mulai")]
]

MAIN_MENU_KEYBOARD = [
    [KeyboardButton("🛒 Katalog & Pesan")],
    [KeyboardButton("📞 Kontak"), KeyboardButton("🕐 Jam Buka")],
    [KeyboardButton("✅ Selesaikan Transaksi")]
]


# --- Helper Functions ---

def get_cart_summary(user_id):
    """Get cart items joined with products for a user."""
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


def build_cart_text(user_id, prepend_text=""):
    """Build the cart summary text."""
    cart_items = get_cart_summary(user_id)

    text = prepend_text + "\n"

    if cart_items:
        text += "━━━━━━━━━━━━━━━━━━━━\n"
        text += "🛒 *Keranjang kamu:*\n\n"
        total = 0
        for product_id, item_name, price, qty in cart_items:
            subtotal = price * qty
            total += subtotal
            text += f"▪️ {item_name} x{qty} — Rp{subtotal:,}\n"
        text += f"\n💰 *Total: Rp{total:,}*\n"
        text += "━━━━━━━━━━━━━━━━━━━━"
    else:
        text += "_Keranjang masih kosong_"

    return text


def build_categories_keyboard():
    """Build the inline keyboard for categories."""
    db = SessionLocal()
    categories = db.query(Product.category).distinct().all()
    db.close()

    keyboard = []
    # Display 2 categories per row
    row = []
    for cat in categories:
        cat_name = cat[0]
        # Using a short callback data to avoid Telegram's 64 byte limit
        # In a real large app, you'd map categories to IDs. Here we truncate if needed.
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
    """Build the inline keyboard for products in a category with pagination."""
    db = SessionLocal()
    # Match the category using LIKE since we might have truncated the prefix
    category = db.query(Product.category).filter(
        Product.category.startswith(category_prefix)).first()[0]

    per_page = 5
    total_products = db.query(Product).filter(
        Product.category == category).count()
    total_pages = math.ceil(total_products / per_page)

    offset = (page - 1) * per_page
    products = db.query(Product).filter(Product.category ==
                                        category).offset(offset).limit(per_page).all()
    db.close()

    keyboard = []

    # Product Rows
    for p in products:
        keyboard.append([InlineKeyboardButton(
            f"{p.item_name} - Rp{p.price:,}", callback_data=f"noop")])
        keyboard.append([
            InlineKeyboardButton(
                "➖", callback_data=f"rem_{p.id}_{category_prefix}_{page}"),
            InlineKeyboardButton(
                "➕ Tambah", callback_data=f"add_{p.id}_{category_prefix}_{page}")
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
    """Handler for the 'Mulai' button."""
    reply_markup = ReplyKeyboardMarkup(
        MAIN_MENU_KEYBOARD,
        resize_keyboard=True,
        one_time_keyboard=False
    )
    await update.message.reply_text(
        "Selamat datang, silakan pilih menu di bawah",
        reply_markup=reply_markup
    )


async def handler_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for the 'Katalog' button — shows categories."""
    user_id = update.effective_user.id
    text = build_cart_text(
        user_id, "🏪 *Katalog Produk*\n\nSilakan pilih kategori:")
    reply_markup = build_categories_keyboard()
    await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")


async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for inline keyboard button clicks."""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    data = query.data

    if data == "noop":
        return

    # Handle "done ordering"
    if data == "done_ordering":
        cart_items = get_cart_summary(user_id)
        if not cart_items:
            await query.edit_message_text("Keranjang kamu masih kosong. Tekan 🛒 Katalog & Pesan untuk memilih produk.")
            return

        text = build_cart_text(
            user_id, "👍 Selesai memilih!\n\nTekan ✅ Selesaikan Transaksi pada menu utama untuk checkout.")
        await query.edit_message_text(text, parse_mode="Markdown")
        return

    # Handle "back to categories"
    if data == "back_to_cat":
        text = build_cart_text(
            user_id, "🏪 *Katalog Produk*\n\nSilakan pilih kategori:")
        reply_markup = build_categories_keyboard()
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
        return

    # Handle category click (cat_<category_prefix>)
    if data.startswith("cat_"):
        cat_prefix = data[4:]
        reply_markup, full_cat_name = build_products_keyboard(
            cat_prefix, page=1)
        text = build_cart_text(
            user_id, f"📦 *Kategori: {full_cat_name}*\n\nPilih produk:")
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
        return

    # Handle payment types (pay_cash, pay_qris)
    if data in ["pay_cash", "pay_qris"]:
        cart_items = get_cart_summary(user_id)
        if not cart_items:
            await query.edit_message_text("Keranjang kamu masih kosong.")
            return

        now = datetime.datetime.now()
        date_str = now.strftime("%d %B %Y %H:%M:%S")

        # Calculate total
        total = 0
        for product_id, item_name, price, qty in cart_items:
            subtotal = price * qty
            total += subtotal

        payment_method = "Tunai (Cash)" if data == "pay_cash" else "QRIS"

        db = SessionLocal()

        # Save transaction
        new_trx = Transaction(
            user_id=user_id,
            payment_method=payment_method,
            total_amount=total,
            created_at=date_str
        )
        db.add(new_trx)
        db.commit()
        db.refresh(new_trx)

        # Generate sequential transaction number (e.g. INV-000001)
        trx_no = f"INV-{new_trx.id:06d}"

        # Generate Image receipt
        receipt_io = generate_receipt_image(
            trx_no, date_str, cart_items, total, payment_method)

        # Clear cart
        db.query(CartItem).filter(CartItem.user_id == user_id).delete()
        db.commit()
        db.close()

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
        parts = data.split("_")
        cat_prefix = parts[1]
        page = int(parts[2])
        reply_markup, full_cat_name = build_products_keyboard(
            cat_prefix, page=page)
        text = build_cart_text(
            user_id, f"📦 *Kategori: {full_cat_name}*\n\nPilih produk:")
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
        return

    # Handle add item (add_<product_id>_<category_prefix>_<page>)
    if data.startswith("add_"):
        parts = data.split("_")
        product_id = int(parts[1])
        cat_prefix = parts[2]
        page = int(parts[3])

        db = SessionLocal()
        new_item = CartItem(user_id=user_id, product_id=product_id)
        db.add(new_item)
        db.commit()
        db.close()

        reply_markup, full_cat_name = build_products_keyboard(
            cat_prefix, page=page)
        text = build_cart_text(
            user_id, f"📦 *Kategori: {full_cat_name}*\n\nPilih produk:")
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
        return

    # Handle remove item (rem_<product_id>_<category_prefix>_<page>)
    if data.startswith("rem_"):
        parts = data.split("_")
        product_id = int(parts[1])
        cat_prefix = parts[2]
        page = int(parts[3])

        db = SessionLocal()
        item_to_remove = db.query(CartItem).filter(
            CartItem.user_id == user_id,
            CartItem.product_id == product_id
        ).first()
        if item_to_remove:
            db.delete(item_to_remove)
            db.commit()
        db.close()

        reply_markup, full_cat_name = build_products_keyboard(
            cat_prefix, page=page)
        text = build_cart_text(
            user_id, f"📦 *Kategori: {full_cat_name}*\n\nPilih produk:")
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
        return


async def handler_checkout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for checkout — shows payment options."""
    user_id = update.effective_user.id
    cart_items = get_cart_summary(user_id)

    if not cart_items:
        await update.message.reply_text("Keranjang kamu masih kosong.")
        return

    order_text = "🧾 *Ringkasan Transaksi:*\n\n"
    total = 0
    for product_id, item_name, price, qty in cart_items:
        subtotal = price * qty
        total += subtotal
        order_text += f"▪️ {item_name} x{qty} — Rp{subtotal:,}\n"
    order_text += f"\n💰 *Total Transaksi: Rp{total:,}*"
    order_text += "\n\nPilih metode pembayaran di bawah:"

    keyboard = [
        [InlineKeyboardButton("💵 Tunai (Cash)", callback_data="pay_cash")],
        [InlineKeyboardButton("📱 QRIS", callback_data="pay_qris")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(order_text, reply_markup=reply_markup, parse_mode="Markdown")


async def handler_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Hubungi tim support kami di @support_user")


async def handler_hours(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Kami buka 24 jam.")


async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Silakan gunakan tombol menu di bawah.")


# --- Main Entry Point ---

if __name__ == "__main__":
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError(
            "BOT_TOKEN environment variable is not set. Please set it before running the bot.")

    app = ApplicationBuilder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_click))

    app.add_handler(MessageHandler(filters.Regex("^🚀 Mulai$"), handler_mulai))
    app.add_handler(MessageHandler(filters.Regex(
        "^🛒 Katalog & Pesan$"), handler_menu))
    app.add_handler(MessageHandler(
        filters.Regex("^📞 Kontak$"), handler_contact))
    app.add_handler(MessageHandler(
        filters.Regex("^🕐 Jam Buka$"), handler_hours))
    app.add_handler(MessageHandler(filters.Regex(
        "^✅ Selesaikan Transaksi$"), handler_checkout))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))

    print("Bot is running...")
    app.run_polling()
