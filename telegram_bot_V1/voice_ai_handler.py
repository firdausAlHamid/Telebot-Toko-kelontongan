"""
Voice AI Handler — Handles voice notes from Telegram, processes them via
OpenRouter AI (transcription + intent classification) and executes CRUD operations.

Flow: Voice Note → Download OGG → OpenRouter Transcribe (STT)
      → OpenRouter Chat (intent parse) → Show Confirmation
      → Admin approves/corrects/cancels → Execute CRUD
"""

import logging
import os
import io
import json
import tempfile
import difflib
from datetime import datetime, date

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from openai import AsyncOpenAI

from config import (
    OPENROUTER_API_KEY, GROQ_API_KEY,
    GROQ_TRANSCRIPTION_MODEL, OPENROUTER_CHAT_MODEL
)
from auth import is_kasir
from database import SessionLocal, Product, Promotion, StoreSchedule
from promotion_service import (
    create_promotion, list_promotions, delete_promotion, format_date_indo
)
from schedule_service import create_schedule, list_schedules, delete_schedule

logger = logging.getLogger(__name__)

# =============================================================================
# API CLIENTS SETUP
# =============================================================================

openrouter_client = AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
)

groq_client = AsyncOpenAI(
    base_url="https://api.groq.com/openai/v1",
    api_key=GROQ_API_KEY,
)

def get_system_prompt():
    """Generate the system prompt dynamically with the current product catalog."""
    base_prompt = """Kamu adalah asisten AI untuk Toko Kelontong. Tugasmu adalah mendengarkan perintah suara dari admin dan mengekstrak intent (niat) serta parameter yang relevan.

Kamu HARUS membalas dalam format JSON yang valid (tanpa markdown, tanpa backtick, hanya pure JSON).

Daftar intent yang tersedia:
1. "ubah_harga" — mengubah harga produk
   Parameters: {"nama_produk": "...", "harga_baru": angka}

2. "tambah_produk" — menambah produk baru
   Parameters: {"nama_produk": "...", "kategori": "...", "subkategori": "...", "harga": angka}
   Kategori yang tersedia: "Sembako & Bahan Pokok", "Mie & Makanan Instan", "Bumbu & Bahan Dapur", "Minuman & Susu", "Camilan & Jajanan", "Perawatan Tubuh", "Kebersihan Rumah Tangga", "Kebutuhan Harian Lainnya"

3. "hapus_produk" — menghapus produk
   Parameters: {"nama_produk": "..."}

4. "tambah_promo" — membuat promosi baru
   Parameters: {"nama_produk": "...", "tipe_diskon": "percentage" atau "fixed_amount", "nilai_diskon": angka, "tanggal_mulai": "DD/MM/YYYY", "tanggal_selesai": "DD/MM/YYYY"}

5. "hapus_promo" — menghapus promosi
   Parameters: {"promo_id": angka} atau {"nama_produk": "..."}

6. "ubah_jadwal" — mengatur jadwal toko (buka/tutup)
   Parameters: {"tanggal_mulai": "DD/MM/YYYY", "tanggal_selesai": "DD/MM/YYYY", "status": "Buka" atau "Tutup", "jam_operasional": "HH:MM - HH:MM" atau null, "alasan": "..." atau null}

7. "list_produk" — menampilkan daftar produk
   Parameters: {"kategori": "..." atau null}

8. "list_promo" — menampilkan daftar promosi aktif
   Parameters: {}

9. "info" — menanyakan informasi tentang produk tertentu
   Parameters: {"nama_produk": "..."}

Jika perintah tidak jelas atau kamu tidak bisa menentukan intent-nya, gunakan:
{"intent": "unknown", "parameters": {}, "message": "penjelasan apa yang kurang jelas"}

Contoh output:
{"intent": "ubah_harga", "parameters": {"nama_produk": "Indomie Goreng Spesial", "harga_baru": 4500}}

PENTING:
- Selalu kembalikan JSON yang valid
- Untuk nama produk, jika admin menyebutkan nama spesifik, cocokkan dengan daftar produk di bawah. TAPI JIKA admin menyebutkan nama umum yang ambigu (contoh: hanya "indomie", "susu", "sabun"), JANGAN MENEBAK varian spesifiknya! Kembalikan kata umum tersebut persis seperti yang diucapkan agar sistem bisa menampilkan tombol pilihan varian.
- Untuk harga, selalu dalam rupiah (angka bulat tanpa titik/koma)
- Jangan tambahkan penjelasan di luar JSON
- Jika ada keraguan pada intent, tetap pilih yang paling sesuai daripada "unknown"

DAFTAR PRODUK SAAT INI DI DATABASE (Sebagai referensi pencocokan):
"""
    # Fetch all product names to give AI context
    db = SessionLocal()
    products = db.query(Product.item_name).all()
    db.close()
    
    product_names = [p[0] for p in products]
    if product_names:
        base_prompt += "\n".join(f"- {name}" for name in product_names)
    else:
        base_prompt += "(Belum ada produk)"
        
    return base_prompt


# =============================================================================
# AI COMMUNICATION (Groq STT + OpenRouter Chat)
# =============================================================================

async def _transcribe_audio(audio_bytes: bytes) -> str:
    """
    Step 1: Send audio bytes to Groq for speech-to-text transcription.
    Uses whisper-large-v3-turbo for super fast & free results.
    Returns the transcribed text string.
    """
    audio_file = io.BytesIO(audio_bytes)
    audio_file.name = "voice.ogg"

    transcript = await groq_client.audio.transcriptions.create(
        model=GROQ_TRANSCRIPTION_MODEL,
        file=audio_file,
    )
    return transcript.text.strip()


async def _parse_intent(text: str) -> dict:
    """
    Step 2: Send transcribed text to OpenRouter chat for intent classification.
    Uses gemini-2.5-flash for cheap & optimal JSON parsing.
    Returns a dict with 'intent' and 'parameters' keys.
    """
    system_prompt = get_system_prompt()

    response = await openrouter_client.chat.completions.create(
        model=OPENROUTER_CHAT_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text},
        ],
        temperature=0.1,  # Low temperature for consistent JSON output
    )

    raw_text = response.choices[0].message.content.strip()
    logger.info(f"OpenRouter intent response: {raw_text}")

    # Clean up response — remove markdown code fences if present
    if raw_text.startswith("```"):
        lines = raw_text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        raw_text = "\n".join(lines).strip()

    return json.loads(raw_text)


async def transcribe_and_parse(audio_bytes: bytes) -> dict:
    """
    2-step pipeline:
      1. Transcribe audio → text (via Groq Whisper API)
      2. Parse text → JSON intent (via OpenRouter Gemini 2.5 Flash Free)
    Returns a dict with 'intent' and 'parameters' keys.
    """
    try:
        # Step 1: Speech-to-Text via Groq
        transcribed_text = await _transcribe_audio(audio_bytes)
        logger.info(f"Transcribed text (Groq): {transcribed_text}")

        if not transcribed_text:
            return {
                "intent": "unknown",
                "parameters": {},
                "message": "Tidak dapat mendengar suara. Coba ulangi perintahmu."
            }

        # Step 2: Intent Classification via OpenRouter
        result = await _parse_intent(transcribed_text)
        return result

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse OpenRouter response as JSON: {e}")
        return {
            "intent": "unknown",
            "parameters": {},
            "message": "Gagal memproses respons AI. Coba ulangi perintahmu."
        }
    except Exception as e:
        logger.error(f"AI API error: {e}")
        return {
            "intent": "error",
            "parameters": {},
            "message": f"Terjadi error saat menghubungi AI: {str(e)}"
        }


# =============================================================================
# PRODUCT SEARCH HELPER (Fuzzy Match)
# =============================================================================

def find_product_by_name(name: str):
    """
    Find a product by name using case-insensitive exact matching,
    followed by difflib fuzzy matching for high accuracy with typos.
    Returns the best matching Product object or None.
    """
    if not name:
        return None
        
    db = SessionLocal()

    # Try exact match first (case-insensitive)
    product = db.query(Product).filter(
        Product.item_name.ilike(f"%{name}%")
    ).first()

    if not product:
        # Fetch all product names and do a smarter fuzzy match
        all_products = db.query(Product).all()
        all_names = {p.item_name.lower(): p for p in all_products}
        
        # Get closest matches (cutoff 0.6 = 60% similarity)
        matches = difflib.get_close_matches(name.lower(), all_names.keys(), n=1, cutoff=0.5)
        
        if matches:
            best_match_name = matches[0]
            product = all_names[best_match_name]

    db.close()
    return product


def find_products_by_name(name: str, limit=10):
    """
    Find multiple products by name using case-insensitive LIKE matching.
    Returns list of Product objects.
    """
    db = SessionLocal()
    products = db.query(Product).filter(
        Product.item_name.ilike(f"%{name}%")
    ).limit(limit).all()
    db.close()
    return products


# =============================================================================
# CRUD EXECUTION FUNCTIONS
# =============================================================================

def do_ubah_harga(params: dict) -> str:
    """Change product price."""
    nama = params.get("nama_produk", "")
    harga_baru = params.get("harga_baru")

    if not nama or not harga_baru:
        return "❌ Parameter tidak lengkap. Sebutkan nama produk dan harga baru."

    try:
        harga_baru = int(harga_baru)
    except (ValueError, TypeError):
        return "❌ Harga harus berupa angka."

    if harga_baru <= 0:
        return "❌ Harga harus lebih dari 0."

    product = find_product_by_name(nama)
    if not product:
        return f"❌ Produk '{nama}' tidak ditemukan."

    db = SessionLocal()
    p = db.query(Product).filter(Product.id == product.id).first()
    old_price = p.price
    p.price = harga_baru
    db.commit()
    db.close()

    return (
        f"✅ *Harga berhasil diubah!*\n\n"
        f"📦 Produk: *{product.item_name}*\n"
        f"💰 Harga Lama: Rp{old_price:,}\n"
        f"💰 Harga Baru: Rp{harga_baru:,}"
    )


def do_tambah_produk(params: dict) -> str:
    """Add new product."""
    nama = params.get("nama_produk", "")
    kategori = params.get("kategori", "")
    subkategori = params.get("subkategori", kategori)
    harga = params.get("harga")

    if not nama or not kategori or not harga:
        return "❌ Parameter tidak lengkap. Sebutkan nama produk, kategori, dan harga."

    try:
        harga = int(harga)
    except (ValueError, TypeError):
        return "❌ Harga harus berupa angka."

    if harga <= 0:
        return "❌ Harga harus lebih dari 0."

    # Check if product already exists
    existing = find_product_by_name(nama)
    if existing and existing.item_name.lower() == nama.lower():
        return f"❌ Produk '{nama}' sudah ada dengan harga Rp{existing.price:,}."

    db = SessionLocal()

    # Get the next ID
    max_id = db.query(Product.id).order_by(Product.id.desc()).first()
    new_id = (max_id[0] + 1) if max_id else 1

    new_product = Product(
        id=new_id,
        category=kategori,
        subcategory=subkategori,
        item_name=nama,
        price=harga,
    )
    db.add(new_product)
    db.commit()
    db.close()

    return (
        f"✅ *Produk baru berhasil ditambahkan!*\n\n"
        f"📦 Nama: *{nama}*\n"
        f"🏷️ Kategori: {kategori}\n"
        f"📂 Sub-kategori: {subkategori}\n"
        f"💰 Harga: Rp{harga:,}\n"
        f"🆔 ID: #{new_id}"
    )


def do_hapus_produk(params: dict) -> str:
    """Delete product (hard delete)."""
    nama = params.get("nama_produk", "")

    if not nama:
        return "❌ Sebutkan nama produk yang ingin dihapus."

    product = find_product_by_name(nama)
    if not product:
        return f"❌ Produk '{nama}' tidak ditemukan."

    product_name = product.item_name
    product_id = product.id

    db = SessionLocal()
    # Also remove any promotions for this product
    db.query(Promotion).filter(Promotion.product_id == product_id).update(
        {"is_active": False}
    )
    db.query(Product).filter(Product.id == product_id).delete()
    db.commit()
    db.close()

    return (
        f"✅ *Produk berhasil dihapus!*\n\n"
        f"📦 Nama: *{product_name}*\n"
        f"🆔 ID: #{product_id}"
    )


def do_tambah_promo(params: dict) -> str:
    """Create new promotion."""
    nama = params.get("nama_produk", "")
    tipe = params.get("tipe_diskon", "percentage")
    nilai = params.get("nilai_diskon")
    tgl_mulai = params.get("tanggal_mulai", "")
    tgl_selesai = params.get("tanggal_selesai", "")

    if not nama or not nilai or not tgl_mulai or not tgl_selesai:
        return "❌ Parameter tidak lengkap. Sebutkan: nama produk, tipe & nilai diskon, tanggal mulai & selesai."

    product = find_product_by_name(nama)
    if not product:
        return f"❌ Produk '{nama}' tidak ditemukan."

    try:
        nilai = int(nilai)
    except (ValueError, TypeError):
        return "❌ Nilai diskon harus berupa angka."

    try:
        start_date = datetime.strptime(tgl_mulai, "%d/%m/%Y").date()
        end_date = datetime.strptime(tgl_selesai, "%d/%m/%Y").date()
    except ValueError:
        return "❌ Format tanggal salah. Gunakan DD/MM/YYYY."

    if end_date <= start_date:
        return "❌ Tanggal selesai harus setelah tanggal mulai."

    promo_id, message = create_promotion(
        product_id=product.id,
        discount_type=tipe,
        discount_value=nilai,
        start_date=start_date,
        end_date=end_date,
        target_category=None,
    )

    if promo_id:
        if tipe == "percentage":
            disc_text = f"{nilai}%"
        else:
            disc_text = f"Rp{nilai:,}"

        return (
            f"✅ *Promosi berhasil ditambahkan!*\n\n"
            f"📦 Produk: *{product.item_name}*\n"
            f"🏷️ Diskon: {disc_text}\n"
            f"📅 Mulai: {format_date_indo(start_date)}\n"
            f"📅 Selesai: {format_date_indo(end_date)}\n"
            f"🆔 Promo ID: #{promo_id}"
        )
    else:
        return f"❌ {message}"


def do_hapus_promo(params: dict) -> str:
    """Delete promotion."""
    promo_id = params.get("promo_id")
    nama = params.get("nama_produk", "")

    if promo_id:
        try:
            promo_id = int(promo_id)
        except (ValueError, TypeError):
            return "❌ ID promo harus berupa angka."

        success, message = delete_promotion(promo_id)
        if success:
            return f"✅ *Promosi #{promo_id} berhasil dihapus!*"
        return f"❌ {message}"

    elif nama:
        # Find promo by product name
        product = find_product_by_name(nama)
        if not product:
            return f"❌ Produk '{nama}' tidak ditemukan."

        db = SessionLocal()
        promo = db.query(Promotion).filter(
            Promotion.product_id == product.id,
            Promotion.is_active == True,
        ).first()
        db.close()

        if not promo:
            return f"❌ Tidak ada promosi aktif untuk produk '{product.item_name}'."

        success, message = delete_promotion(promo.id)
        if success:
            return f"✅ *Promosi untuk {product.item_name} (#{promo.id}) berhasil dihapus!*"
        return f"❌ {message}"

    return "❌ Sebutkan ID promo atau nama produk yang promosinya ingin dihapus."


def do_ubah_jadwal(params: dict) -> str:
    """Create/update store schedule."""
    tgl_mulai = params.get("tanggal_mulai", "")
    tgl_selesai = params.get("tanggal_selesai", "")
    status = params.get("status", "Tutup")
    jam = params.get("jam_operasional")
    alasan = params.get("alasan")

    if not tgl_mulai or not tgl_selesai:
        return "❌ Parameter tidak lengkap. Sebutkan tanggal mulai dan selesai."

    try:
        start_date = datetime.strptime(tgl_mulai, "%d/%m/%Y").date()
        end_date = datetime.strptime(tgl_selesai, "%d/%m/%Y").date()
    except ValueError:
        return "❌ Format tanggal salah. Gunakan DD/MM/YYYY."

    if end_date < start_date:
        return "❌ Tanggal selesai harus setelah atau sama dengan tanggal mulai."

    sched_id, message = create_schedule(
        start_date=start_date,
        end_date=end_date,
        status=status,
        operating_hours=jam,
        reason=alasan,
    )

    status_emoji = "🟢" if status == "Buka" else "🔴"

    return (
        f"✅ *Jadwal berhasil ditambahkan!*\n\n"
        f"📅 Mulai: {format_date_indo(start_date)}\n"
        f"📅 Selesai: {format_date_indo(end_date)}\n"
        f"{status_emoji} Status: *{status}*\n"
        f"⏰ Jam: {jam or '-'}\n"
        f"📝 Alasan: {alasan or '-'}\n"
        f"🆔 ID: #{sched_id}"
    )


def do_list_produk(params: dict) -> str:
    """List products, optionally filtered by category."""
    kategori = params.get("kategori")

    db = SessionLocal()

    if kategori:
        products = db.query(Product).filter(
            Product.category.ilike(f"%{kategori}%")
        ).order_by(Product.category, Product.item_name).all()
    else:
        products = db.query(Product).order_by(
            Product.category, Product.item_name
        ).limit(30).all()

    db.close()

    if not products:
        return f"❌ Tidak ada produk ditemukan{' untuk kategori ' + kategori if kategori else ''}."

    text = f"📦 *Daftar Produk*"
    if kategori:
        text += f" — {products[0].category}"
    text += f" ({len(products)} produk)\n\n"

    current_cat = ""
    for p in products:
        if p.category != current_cat:
            current_cat = p.category
            text += f"\n*{current_cat}:*\n"
        text += f"  ▪️ {p.item_name} — Rp{p.price:,}\n"

    if not kategori and len(products) == 30:
        text += "\n_Menampilkan 30 produk pertama. Sebutkan kategori untuk filter._"

    return text


def do_list_promo(params: dict) -> str:
    """List active promotions."""
    promos = list_promotions(active_only=True)

    if not promos:
        return "📋 *Daftar Promosi*\n\n_Belum ada promosi aktif._"

    text = f"📋 *Daftar Promosi Aktif* ({len(promos)})\n\n"
    for p in promos:
        text += (
            f"*#{p['id']}* — {p['product_name']}\n"
            f"   🏷️ Diskon: {p['discount_text']}\n"
            f"   📅 {p['start_date_str']} — {p['end_date_str']}\n"
            f"   {p['status']}\n\n"
        )

    return text


def do_info_produk(params: dict) -> str:
    """Get info about a specific product."""
    nama = params.get("nama_produk", "")

    if not nama:
        return "❌ Sebutkan nama produk yang ingin dicari."

    products = find_products_by_name(nama, limit=5)

    if not products:
        return f"❌ Produk '{nama}' tidak ditemukan."

    if len(products) == 1:
        p = products[0]
        text = (
            f"📦 *Info Produk*\n\n"
            f"📝 Nama: *{p.item_name}*\n"
            f"🏷️ Kategori: {p.category}\n"
            f"📂 Sub-kategori: {p.subcategory}\n"
            f"💰 Harga: *Rp{p.price:,}*\n"
            f"🆔 ID: #{p.id}"
        )
    else:
        text = f"📦 *Hasil Pencarian '{nama}'* ({len(products)} ditemukan)\n\n"
        for p in products:
            text += f"▪️ *{p.item_name}* — Rp{p.price:,}\n   🏷️ {p.category}\n\n"

    return text


# =============================================================================
# INTENT DISPATCHER
# =============================================================================

INTENT_HANDLERS = {
    "ubah_harga": do_ubah_harga,
    "tambah_produk": do_tambah_produk,
    "hapus_produk": do_hapus_produk,
    "tambah_promo": do_tambah_promo,
    "hapus_promo": do_hapus_promo,
    "ubah_jadwal": do_ubah_jadwal,
    "list_produk": do_list_produk,
    "list_promo": do_list_promo,
    "info": do_info_produk,
}

# Intents that only READ data — no confirmation needed
READ_ONLY_INTENTS = {"list_produk", "list_promo", "info"}


def execute_intent(parsed: dict) -> str:
    """
    Execute the parsed intent from Gemini AI.
    Returns a formatted response string.
    """
    intent = parsed.get("intent", "unknown")
    params = parsed.get("parameters", {})

    handler = INTENT_HANDLERS.get(intent)

    if handler:
        try:
            return handler(params)
        except Exception as e:
            logger.error(f"Error executing intent '{intent}': {e}")
            return f"❌ Terjadi error saat mengeksekusi perintah: {str(e)}"

    # Handle unknown/error intents
    if intent == "error":
        return f"❌ {parsed.get('message', 'Terjadi error.')}"

    msg = parsed.get("message", "Coba ulangi perintahmu dengan lebih jelas.")
    return (
        f"❓ *Perintah tidak dikenali*\n\n"
        f"_{msg}_\n\n"
        f"💡 *Contoh perintah yang bisa kamu ucapkan:*\n"
        f"▪️ \"Ubah harga Indomie Goreng jadi 4000\"\n"
        f"▪️ \"Tambah produk baru Sabun Cair harga 15000 kategori Perawatan Tubuh\"\n"
        f"▪️ \"Hapus produk Beras Merah\"\n"
        f"▪️ \"Buat promo diskon 10% untuk Chitato mulai 1 Juli sampai 31 Juli\"\n"
        f"▪️ \"Hapus promo nomor 5\"\n"
        f"▪️ \"Set toko tutup tanggal 10 sampai 12 Juli\"\n"
        f"▪️ \"Tampilkan semua produk Sembako\"\n"
        f"▪️ \"Lihat promo aktif\"\n"
        f"▪️ \"Berapa harga Aqua galon?\""
    )


# =============================================================================
# CONFIRMATION MESSAGE BUILDER
# =============================================================================

INTENT_LABELS = {
    "ubah_harga": "💰 Ubah Harga Produk",
    "tambah_produk": "📦 Tambah Produk Baru",
    "hapus_produk": "🗑 Hapus Produk",
    "tambah_promo": "🏷️ Tambah Promosi",
    "hapus_promo": "🗑 Hapus Promosi",
    "ubah_jadwal": "🗓️ Atur Jadwal Toko",
}


def format_confirmation(parsed: dict) -> str:
    """
    Format a human-readable confirmation message from parsed intent.
    Shows all parameters clearly so admin can verify before executing.
    """
    intent = parsed.get("intent", "unknown")
    params = parsed.get("parameters", {})
    label = INTENT_LABELS.get(intent, intent)

    text = f"⚠️ *KONFIRMASI PERINTAH*\n\n"
    text += f"🤖 Aksi: *{label}*\n"
    text += f"━━━━━━━━━━━━━━━━━━━━\n"

    if intent == "ubah_harga":
        text += f"📦 Produk: *{params.get('nama_produk', '-')}*\n"
        harga = params.get('harga_baru', '-')
        text += f"💰 Harga Baru: *Rp{int(harga):,}*\n" if harga != '-' else f"💰 Harga Baru: -\n"

    elif intent == "tambah_produk":
        text += f"📦 Nama: *{params.get('nama_produk', '-')}*\n"
        text += f"🏷️ Kategori: {params.get('kategori', '-')}\n"
        text += f"📂 Sub-kategori: {params.get('subkategori', params.get('kategori', '-'))}\n"
        harga = params.get('harga', '-')
        text += f"💰 Harga: *Rp{int(harga):,}*\n" if harga != '-' else f"💰 Harga: -\n"

    elif intent == "hapus_produk":
        text += f"📦 Produk: *{params.get('nama_produk', '-')}*\n"
        text += f"⚠️ _Produk akan dihapus permanen dari database!_\n"

    elif intent == "tambah_promo":
        text += f"📦 Produk: *{params.get('nama_produk', '-')}*\n"
        tipe = params.get('tipe_diskon', 'percentage')
        nilai = params.get('nilai_diskon', '-')
        if tipe == 'percentage':
            text += f"🏷️ Diskon: *{nilai}%*\n"
        else:
            text += f"🏷️ Diskon: *Rp{int(nilai):,}*\n" if nilai != '-' else f"🏷️ Diskon: -\n"
        text += f"📅 Mulai: {params.get('tanggal_mulai', '-')}\n"
        text += f"📅 Selesai: {params.get('tanggal_selesai', '-')}\n"

    elif intent == "hapus_promo":
        if params.get('promo_id'):
            text += f"🆔 Promo ID: *#{params.get('promo_id')}*\n"
        if params.get('nama_produk'):
            text += f"📦 Produk: *{params.get('nama_produk')}*\n"

    elif intent == "ubah_jadwal":
        text += f"📅 Mulai: {params.get('tanggal_mulai', '-')}\n"
        text += f"📅 Selesai: {params.get('tanggal_selesai', '-')}\n"
        status = params.get('status', 'Tutup')
        emoji = "🟢" if status == "Buka" else "🔴"
        text += f"{emoji} Status: *{status}*\n"
        jam = params.get('jam_operasional')
        if jam:
            text += f"⏰ Jam: {jam}\n"
        alasan = params.get('alasan')
        if alasan:
            text += f"📝 Alasan: {alasan}\n"

    text += f"━━━━━━━━━━━━━━━━━━━━\n"
    text += f"\nApakah data di atas sudah benar?"

    return text


def build_confirmation_keyboard():
    """Build inline keyboard for confirmation step."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Konfirmasi & Jalankan", callback_data="vc_confirm")],
        [InlineKeyboardButton("✏️ Koreksi (Ketik Ulang)", callback_data="vc_correct")],
        [InlineKeyboardButton("❌ Batal", callback_data="vc_cancel")],
    ])


def check_disambiguation(name: str):
    """
    Check if the product name is exact, ambiguous, or not found.
    Returns (status, products):
      - status: "exact", "ambiguous", or "not_found"
      - products: List of matching Product objects
    """
    if not name:
        return "not_found", []
        
    db = SessionLocal()
    
    # 1. Exact match
    product = db.query(Product).filter(Product.item_name.ilike(name)).first()
    if product:
        db.close()
        return "exact", [product]
        
    # 2. Fuzzy match to find closest candidates
    all_products = db.query(Product).all()
    all_names = {p.item_name.lower(): p for p in all_products}
    matches = difflib.get_close_matches(name.lower(), all_names.keys(), n=10, cutoff=0.3)
    
    if not matches:
        # 3. Fallback to contains match if difflib finds nothing
        products = db.query(Product).filter(Product.item_name.ilike(f"%{name}%")).limit(10).all()
        db.close()
        if not products:
            return "not_found", []
        elif len(products) == 1:
            return "exact", products
        else:
            return "ambiguous", products
            
    if len(matches) == 1:
        db.close()
        return "exact", [all_names[matches[0]]]
        
    matched_products = [all_names[m] for m in matches]
    db.close()
    return "ambiguous", matched_products


async def process_parsed_intent(parsed: dict, processing_msg, context: ContextTypes.DEFAULT_TYPE):
    """
    Common handler for routing parsed intents. 
    Handles read-only, disambiguation, and confirmation steps.
    """
    intent = parsed.get("intent", "unknown")
    logger.info(f"Processing intent: {intent}, params: {parsed.get('parameters', {})}")

    # --- READ-ONLY intents: execute immediately ---
    if intent in READ_ONLY_INTENTS:
        result = execute_intent(parsed)
        await processing_msg.edit_text(
            f"🎤 *Perintah Diproses*\n🤖 Aksi: `{intent}`\n\n{result}",
            parse_mode="Markdown"
        )
        return

    # --- UNKNOWN / ERROR intents: show help ---
    if intent in ("unknown", "error"):
        result = execute_intent(parsed)
        await processing_msg.edit_text(result, parse_mode="Markdown")
        return

    # --- DATA-MODIFYING intents: DISAMBIGUATION CHECK ---
    if intent in ("ubah_harga", "hapus_produk", "tambah_promo", "hapus_promo"):
        nama_produk = parsed.get("parameters", {}).get("nama_produk")
        
        # hapus_promo can omit nama_produk if using promo_id
        if nama_produk:
            status, products = check_disambiguation(nama_produk)
            
            if status == "not_found":
                await processing_msg.edit_text(
                    f"❌ Produk dengan nama *{nama_produk}* tidak ditemukan di database.",
                    parse_mode="Markdown"
                )
                return
                
            elif status == "ambiguous":
                context.user_data["voice_pending"] = parsed
                
                buttons = []
                for p in products:
                    buttons.append([InlineKeyboardButton(p.item_name, callback_data=f"vc_pick_{p.id}")])
                buttons.append([InlineKeyboardButton("❌ Batal", callback_data="vc_cancel")])
                
                await processing_msg.edit_text(
                    f"⚠️ *Klarifikasi Produk*\n\n"
                    f"Ada beberapa produk yang cocok dengan *{nama_produk}*.\n"
                    f"Silakan pilih produk yang dimaksud:",
                    reply_markup=InlineKeyboardMarkup(buttons),
                    parse_mode="Markdown"
                )
                return
                
            elif status == "exact":
                # Update with exact name
                parsed["parameters"]["nama_produk"] = products[0].item_name

    # --- DATA-MODIFYING intents: CONFIRMATION ---
    context.user_data["voice_pending"] = parsed
    confirmation_text = format_confirmation(parsed)
    keyboard = build_confirmation_keyboard()

    await processing_msg.edit_text(
        confirmation_text,
        reply_markup=keyboard,
        parse_mode="Markdown"
    )


# =============================================================================
# TELEGRAM VOICE HANDLER (with confirmation)
# =============================================================================

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Main handler for voice messages from Telegram.
    Downloads OGG audio, sends to Gemini AI for processing.
    For data-modifying intents: shows confirmation first.
    For read-only intents: executes immediately.
    """
    user = update.effective_user

    # Role check — kasir, vendor, and developer can use voice commands
    if not is_kasir(user.id):
        await update.message.reply_text(
            "⛔ Maaf, fitur perintah suara hanya tersedia untuk staf terdaftar."
        )
        return

    # Clear any previous correction mode
    context.user_data.pop("voice_correction_mode", None)

    # Show processing indicator
    processing_msg = await update.message.reply_text(
        "🎤 Memproses pesan suara...\n⏳ Menghubungi AI untuk analisis..."
    )

    try:
        # Download the voice note
        voice = update.message.voice
        file = await context.bot.get_file(voice.file_id)

        # Download to memory (ByteArray)
        audio_bytearray = await file.download_as_bytearray()
        audio_bytes = bytes(audio_bytearray)

        logger.info(
            f"Voice note received from @{username}: "
            f"{voice.duration}s, {len(audio_bytes)} bytes"
        )

        # Send to Gemini for transcription and intent parsing
        parsed = await transcribe_and_parse(audio_bytes)
        await process_parsed_intent(parsed, processing_msg, context)

    except Exception as e:
        logger.error(f"Voice handler error: {e}")
        await processing_msg.edit_text(
            f"❌ *Error memproses pesan suara*\n\n"
            f"_{str(e)}_\n\n"
            f"Coba kirim ulang voice note-mu.",
            parse_mode="Markdown"
        )


# =============================================================================
# CALLBACK HANDLER — Confirmation buttons
# =============================================================================

async def handle_voice_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle inline keyboard button clicks for voice command confirmation.
    Callback data: vc_confirm, vc_correct, vc_cancel
    """
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "vc_confirm":
        # --- CONFIRM: Execute the pending intent ---
        pending = context.user_data.pop("voice_pending", None)

        if not pending:
            await query.edit_message_text(
                "❌ Tidak ada perintah yang menunggu konfirmasi.\n"
                "Kirim voice note baru untuk memulai."
            )
            return

        intent = pending.get("intent", "unknown")
        result = execute_intent(pending)

        await query.edit_message_text(
            f"🎤 *Perintah Suara Dieksekusi*\n"
            f"🤖 Aksi: `{intent}`\n\n"
            f"{result}",
            parse_mode="Markdown"
        )

    elif data == "vc_correct":
        # --- CORRECT: Enter text correction mode ---
        pending = context.user_data.get("voice_pending")

        if not pending:
            await query.edit_message_text(
                "❌ Tidak ada perintah yang menunggu koreksi.\n"
                "Kirim voice note baru untuk memulai."
            )
            return

        # Set correction mode flag
        context.user_data["voice_correction_mode"] = True

        intent = pending.get("intent", "unknown")
        label = INTENT_LABELS.get(intent, intent)

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Batal", callback_data="vc_cancel")],
        ])

        await query.edit_message_text(
            f"✏️ *Mode Koreksi*\n\n"
            f"Aksi saat ini: *{label}*\n\n"
            f"Silakan ketik ulang perintah yang benar.\n"
            f"Contoh:\n"
            f"_\"Ubah harga Indomie Goreng jadi 4500\"_\n"
            f"_\"Tambah produk Sabun Cair harga 15000 kategori Perawatan Tubuh\"_\n\n"
            f"Atau tekan ❌ Batal untuk membatalkan.",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )

    elif data == "vc_cancel":
        # --- CANCEL: Discard pending intent ---
        context.user_data.pop("voice_pending", None)
        context.user_data.pop("voice_correction_mode", None)

        await query.edit_message_text(
            "❌ *Perintah dibatalkan.*\n\n"
            "Kirim voice note baru kapan saja untuk memulai lagi.",
            parse_mode="Markdown"
        )

    elif data.startswith("vc_pick_"):
        # --- DISAMBIGUATION: User picked a specific product ---
        product_id = int(data.split("_")[2])
        
        db = SessionLocal()
        product = db.query(Product).filter(Product.id == product_id).first()
        db.close()
        
        if not product:
            await query.edit_message_text("❌ Produk tidak ditemukan.")
            return
            
        pending = context.user_data.get("voice_pending")
        if not pending:
            await query.edit_message_text("❌ Sesi kedaluwarsa. Silakan ulangi perintah.")
            return
            
        # Update the pending intent with the exact product name
        pending["parameters"]["nama_produk"] = product.item_name
        
        # Proceed to confirmation step
        confirmation_text = format_confirmation(pending)
        keyboard = build_confirmation_keyboard()
        
        await query.edit_message_text(
            confirmation_text,
            reply_markup=keyboard,
            parse_mode="Markdown"
        )


# =============================================================================
# TEXT CORRECTION HANDLER
# =============================================================================

async def handle_voice_text_correction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle text messages when in voice correction mode.
    Re-parses the typed text with Gemini AI and shows confirmation again.
    """
    # Only process if correction mode is active
    if not context.user_data.get("voice_correction_mode"):
        return False  # Signal that this handler didn't handle the message

    # Role check
    if not is_kasir(update.effective_user.id):
        return False

    # Clear correction mode flag
    context.user_data.pop("voice_correction_mode", None)

    text_input = update.message.text.strip()

    processing_msg = await update.message.reply_text(
        "✏️ Memproses koreksi...\n⏳ Menghubungi AI untuk analisis ulang..."
    )

    try:
        # Send text to OpenRouter for re-parsing (text only, no audio)
        parsed = await _parse_intent(text_input)
        logger.info(f"OpenRouter correction response: {parsed}")
        await process_parsed_intent(parsed, processing_msg, context)

    except json.JSONDecodeError:
        await processing_msg.edit_text(
            "❌ Gagal memproses koreksi.\n"
            "Coba ketik ulang perintahmu atau kirim voice note baru.",
        )
    except Exception as e:
        logger.error(f"Voice text correction error: {e}")
        await processing_msg.edit_text(
            f"❌ Error: {str(e)}\n"
            f"Coba kirim voice note baru.",
        )

    return True
