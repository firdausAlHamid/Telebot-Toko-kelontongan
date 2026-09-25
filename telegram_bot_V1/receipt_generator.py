import io
import os
import qrcode
import textwrap
from PIL import Image, ImageDraw, ImageFont


def _load_fonts():
    """Load monospace fonts with layered fallback. Returns (font, bold, title, small)."""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        (os.path.join(base_dir, "fonts", "DejaVuSansMono.ttf"),
         os.path.join(base_dir, "fonts", "DejaVuSansMono-Bold.ttf")),
        (os.path.join(base_dir, "fonts", "IBMPlexMono-Regular.ttf"),
         os.path.join(base_dir, "fonts", "IBMPlexMono-Bold.ttf")),
        ("fonts/DejaVuSansMono.ttf", "fonts/DejaVuSansMono-Bold.ttf"),
        ("DejaVuSansMono.ttf", "DejaVuSansMono-Bold.ttf"),
        ("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"),
    ]
    for regular, bold in candidates:
        try:
            font = ImageFont.truetype(regular, 18)
            font_bold = ImageFont.truetype(bold, 22)
            font_title = ImageFont.truetype(bold, 28)
            font_small = ImageFont.truetype(regular, 14)
            return font, font_bold, font_title, font_small
        except (IOError, OSError):
            continue
    font = ImageFont.load_default()
    return font, font, font, font

def generate_receipt_image(
    trx_no, date_str, cart_items, total, payment_method,
    discount_details=None, total_discount=0, grand_total=None,
    recommendations=None, whatsapp_number=None, store_schedule=None,
    store_name="TOKO KELONTONG"
):
    """
    Generates a 58mm thermal-printer compatible receipt image.
    Width: 384 pixels (Standard for 58mm printers).
    Returns an io.BytesIO object containing the PNG image.
    """
    WIDTH = 384

    font, font_bold, font_title, font_small = _load_fonts()

    # Instead of predicting the exact height perfectly beforehand,
    # we create a generously large canvas and crop it at the end.
    recs_count = len(recommendations) if recommendations else 0
    MAX_HEIGHT = 1000 + (len(cart_items) * 120) + (recs_count * 150)
    
    # Create white canvas
    img = Image.new('RGB', (WIDTH, MAX_HEIGHT), color='white')
    draw = ImageDraw.Draw(img)
    
    y = 20
    
    def get_text_width(text, f):
        try:
            return draw.textlength(text, font=f)
        except AttributeError:
            return len(text) * (12 if f == font_bold else 10)

    # Draw Title (Centered)
    title = store_name
    title_w = get_text_width(title, font_title)
    draw.text(((WIDTH - title_w) / 2, y), title, font=font_title, fill='black')
    y += 40
    
    # Draw Schedule (if provided)
    if store_schedule:
        for line in store_schedule:
            sched_w = get_text_width(line, font_small)
            draw.text(((WIDTH - sched_w) / 2, y), line, font=font_small, fill='black')
            y += 25
        y += 15
    else:
        y += 10
    
    # Draw Header Info
    draw.text((20, y), f"No   : {trx_no}", font=font, fill='black')
    y += 30
    draw.text((20, y), f"Waktu: {date_str}", font=font, fill='black')
    y += 40
    
    # Divider
    draw.text((20, y), "=" * 32, font=font, fill='black')
    y += 30
    
    # Draw Items
    for product_id, item_name, price, qty in cart_items:
        # Wrap long item names
        wrapped_name = textwrap.wrap(item_name, width=24)
        for line in wrapped_name:
            draw.text((20, y), line, font=font_bold, fill='black')
            y += 25
        
        qty_price_str = f"{qty} x Rp{price:,}"
        subtotal_str = f"Rp{price * qty:,}"
        subtotal_w = get_text_width(subtotal_str, font)
            
        draw.text((20, y), qty_price_str, font=font, fill='black')
        draw.text((WIDTH - 20 - subtotal_w, y), subtotal_str, font=font, fill='black')
        y += 30
        
        # Check if item has discount
        if discount_details and product_id in discount_details:
            disc_info = discount_details[product_id]
            disc_label = f"  Diskon {disc_info['value']}%" if disc_info['type'] == 'percentage' else "  Diskon"
            disc_val_str = f"-Rp{disc_info['amount']:,}"
            disc_val_w = get_text_width(disc_val_str, font)
            
            draw.text((20, y), disc_label, font=font, fill='black')
            draw.text((WIDTH - 20 - disc_val_w, y), disc_val_str, font=font, fill='black')
            y += 30

    # Divider
    draw.text((20, y), "-" * 32, font=font, fill='black')
    y += 30
    
    # Total / Summary
    if total_discount > 0 and grand_total is not None:
        # Subtotal
        sub_str = f"Rp{total:,}"
        draw.text((20, y), "Subtotal:", font=font, fill='black')
        draw.text((WIDTH - 20 - get_text_width(sub_str, font), y), sub_str, font=font, fill='black')
        y += 30
        
        # Discount
        disc_str = f"-Rp{total_discount:,}"
        draw.text((20, y), "Total Diskon:", font=font, fill='black')
        draw.text((WIDTH - 20 - get_text_width(disc_str, font), y), disc_str, font=font, fill='black')
        y += 30
        
        # Grand Total
        gt_str = f"Rp{grand_total:,}"
        draw.text((20, y), "GRAND TOTAL:", font=font_bold, fill='black')
        draw.text((WIDTH - 20 - get_text_width(gt_str, font_bold), y), gt_str, font=font_bold, fill='black')
        y += 40
    else:
        # Normal Total
        total_str = f"Rp{total:,}"
        draw.text((20, y), "TOTAL:", font=font_bold, fill='black')
        draw.text((WIDTH - 20 - get_text_width(total_str, font_bold), y), total_str, font=font_bold, fill='black')
        y += 40
    
    # Payment Method
    draw.text((20, y), f"Pembayaran: {payment_method}", font=font, fill='black')
    y += 40
    
    # Draw Recommendations
    if recommendations:
        draw.text((20, y), "=" * 32, font=font, fill='black')
        y += 30
        
        promo_title = "~ PROMO UNTUK ANDA ~"
        draw.text(((WIDTH - get_text_width(promo_title, font_bold)) / 2, y), promo_title, font=font_bold, fill='black')
        y += 40
        
        for rec in recommendations:
            draw.text((20, y), "Coba:", font=font, fill='black')
            y += 25
            
            wrapped_rec = textwrap.wrap(rec['product_name'], width=24)
            for line in wrapped_rec:
                draw.text((20, y), line, font=font_bold, fill='black')
                y += 25
            
            draw.text((20, y), f"{rec['discount_text']} s/d {rec['end_date_str']}", font=font_small, fill='black')
            y += 40
            
    # Divider
    draw.text((20, y), "=" * 32, font=font, fill='black')
    y += 30
    
    # Footer
    footer = "Terima Kasih Atas\nKunjungan Anda!"
    # Simple centering for multiline (approx)
    for line in footer.split('\n'):
        draw.text(((WIDTH - get_text_width(line, font_bold)) / 2, y), line, font=font_bold, fill='black')
        y += 30
    
    # WhatsApp QR Code
    if whatsapp_number:
        y += 20
        wa_url = f"https://wa.me/{whatsapp_number}"
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=5,
            border=1,
        )
        qr.add_data(wa_url)
        qr.make(fit=True)
        
        qr_img = qr.make_image(fill_color="black", back_color="white")
        qr_pil = qr_img.get_image()
        qr_w, qr_h = qr_pil.size
        
        # Paste QR in the center
        img.paste(qr_pil, (int((WIDTH - qr_w) / 2), y))
        y += qr_h + 10
        
        qr_text = "Hubungi Kami via WhatsApp"
        draw.text(((WIDTH - get_text_width(qr_text, font_small)) / 2, y), qr_text, font=font_small, fill='black')
        y += 30

    # Crop image exactly to final height
    y += 20 # final padding
    img = img.crop((0, 0, WIDTH, y))

    # Save to BytesIO
    byte_io = io.BytesIO()
    img.save(byte_io, 'PNG')
    byte_io.seek(0)
    
    return byte_io
