import io
from PIL import Image, ImageDraw, ImageFont

def generate_receipt_image(trx_no, date_str, cart_items, total, payment_method):
    """
    Generates a 58mm thermal-printer compatible receipt image.
    Width: 384 pixels (Standard for 58mm printers).
    Returns an io.BytesIO object containing the JPEG image.
    """
    # 58mm standard width in pixels
    WIDTH = 384
    
    # Try to load a monospaced font, fallback to default
    try:
        font = ImageFont.truetype("consola.ttf", 20)
        font_bold = ImageFont.truetype("consolab.ttf", 24)
        font_title = ImageFont.truetype("consolab.ttf", 32)
    except IOError:
        # Fallback if Consolas is not available
        font = ImageFont.load_default()
        font_bold = font
        font_title = font

    # Calculate height based on number of items
    # Base height (header + footer) approx 400px, each item adds approx 50px
    base_height = 450
    item_height = 50
    HEIGHT = base_height + (len(cart_items) * item_height)
    
    # Create white canvas
    img = Image.new('RGB', (WIDTH, HEIGHT), color='white')
    draw = ImageDraw.Draw(img)
    
    y = 20
    
    # Draw Title (Centered)
    title = "TOKO KELONTONG"
    # Using textbbox to get width for centering if available, else hardcode approx
    try:
        title_w = draw.textlength(title, font=font_title)
    except AttributeError:
        title_w = 200 # fallback
    
    draw.text(((WIDTH - title_w) / 2, y), title, font=font_title, fill='black')
    y += 50
    
    # Draw Header Info
    draw.text((20, y), f"No   : {trx_no}", font=font, fill='black')
    y += 30
    draw.text((20, y), f"Waktu: {date_str}", font=font, fill='black')
    y += 40
    
    # Divider
    draw.text((20, y), "-" * 32, font=font, fill='black')
    y += 30
    
    # Draw Items
    for product_id, item_name, price, qty in cart_items:
        subtotal = price * qty
        # Item name (wrap if too long, but we'll just truncate for simplicity)
        name_display = item_name[:28] 
        draw.text((20, y), name_display, font=font_bold, fill='black')
        y += 25
        
        qty_price_str = f"{qty} x Rp{price:,}"
        subtotal_str = f"Rp{subtotal:,}"
        
        # Right align subtotal
        try:
            subtotal_w = draw.textlength(subtotal_str, font=font)
        except AttributeError:
            subtotal_w = len(subtotal_str) * 10
            
        draw.text((20, y), qty_price_str, font=font, fill='black')
        draw.text((WIDTH - 20 - subtotal_w, y), subtotal_str, font=font, fill='black')
        y += 35

    # Divider
    draw.text((20, y), "-" * 32, font=font, fill='black')
    y += 30
    
    # Total
    total_str = f"Rp{total:,}"
    try:
        total_w = draw.textlength(total_str, font=font_bold)
    except AttributeError:
        total_w = len(total_str) * 12
        
    draw.text((20, y), "TOTAL:", font=font_bold, fill='black')
    draw.text((WIDTH - 20 - total_w, y), total_str, font=font_bold, fill='black')
    y += 40
    
    # Payment Method
    draw.text((20, y), f"Pembayaran: {payment_method}", font=font, fill='black')
    y += 50
    
    # Footer
    footer = "Terima Kasih Atas\nKunjungan Anda!"
    # Simple centering for multiline (approx)
    draw.text((80, y), footer, font=font_bold, fill='black', align='center')

    # Save to BytesIO
    byte_io = io.BytesIO()
    img.save(byte_io, 'PNG')
    byte_io.seek(0)
    
    return byte_io
