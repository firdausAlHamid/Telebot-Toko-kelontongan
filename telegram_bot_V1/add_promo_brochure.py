import re

# --- 1. Modify receipt_generator.py ---
with open("receipt_generator.py", "r", encoding="utf-8") as f:
    receipt_content = f.read()

promo_func = """
def generate_promo_brochure_image(promos, store_name, join_link=None):
    \"\"\"Generates a receipt-style brochure for active promotions.\"\"\"
    WIDTH = 384
    font, font_bold, font_title, font_small = _load_fonts()
    
    MAX_HEIGHT = 500 + (len(promos) * 150)
    img = Image.new('RGB', (WIDTH, MAX_HEIGHT), color='white')
    draw = ImageDraw.Draw(img)
    y = 20
    
    def get_text_width(text, f):
        try:
            return draw.textlength(text, font=f)
        except AttributeError:
            return len(text) * (12 if f == font_bold else 10)

    # Header
    title = store_name
    draw.text(((WIDTH - get_text_width(title, font_title)) / 2, y), title, font=font_title, fill='black')
    y += 40
    
    subtitle = "=== BROSUR PROMO ==="
    draw.text(((WIDTH - get_text_width(subtitle, font_bold)) / 2, y), subtitle, font=font_bold, fill='black')
    y += 40
    
    draw.text((20, y), "-" * 32, font=font, fill='black')
    y += 30
    
    if not promos:
        text = "Belum ada promo saat ini."
        draw.text(((WIDTH - get_text_width(text, font)) / 2, y), text, font=font, fill='black')
        y += 40
    else:
        for p in promos:
            wrapped_name = textwrap.wrap(p['product_name'], width=24)
            for line in wrapped_name:
                draw.text((20, y), line, font=font_bold, fill='black')
                y += 25
            
            draw.text((20, y), f"Diskon: {p['discount_text']}", font=font, fill='black')
            y += 25
            draw.text((20, y), f"Berlaku: {p['start_date_str']} s/d {p['end_date_str']}", font=font_small, fill='black')
            y += 25
            if p.get('target_category') and p['target_category'].lower() != "semua":
                draw.text((20, y), f"Khusus Beli: {p['target_category']}", font=font_small, fill='black')
                y += 25
            y += 20
    
    draw.text((20, y), "=" * 32, font=font, fill='black')
    y += 30
    
    if join_link:
        qr = qrcode.QRCode(version=1, box_size=5, border=1)
        qr.add_data(join_link)
        qr.make(fit=True)
        qr_img = qr.make_image(fill_color="black", back_color="white").get_image()
        qr_w, qr_h = qr_img.size
        img.paste(qr_img, (int((WIDTH - qr_w) / 2), y))
        y += qr_h + 10
        
        scan_text = "Scan untuk Gabung & Pesan!"
        draw.text(((WIDTH - get_text_width(scan_text, font_small)) / 2, y), scan_text, font=font_small, fill='black')
        y += 30

    y += 20
    img = img.crop((0, 0, WIDTH, y))
    
    byte_io = io.BytesIO()
    img.save(byte_io, 'PNG')
    byte_io.seek(0)
    return byte_io
"""

if "generate_promo_brochure_image" not in receipt_content:
    receipt_content += "\n" + promo_func
    with open("receipt_generator.py", "w", encoding="utf-8") as f:
        f.write(receipt_content)
    print("Added generate_promo_brochure_image to receipt_generator.py")


# --- 2. Modify admin_handlers.py ---
with open("admin_handlers.py", "r", encoding="utf-8") as f:
    admin_content = f.read()

# Add imports
if "from auth import can" not in admin_content:
    admin_content = admin_content.replace(
        "from auth import require, get_tenant_id",
        "from auth import require, get_tenant_id, can, get_store_name"
    )
if "from receipt_generator" not in admin_content:
    admin_content = admin_content.replace(
        "from database import SessionLocal",
        "from receipt_generator import generate_promo_brochure_image\nfrom database import SessionLocal"
    )

old_show_list = """async def show_promo_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    \"\"\"Show all active promotions as a formatted list.\"\"\"
    promos = list_promotions(active_only=True)

    if not promos:
        text = "📋 *Daftar Promosi*\\n\\n_Belum ada promosi aktif._"
    else:
        text = f"📋 *Daftar Promosi Aktif* ({len(promos)})\\n\\n"
        for p in promos:
            text += (
                f"*#{p['id']}* — {p['product_name']}\\n"
                f"   🏷️ Diskon: {p['discount_text']}\\n"
                f"   📅 {p['start_date_str']} — {p['end_date_str']}\\n"
                f"   🎯 Target: {p['target_category']}\\n"
                f"   {p['status']}\\n\\n"
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

    return PROMO_MENU"""

new_show_list = """async def show_promo_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    \"\"\"Show all active promotions as a receipt-style brochure.\"\"\"
    user_id = update.effective_user.id
    tenant_id = get_tenant_id(user_id)
    promos = list_promotions(active_only=True, tenant_id=tenant_id)
    store_name = get_store_name(user_id) or "TOKO KELONTONG"
    join_link = f"https://t.me/{context.bot.username}?start=toko_{tenant_id}"
    
    # Generate image
    image_io = generate_promo_brochure_image(promos, store_name, join_link=join_link)
    
    keyboard = [[InlineKeyboardButton("🔙 Menu Promosi", callback_data="ap_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        # We can't edit a text message into an image easily without deleting
        # Just delete and send new
        try:
            await update.callback_query.message.delete()
        except:
            pass
        await context.bot.send_photo(
            chat_id=update.effective_chat.id,
            photo=image_io,
            caption="🏷️ *Brosur Promo Aktif*",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_photo(
            photo=image_io,
            caption="🏷️ *Brosur Promo Aktif*",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )

    return PROMO_MENU"""

if "generate_promo_brochure_image(promos" not in admin_content:
    if old_show_list in admin_content:
        admin_content = admin_content.replace(old_show_list, new_show_list)
        with open("admin_handlers.py", "w", encoding="utf-8") as f:
            f.write(admin_content)
        print("Updated show_promo_list to send brochure image")
    else:
        print("Could not find exact old_show_list")
