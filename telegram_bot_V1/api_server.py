"""
api_server.py — FastAPI Backend for POS Bot V2
================================================
Endpoints:
  POST /api/web/register-owner       — Website: register a new owner + tenant, returns token
  POST /api/web/generate-kasir-token — Owner: generate a kasir invitation token
  GET  /api/mini/dashboard           — Mini App: get dashboard data (validated via initData)
  GET  /api/mini/kasir-list          — Mini App: get kasir list for owner
  GET  /api/mini/transactions        — Mini App: get recent transactions
  POST /api/mini/generate-kasir-token — Mini App: owner generates kasir token

Run with:
    uvicorn api_server:app --reload --host 0.0.0.0 --port 8000
"""

import hashlib
import hmac
import json
import logging
import secrets
from datetime import datetime, timedelta
from urllib.parse import unquote, parse_qsl

from fastapi import FastAPI, HTTPException, Header, Request, Response, UploadFile, File, Form
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx

from database import (
    SessionLocal, BotUser, Tenant, RegistrationToken, Transaction,
    Product, TransactionItem, StockMovement, Promotion, StoreSchedule,
    QrisTransaction
)
from sqlalchemy import func, desc
from receipt_generator import generate_receipt_image
import qris_service

# ── Try to import config, fall back to env vars ───────────────────────────────
try:
    from config import API_SECRET_KEY, BOT_TOKEN, OWNER_TELEGRAM_ID
except ImportError:
    import os
    API_SECRET_KEY = os.getenv("API_SECRET_KEY", "")
    BOT_TOKEN = os.getenv("BOT_TOKEN", "")
    OWNER_TELEGRAM_ID = int(os.getenv("OWNER_TELEGRAM_ID", "0"))

logger = logging.getLogger(__name__)

app = FastAPI(
    title="POS Toko Bot API",
    description="Backend API for Telegram POS Bot V2",
    version="2.0.0",
)

# CORS — allow requests from the Mini App and website
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # tighten this in production to your domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from fastapi.responses import RedirectResponse

@app.get("/")
async def root_redirect():
    """Otomatis arahkan pengunjung root ke halaman Mini App."""
    return RedirectResponse(url="/miniapp/index.html")


# ==============================================================================
# Pydantic Schemas
# ==============================================================================

class RegisterOwnerRequest(BaseModel):
    store_name: str
    telegram_username: str   # @username without @, for display only


class GenerateKasirTokenRequest(BaseModel):
    api_secret: str          # Shared secret to protect this endpoint


class OrderItemSchema(BaseModel):
    id: int
    name: str
    price: int
    quantity: int


class CreateOrderRequest(BaseModel):
    tenant_id: int | None = None
    items: list[OrderItemSchema]
    delivery_type: str = "pickup"  # "pickup" or "delivery"
    customer_name: str
    customer_phone: str
    customer_address: str | None = None
    payment_method: str = "cod"   # "cod", "transfer", "qris"
    notes: str | None = None
    telegram_user: dict | None = None


class ProductManageRequest(BaseModel):
    item_name: str
    category: str
    subcategory: str | None = None
    price: int
    stock: int = 100
    image_url: str | None = None
    tenant_id: int | None = None


class PosCheckoutRequest(BaseModel):
    tenant_id: int | None = None
    items: list[OrderItemSchema]
    payment_method: str = "cash"  # "cash" or "qris"
    amount_paid: int | None = None
    discount: int = 0
    customer_name: str = "Pelanggan Toko (Langsung)"
    user_id: int | None = 0


class OrderStatusUpdateRequest(BaseModel):
    status: str  # "diproses", "siap_diambil", "completed", "cancelled"


# ==============================================================================
# Mini App initData Validation (Telegram spec)
# ==============================================================================

def validate_telegram_init_data(init_data: str) -> dict | None:
    """
    Validate the initData string sent by Telegram Mini App.
    Returns the parsed user dict on success, None on failure.

    Spec: https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
    """
    try:
        parsed = dict(parse_qsl(init_data, keep_blank_values=True))
        received_hash = parsed.pop("hash", None)
        if not received_hash:
            return None

        # Build check string — sorted key=value pairs, newline separated
        check_string = "\n".join(
            f"{k}={v}" for k, v in sorted(parsed.items())
        )

        # HMAC-SHA256 with key = HMAC-SHA256("WebAppData", BOT_TOKEN)
        secret_key = hmac.new(
            b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256
        ).digest()
        expected_hash = hmac.new(
            secret_key, check_string.encode(), hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(expected_hash, received_hash):
            return None

        # Check expiry (initData is valid for 24 hours)
        auth_date = int(parsed.get("auth_date", 0))
        if datetime.now().timestamp() - auth_date > 86400:
            return None

        user_json = parsed.get("user", "{}")
        return json.loads(user_json)

    except Exception as e:
        logger.error(f"initData validation error: {e}")
        return None


def get_user_from_init_data(init_data: str):
    """Parse initData, validate it, and look up the BotUser. Returns (tg_user_dict, BotUser or None)."""
    tg_user = validate_telegram_init_data(init_data)
    if not tg_user:
        raise HTTPException(status_code=401, detail="Invalid or expired Telegram initData.")

    telegram_id = tg_user.get("id")
    if not telegram_id:
        raise HTTPException(status_code=401, detail="No user ID in initData.")

    db = SessionLocal()
    user = db.query(BotUser).filter(
        BotUser.telegram_id == telegram_id,
        BotUser.is_active == True,
    ).first()
    db.close()

    return tg_user, user


# ==============================================================================
# WEB APP ENDPOINTS (called by the registration website)
# ==============================================================================

@app.post("/api/web/register-owner")
async def register_owner(req: RegisterOwnerRequest, x_api_secret: str = Header(None)):
    """
    Register a new owner via the web app.
    Creates a Tenant + RegistrationToken.
    The owner then uses this token in the Telegram bot to activate their account.
    """
    if x_api_secret != API_SECRET_KEY:
        raise HTTPException(status_code=403, detail="Invalid API secret.")

    username = req.telegram_username.lstrip("@").strip()
    store_name = req.store_name.strip()

    if not store_name:
        raise HTTPException(status_code=400, detail="store_name is required.")
    if not username:
        raise HTTPException(status_code=400, detail="telegram_username is required.")

    db = SessionLocal()

    # Check if tenant with same name already registered
    existing = db.query(Tenant).filter(Tenant.store_name == store_name).first()
    if existing:
        db.close()
        raise HTTPException(status_code=409, detail=f"Toko '{store_name}' sudah terdaftar.")

    # Create tenant (owner_id will be filled when they activate the token)
    tenant = Tenant(store_name=store_name, owner_id=0, is_active=True)
    db.add(tenant)
    db.flush()  # get tenant.id

    token_str = "POS-OWNER-" + secrets.token_hex(4).upper()
    expires = datetime.now() + timedelta(hours=48)

    new_token = RegistrationToken(
        token=token_str,
        role="owner",
        tenant_id=tenant.id,
        created_by=None,
        expires_at=expires,
    )
    db.add(new_token)
    db.commit()
    tenant_id = tenant.id
    db.close()

    logger.info(f"Owner registration token created: store='{store_name}', token={token_str}")

    return {
        "success": True,
        "token": token_str,
        "store_name": store_name,
        "expires_at": expires.isoformat(),
        "instructions": (
            f"Buka bot Telegram dan kirim pesan: /start\n"
            f"Kemudian masukkan token kamu: {token_str}"
        )
    }


# ==============================================================================
# MINI APP ENDPOINTS (called by the Telegram Mini App, validated via initData)
# ==============================================================================

@app.get("/api/mini/dashboard")
async def mini_dashboard(request: Request):
    """
    Dashboard data for the Mini App.
    Owners get full store summary; kasir get their own summary.
    """
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    tg_user, bot_user = get_user_from_init_data(init_data)

    if not bot_user:
        raise HTTPException(status_code=403, detail="User belum terdaftar. Aktivasi token dulu di bot.")

    db = SessionLocal()
    tenant_id = bot_user.tenant_id

    # Get today's date range
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)

    # Base query
    base_q = db.query(Transaction).filter(
        Transaction.status == "completed",
        Transaction.created_at >= today_start,
        Transaction.created_at < today_end,
    )

    if bot_user.role == "owner" and tenant_id:
        base_q = base_q.filter(Transaction.tenant_id == tenant_id)
    elif bot_user.role == "kasir":
        # Kasir can only see their own transactions
        base_q = base_q.filter(Transaction.user_id == bot_user.telegram_id)

    txns = base_q.all()
    total_transactions = len(txns)
    total_revenue = sum(t.grand_total or t.total_amount or 0 for t in txns)
    total_discount = sum(t.total_discount or 0 for t in txns)

    # Payment breakdown
    payment_breakdown = {}
    for t in txns:
        method = t.payment_method or "Lainnya"
        if method not in payment_breakdown:
            payment_breakdown[method] = {"count": 0, "amount": 0}
        payment_breakdown[method]["count"] += 1
        payment_breakdown[method]["amount"] += t.grand_total or t.total_amount or 0

    # Monthly revenue (owner only)
    month_revenue = None
    if bot_user.role == "owner" and tenant_id:
        month_start = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        month_txns = db.query(Transaction).filter(
            Transaction.status == "completed",
            Transaction.tenant_id == tenant_id,
            Transaction.created_at >= month_start,
        ).all()
        month_revenue = sum(t.grand_total or t.total_amount or 0 for t in month_txns)

    # Store name
    store_name = None
    if tenant_id:
        tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
        store_name = tenant.store_name if tenant else None

    # Stock overview (total products, low stock count) - tenant-scoped
    total_products = db.query(Product).filter(Product.tenant_id == tenant_id).count()
    low_stock = db.query(Product).filter(
        (Product.stock <= Product.min_stock) | (Product.stock == 0),
        Product.tenant_id == tenant_id
    ).count()

    db.close()

    return {
        "role": bot_user.role,
        "store_name": store_name,
        "full_name": bot_user.full_name or tg_user.get("first_name", ""),
        "today": {
            "total_transactions": total_transactions,
            "total_revenue": total_revenue,
            "total_discount": total_discount,
            "payment_breakdown": payment_breakdown,
        },
        "month_revenue": month_revenue,
        "stock": {
            "total_products": total_products,
            "low_stock": low_stock
        }
    }


@app.get("/api/mini/stock-summary")
async def mini_stock_summary(request: Request):
    """Return total stock per category."""
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    tg_user, bot_user = get_user_from_init_data(init_data)
    if not bot_user:
        raise HTTPException(status_code=403, detail="User belum terdaftar.")

    db = SessionLocal()
    tenant_id = bot_user.tenant_id
    summary = db.query(Product.category, func.sum(Product.stock)).filter(
        Product.tenant_id == tenant_id
    ).group_by(Product.category).all()
    db.close()

    return [{"category": s[0], "total_stock": int(s[1] or 0)} for s in summary]


@app.get("/api/mini/top-products")
async def mini_top_products(request: Request):
    """Return top 5 best-selling products in the last 7 days."""
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    tg_user, bot_user = get_user_from_init_data(init_data)
    if not bot_user:
        raise HTTPException(status_code=403, detail="User belum terdaftar.")

    db = SessionLocal()
    seven_days_ago = datetime.now() - timedelta(days=7)
    
    top_items = (
        db.query(TransactionItem.product_name, func.sum(TransactionItem.quantity).label("qty"))
        .join(Transaction, Transaction.id == TransactionItem.transaction_id)
        .filter(Transaction.status == "completed", Transaction.created_at >= seven_days_ago)
        .group_by(TransactionItem.product_name)
        .order_by(desc("qty"))
        .limit(5)
        .all()
    )
    db.close()

    return [{"product_name": t[0], "quantity": int(t[1])} for t in top_items]


@app.get("/api/mini/consignment")
async def mini_consignment(request: Request):
    """Return list of consignment products and their stock."""
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    tg_user, bot_user = get_user_from_init_data(init_data)
    if not bot_user:
        raise HTTPException(status_code=403, detail="User belum terdaftar.")

    db = SessionLocal()
    tenant_id = bot_user.tenant_id
    items = db.query(Product).filter(
        Product.is_consignment == True,
        Product.tenant_id == tenant_id
    ).all()
    db.close()

    return [{
        "id": p.id,
        "name": p.item_name,
        "supplier": p.consignment_supplier or "-",
        "stock": p.stock,
        "price": p.price
    } for p in items]


@app.get("/api/mini/kasir-list")
async def mini_kasir_list(request: Request):
    """Return list of active kasir for the owner's tenant."""
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    tg_user, bot_user = get_user_from_init_data(init_data)

    if not bot_user or bot_user.role != "owner":
        raise HTTPException(status_code=403, detail="Hanya owner yang bisa melihat daftar kasir.")

    db = SessionLocal()
    kasirs = db.query(BotUser).filter(
        BotUser.tenant_id == bot_user.tenant_id,
        BotUser.role == "kasir",
        BotUser.is_active == True,
    ).all()
    db.close()

    return {
        "kasir_list": [
            {
                "telegram_id": k.telegram_id,
                "username": k.telegram_username,
                "full_name": k.full_name,
                "joined_at": k.token_validated_at.isoformat() if k.token_validated_at else None,
            }
            for k in kasirs
        ]
    }


@app.post("/api/mini/generate-kasir-token")
async def mini_generate_kasir_token(request: Request):
    """Owner generates a new kasir invitation token."""
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    tg_user, bot_user = get_user_from_init_data(init_data)

    if not bot_user or bot_user.role != "owner":
        raise HTTPException(status_code=403, detail="Hanya owner yang bisa generate token kasir.")

    db = SessionLocal()
    token_str = "POS-KASIR-" + secrets.token_hex(4).upper()
    expires = datetime.now() + timedelta(hours=48)

    new_token = RegistrationToken(
        token=token_str,
        role="kasir",
        tenant_id=bot_user.tenant_id,
        created_by=bot_user.telegram_id,
        expires_at=expires,
    )
    db.add(new_token)
    db.commit()
    db.close()

    logger.info(f"Kasir token generated via MiniApp by owner={bot_user.telegram_id}: {token_str}")

    return {
        "success": True,
        "token": token_str,
        "expires_at": expires.isoformat(),
        "instructions": f"Bagikan token ini ke kasir kamu: {token_str}\n(Berlaku 48 jam)"
    }


@app.get("/api/mini/transactions")
async def mini_transactions(request: Request, limit: int = 20, offset: int = 0):
    """Recent transactions for the Mini App."""
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    tg_user, bot_user = get_user_from_init_data(init_data)

    if not bot_user:
        raise HTTPException(status_code=403, detail="User belum terdaftar.")

    db = SessionLocal()
    q = db.query(Transaction).filter(Transaction.status == "completed")

    if bot_user.role == "owner" and bot_user.tenant_id:
        q = q.filter(Transaction.tenant_id == bot_user.tenant_id)
    else:
        q = q.filter(Transaction.user_id == bot_user.telegram_id)

    total = q.count()
    txns = q.order_by(desc(Transaction.created_at)).offset(offset).limit(limit).all()
    db.close()

    return {
        "total": total,
        "transactions": [
            {
                "id": t.id,
                "invoice_no": t.invoice_no or f"INV-{t.id:06d}",
                "grand_total": t.grand_total or t.total_amount or 0,
                "payment_method": t.payment_method,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
            for t in txns
        ]
    }


@app.delete("/api/mini/kasir/{telegram_id}")
async def mini_deactivate_kasir(telegram_id: int, request: Request):
    """Owner deactivates a kasir from their tenant."""
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    tg_user, bot_user = get_user_from_init_data(init_data)

    if not bot_user or bot_user.role != "owner":
        raise HTTPException(status_code=403, detail="Hanya owner yang bisa nonaktifkan kasir.")

    db = SessionLocal()
    kasir = db.query(BotUser).filter(
        BotUser.telegram_id == telegram_id,
        BotUser.tenant_id == bot_user.tenant_id,
        BotUser.role == "kasir",
    ).first()

    if not kasir:
        db.close()
        raise HTTPException(status_code=404, detail="Kasir tidak ditemukan di toko kamu.")

    kasir.is_active = False
    db.commit()
    db.close()

    logger.info(f"Kasir {telegram_id} deactivated by owner={bot_user.telegram_id}")
    return {"success": True, "message": "Kasir berhasil dinonaktifkan."}


@app.get("/health")
async def health():
    return {"status": "ok", "timestamp": datetime.now().isoformat()}


# ==============================================================================
# STOREFRONT MINI APP ENDPOINTS (Customer E-Commerce Web App)
# ==============================================================================

async def _send_order_notifications(
    trx_no: str,
    req: CreateOrderRequest,
    grand_total: int,
    store_name: str,
    tenant_owner_id: int | None = None
):
    """Send Telegram notifications to customer and store owner upon order creation."""
    if not BOT_TOKEN:
        return

    delivery_label = "🏪 Ambil Mandiri di Toko (Pickup)"
    payment_label = {
        "cod": "💵 Bayar saat Ambil (Tunai/COD)",
        "transfer": "🏦 Transfer Bank",
        "qris": "📱 QRIS"
    }.get(req.payment_method.lower(), req.payment_method.upper())

    item_lines = []
    for it in req.items:
        item_lines.append(f"▪️ {it.name} x{it.quantity} — Rp{it.price * it.quantity:,}")
    items_text = "\n".join(item_lines)

    # 1. Notify Customer (if telegram user id exists)
    tg_user = req.telegram_user or {}
    customer_tg_id = tg_user.get("id")
    if customer_tg_id:
        cust_msg = (
            f"🎉 *PESANAN BERHASIL DIBUAT!*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🧾 No. Invoice: *{trx_no}*\n"
            f"🏪 Toko: *{store_name}*\n"
            f"📦 Pengiriman: *{delivery_label}*\n"
            f"💳 Pembayaran: *{payment_label}*\n\n"
            f"📋 *Rincian Pesanan:*\n{items_text}\n\n"
            f"💰 *Total Pembayaran: Rp{grand_total:,}*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
        )
        if req.delivery_type == "delivery" and req.customer_address:
            cust_msg += f"📍 *Alamat Antar:* {req.customer_address}\n"
        if req.notes:
            cust_msg += f"📝 *Catatan:* {req.notes}\n"
        cust_msg += "\n_Terima kasih telah berbelanja! Pesanan Anda segera disiapkan._"

        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                await client.post(
                    f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                    json={"chat_id": customer_tg_id, "text": cust_msg, "parse_mode": "Markdown"}
                )
            except Exception as e:
                logger.error(f"Failed to send customer notification: {e}")

    # 2. Notify Store Owner / Admin
    recipients = set()
    if tenant_owner_id and tenant_owner_id > 0:
        recipients.add(tenant_owner_id)
    if OWNER_TELEGRAM_ID and OWNER_TELEGRAM_ID > 0:
        recipients.add(OWNER_TELEGRAM_ID)

    admin_msg = (
        f"🚨 *PESANAN BARU DARI MINI APP!*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🧾 Invoice: *{trx_no}*\n"
        f"👤 Pemesan: *{req.customer_name}* ({req.customer_phone})\n"
        f"📦 Pengiriman: *{delivery_label}*\n"
        f"💳 Pembayaran: *{payment_label}*\n\n"
        f"📋 *Item Dipesan:*\n{items_text}\n\n"
        f"💵 *Total: Rp{grand_total:,}*\n"
    )
    if req.delivery_type == "delivery" and req.customer_address:
        admin_msg += f"📍 *Alamat:* {req.customer_address}\n"
    if req.notes:
        admin_msg += f"📝 *Catatan:* {req.notes}\n"
    admin_msg += f"━━━━━━━━━━━━━━━━━━━━\n_Segera cek dan proses pesanan ini!_"

    async with httpx.AsyncClient(timeout=10.0) as client:
        for chat_id in recipients:
            try:
                await client.post(
                    f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                    json={"chat_id": chat_id, "text": admin_msg, "parse_mode": "Markdown"}
                )
            except Exception as e:
                logger.error(f"Failed to send admin notification to {chat_id}: {e}")


@app.get("/api/mini/store-info")
async def mini_store_info(tenant_id: int | None = None):
    """Store operational details and status for the customer Mini App."""
    db = SessionLocal()
    tenant = None
    if tenant_id:
        tenant = db.query(Tenant).filter(Tenant.id == tenant_id, Tenant.is_active == True).first()
    if not tenant:
        # Default to first active tenant with products or fallback
        first_with_prod = db.query(Product.tenant_id).filter(Product.tenant_id != None).first()
        preferred_tid = first_with_prod[0] if first_with_prod else 1
        tenant = db.query(Tenant).filter(Tenant.id == preferred_tid).first()
        if not tenant:
            tenant = db.query(Tenant).filter(Tenant.is_active == True).first()

    tid = tenant.id if tenant else 1
    store_name = tenant.store_name if tenant else "Toko Ciamis"

    # Operational hours & status check from StoreSchedule
    today = datetime.now().date()
    schedule_query = db.query(StoreSchedule).filter(
        StoreSchedule.is_active == True,
        StoreSchedule.start_date <= today,
        StoreSchedule.end_date >= today
    )
    if tenant:
        schedule_query = schedule_query.filter(StoreSchedule.tenant_id == tid)
    sched = schedule_query.order_by(StoreSchedule.id.desc()).first()

    status = "Buka"
    operating_hours = "07:00 - 22:00"
    reason = "Buka Setiap Hari"
    if sched:
        status = sched.status
        operating_hours = sched.operating_hours or "08:00 - 21:00"
        reason = sched.reason or ""

    total_products = db.query(Product).filter(
        (Product.tenant_id == tid) | (Product.tenant_id == None)
    ).count()

    qris_img = tenant.qris_image_url if tenant else None

    db.close()

    return {
        "tenant_id": tid,
        "store_name": store_name,
        "status": status,
        "operating_hours": operating_hours,
        "reason": reason,
        "total_products": total_products,
        "whatsapp": "628123456789",
        "qris_image_url": qris_img
    }


class StoreQrisRequest(BaseModel):
    tenant_id: int | None = 1
    qris_image_url: str | None = None


@app.post("/api/mini/store-qris")
async def mini_set_store_qris(req: StoreQrisRequest):
    """Menyimpan atau mengubah foto QRIS toko milik tenant."""
    db = SessionLocal()
    tid = req.tenant_id or 1
    tenant = db.query(Tenant).filter(Tenant.id == tid).first()
    if not tenant:
        # Fallback first tenant
        tenant = db.query(Tenant).first()
    if not tenant:
        db.close()
        raise HTTPException(status_code=404, detail="Data tenant toko tidak ditemukan.")

    tenant.qris_image_url = req.qris_image_url
    db.commit()
    db.refresh(tenant)
    saved_url = tenant.qris_image_url
    db.close()

    return {
        "success": True,
        "message": "Foto QRIS toko berhasil disimpan!",
        "qris_image_url": saved_url
    }


class StoreScheduleRequest(BaseModel):
    tenant_id: int | None = 1
    status: str  # "Buka" or "Tutup"
    operating_hours: str | None = "24 Jam"
    reason: str | None = None
    days_duration: int | None = 1


@app.post("/api/mini/store-schedule")
async def mini_set_store_schedule(req: StoreScheduleRequest):
    """Atur status buka/tutup dan jam operasional toko (misal tutup saat lebaran / penjaga sakit)."""
    db = SessionLocal()
    tid = req.tenant_id or 1
    today = datetime.now().date()
    end = today + timedelta(days=max(1, req.days_duration or 1))

    # Nonaktifkan jadwal lama yang aktif untuk tenant ini
    db.query(StoreSchedule).filter(
        StoreSchedule.tenant_id == tid,
        StoreSchedule.is_active == True
    ).update({"is_active": False})

    new_sched = StoreSchedule(
        tenant_id=tid,
        start_date=today,
        end_date=end,
        status=req.status,
        operating_hours=req.operating_hours or ("24 Jam" if req.status == "Buka" else "TUTUP"),
        reason=req.reason or ("Buka 24 Jam" if req.status == "Buka" else "Toko Sedang Tutup Sementara"),
        is_active=True
    )
    db.add(new_sched)
    db.commit()
    db.refresh(new_sched)

    out_hours = new_sched.operating_hours
    out_reason = new_sched.reason
    db.close()

    return {
        "success": True,
        "message": f"Status toko berhasil diubah menjadi: {req.status}",
        "status": req.status,
        "operating_hours": out_hours,
        "reason": out_reason
    }


@app.get("/api/mini/catalog")
async def mini_catalog(tenant_id: int | None = None, category: str | None = None, q: str | None = None):
    """Catalog products and category list with active promo calculation."""
    db = SessionLocal()
    tid = tenant_id

    # Fallback to tenant with products if specified has none
    if tid:
        has_items = db.query(Product).filter(Product.tenant_id == tid).first()
        if not has_items:
            first_with_prod = db.query(Product.tenant_id).filter(Product.tenant_id != None).first()
            tid = first_with_prod[0] if first_with_prod else None
    else:
        first_with_prod = db.query(Product.tenant_id).filter(Product.tenant_id != None).first()
        tid = first_with_prod[0] if first_with_prod else None

    # Base filter for tenant
    base_cond = (Product.tenant_id == tid) if tid is not None else (Product.tenant_id == None)

    # Categories
    cat_query = db.query(Product.category).distinct().filter(base_cond)
    categories = [c[0] for c in cat_query.all() if c[0]]

    # Products
    prod_query = db.query(Product).filter(base_cond)
    if category and category != "Semua":
        prod_query = prod_query.filter(Product.category == category)
    if q and q.strip():
        search_term = f"%{q.strip()}%"
        prod_query = prod_query.filter(
            (Product.item_name.ilike(search_term)) | (Product.subcategory.ilike(search_term))
        )

    products = prod_query.order_by(Product.category, Product.item_name).all()

    # Active Promotions
    today = datetime.now().date()
    promos = db.query(Promotion).filter(
        Promotion.is_active == True,
        Promotion.start_date <= today,
        Promotion.end_date >= today
    ).all()
    promo_map = {p.product_id: p for p in promos}

    items = []
    for p in products:
        promo = promo_map.get(p.id)
        discount_amount = 0
        discount_label = ""
        discount_price = p.price

        if promo:
            if promo.discount_type == "percentage":
                discount_amount = int(p.price * promo.discount_value / 100)
                discount_label = f"-{promo.discount_value}%"
            else:
                discount_amount = min(p.price, promo.discount_value)
                discount_label = f"-Rp{promo.discount_value:,}"
            discount_price = max(0, p.price - discount_amount)

        items.append({
            "id": p.id,
            "item_name": p.item_name,
            "category": p.category,
            "subcategory": p.subcategory,
            "price": p.price,
            "stock": p.stock,
            "image_url": p.image_url,
            "is_consignment": p.is_consignment,
            "has_promo": bool(promo),
            "discount_label": discount_label,
            "discount_price": discount_price if promo else p.price,
        })

    db.close()
    return {
        "tenant_id": tid,
        "categories": categories,
        "products": items
    }


@app.post("/api/mini/order")
async def mini_create_order(req: CreateOrderRequest):
    """Receive orders from the Telegram Mini App."""
    if not req.items:
        raise HTTPException(status_code=400, detail="Keranjang belanja kosong.")

    db = SessionLocal()
    tenant_id = req.tenant_id or 1
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    store_name = tenant.store_name if tenant else "Toko Kelontong"
    tenant_owner_id = tenant.owner_id if tenant else None

    # Calculate totals
    subtotal = sum(it.price * it.quantity for it in req.items)
    grand_total = subtotal

    tg_user = req.telegram_user or {}
    user_id = tg_user.get("id") or 0

    now = datetime.now()
    delivery_str = "Ambil Mandiri"
    payment_str = req.payment_method.upper()
    is_qris = req.payment_method.lower() == "qris"
    initial_status = "pending" if is_qris else "diproses"

    new_trx = Transaction(
        user_id=user_id,
        tenant_id=tenant_id,
        payment_method=f"{payment_str} ({delivery_str})",
        subtotal=subtotal,
        total_discount=0,
        grand_total=grand_total,
        status=initial_status,
        created_at=now
    )
    db.add(new_trx)
    db.commit()
    db.refresh(new_trx)

    trx_no = f"INV-{new_trx.id:06d}"
    new_trx.invoice_no = trx_no

    # Insert items and deduct stock
    for it in req.items:
        item_subtotal = it.price * it.quantity
        trx_item = TransactionItem(
            transaction_id=new_trx.id,
            product_id=it.id,
            product_name=it.name,
            unit_price=it.price,
            quantity=it.quantity,
            discount_type=None,
            discount_value=0,
            discount_amount=0,
            subtotal=item_subtotal
        )
        db.add(trx_item)

        prod = db.query(Product).filter(Product.id == it.id).first()
        if prod:
            prod.stock = max(0, prod.stock - it.quantity)
            movement = StockMovement(
                product_id=it.id,
                tenant_id=tenant_id,
                movement_type="out",
                quantity=-it.quantity,
                reference=trx_no,
                notes=f"Pesanan Mini App ({req.delivery_type})",
                created_by=user_id
            )
            db.add(movement)

    db.commit()

    # Integrasi KlikQRIS Sandbox jika metode bayar adalah QRIS
    qris_info = None
    if is_qris:
        order_id = f"Q-{new_trx.id:05d}-{secrets.token_hex(2).upper()}"
        try:
            qris_res = await qris_service.create_qris_transaction(
                order_id=order_id,
                amount=grand_total,
                keterangan=f"Pesanan {trx_no} - {req.customer_name}"
            )
            qris_trx = QrisTransaction(
                order_id=order_id,
                invoice_no=trx_no,
                tenant_id=tenant_id,
                amount=int(qris_res["amount"]),
                amount_uniq=int(qris_res["amount_uniq"]),
                total_amount=int(qris_res["total_amount"]),
                status=qris_res["status"],
                signature=qris_res["signature"],
                qris_url=qris_res["qris_url"],
                qris_image=qris_res["qris_image"],
                expired_at=qris_res["expired_at"],
                keterangan=f"KlikQRIS Sandbox {trx_no}"
            )
            db.add(qris_trx)
            db.commit()

            qris_info = {
                "order_id": order_id,
                "amount": qris_res["amount"],
                "amount_uniq": qris_res["amount_uniq"],
                "total_amount": qris_res["total_amount"],
                "qris_image": qris_res["qris_image"],
                "qris_url": qris_res["qris_url"],
                "expired_at": qris_res["expired_at"],
                "signature": qris_res["signature"]
            }
        except Exception as e:
            logger.error(f"Error initiating KlikQRIS transaction: {e}")

    db.close()

    # Send notifications in background
    try:
        await _send_order_notifications(
            trx_no=trx_no,
            req=req,
            grand_total=grand_total,
            store_name=store_name,
            tenant_owner_id=tenant_owner_id
        )
    except Exception as e:
        logger.error(f"Error sending order notifications: {e}")

    return {
        "success": True,
        "invoice_no": trx_no,
        "grand_total": grand_total,
        "is_qris": is_qris,
        "qris": qris_info,
        "receipt_url": f"/api/receipt/{trx_no}",
        "message": "Pesanan Anda berhasil dibuat dan siap diproses!"
    }


# ==============================================================================
# DIGITAL THERMAL RECEIPT ENDPOINT
# ==============================================================================

@app.get("/api/receipt/{invoice_no}")
async def get_receipt_image(invoice_no: str):
    """Generate and return thermal receipt image (PNG) for an invoice."""
    db = SessionLocal()
    trx = db.query(Transaction).filter(Transaction.invoice_no == invoice_no).first()
    if not trx:
        db.close()
        raise HTTPException(status_code=404, detail="Invoice tidak ditemukan.")

    items = db.query(TransactionItem).filter(TransactionItem.transaction_id == trx.id).all()
    cart_items = [
        (it.product_id, it.product_name, it.unit_price, it.quantity)
        for it in items
    ]

    tenant = db.query(Tenant).filter(Tenant.id == trx.tenant_id).first()
    store_name = tenant.store_name if tenant else "TOKO KELONTONG"

    # Get active promotion for recommendation section if available
    today = datetime.now().date()
    promo = db.query(Promotion).filter(
        Promotion.is_active == True,
        Promotion.start_date <= today,
        Promotion.end_date >= today
    ).first()

    recommendations = []
    if promo:
        rec_prod = db.query(Product).filter(Product.id == promo.product_id).first()
        if rec_prod:
            disc_text = f"Diskon {promo.discount_value}%" if promo.discount_type == "percentage" else f"Diskon Rp{promo.discount_value:,}"
            recommendations.append({
                "product_name": rec_prod.item_name,
                "discount_text": disc_text,
                "end_date_str": promo.end_date.strftime("%d %B %Y")
            })

    date_str = trx.created_at.strftime("%d %B %Y %H:%M:%S") if trx.created_at else datetime.now().strftime("%d %B %Y %H:%M:%S")

    img_io = generate_receipt_image(
        trx_no=trx.invoice_no or invoice_no,
        date_str=date_str,
        cart_items=cart_items,
        total=trx.subtotal or trx.grand_total or 0,
        payment_method=trx.payment_method or "TUNAI",
        total_discount=trx.total_discount or 0,
        grand_total=trx.grand_total or trx.subtotal or 0,
        recommendations=recommendations,
        whatsapp_number="628123456789",
        store_name=store_name
    )
    db.close()

    return Response(content=img_io.getvalue(), media_type="image/png")


# ==============================================================================
# KLIKQRIS SANDBOX API ENDPOINTS & WEBHOOK
# ==============================================================================

@app.post("/api/qris/create")
async def create_qris_manual(req: dict):
    """Endpoint untuk membuat transaksi QRIS Sandbox KlikQRIS manual/dinamis."""
    order_id = req.get("order_id") or f"MANUAL-{secrets.token_hex(4).upper()}"
    amount = int(req.get("amount", 10000))
    keterangan = req.get("keterangan", "Pembayaran Toko")
    invoice_no = req.get("invoice_no")

    res = await qris_service.create_qris_transaction(order_id, amount, keterangan)

    db = SessionLocal()
    qris_trx = QrisTransaction(
        order_id=order_id,
        invoice_no=invoice_no,
        amount=int(res["amount"]),
        amount_uniq=int(res["amount_uniq"]),
        total_amount=int(res["total_amount"]),
        status=res["status"],
        signature=res["signature"],
        qris_url=res["qris_url"],
        qris_image=res["qris_image"],
        expired_at=res["expired_at"],
        keterangan=keterangan
    )
    db.add(qris_trx)
    db.commit()
    db.close()

    return res


@app.get("/api/qris/status/{order_id}")
async def check_qris_status_endpoint(order_id: str):
    """Polling status transaksi QRIS ke KlikQRIS Sandbox dan update database."""
    res = await qris_service.get_qris_status(order_id)

    if res.get("success"):
        status = res.get("status", "").upper()
        db = SessionLocal()
        qris_trx = db.query(QrisTransaction).filter(QrisTransaction.order_id == order_id).first()
        if qris_trx:
            qris_trx.status = status
            if status in ["SUCCESS", "PAID"]:
                qris_trx.paid_at = res.get("paid_at") or datetime.now().isoformat()
                # Update status transaksi utama menjadi completed jika ada invoice
                if qris_trx.invoice_no:
                    trx = db.query(Transaction).filter(Transaction.invoice_no == qris_trx.invoice_no).first()
                    if trx:
                        trx.status = "completed"
            db.commit()
        db.close()

    return res


@app.post("/api/qris/webhook")
async def klikqris_webhook(request: Request):
    """
    Webhook penerima notifikasi otomatis dari KlikQRIS Sandbox saat pembayaran dieksekusi.
    Wajib membalas HTTP 200 OK dan bersifat idempotent.
    """
    try:
        payload = await request.json()
    except Exception:
        payload = {}

    qris_service.log_webhook_payload(payload)
    order_id = payload.get("order_id")
    incoming_status = (payload.get("status") or "").upper()
    incoming_sig = payload.get("signature")

    logger.info(f"Received KlikQRIS webhook: order_id={order_id}, status={incoming_status}")

    if not order_id:
        return {"status": True, "message": "Received with empty order_id"}

    db = SessionLocal()
    qris_trx = db.query(QrisTransaction).filter(QrisTransaction.order_id == order_id).first()

    # Idempotency check: jika sudah berstatus PAID / SUCCESS, abaikan
    if qris_trx and qris_trx.status in ["PAID", "SUCCESS"]:
        db.close()
        return {"status": True, "message": "Transaction already paid/processed"}

    if qris_trx:
        qris_trx.status = "PAID"
        qris_trx.paid_at = payload.get("payment_date") or datetime.now().isoformat()

        # Update status pesanan / transaksi utama
        if qris_trx.invoice_no:
            trx = db.query(Transaction).filter(Transaction.invoice_no == qris_trx.invoice_no).first()
            if trx:
                trx.status = "completed"
                # Notifikasi Telegram pembayaran lunas
                if BOT_TOKEN and trx.user_id:
                    try:
                        async with httpx.AsyncClient(timeout=5.0) as client:
                            await client.post(
                                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                                json={
                                    "chat_id": trx.user_id,
                                    "text": f"✅ *PEMBAYARAN QRIS TERVERIFIKASI!*\n\nPesanan `{trx.invoice_no}` sebesar *Rp{trx.grand_total:,}* telah berhasil dibayar.\nSilakan datang ke toko untuk mengambil pesanan Anda.",
                                    "parse_mode": "Markdown"
                                }
                            )
                    except Exception as e:
                        logger.error(f"Failed to notify user about paid webhook: {e}")

        db.commit()

    db.close()
    return {"status": True, "message": "Webhook processed successfully"}


# ==============================================================================
# IN-STORE POS DIRECT CHECKOUT (Khusus Kasir di Toko)
# ==============================================================================

@app.post("/api/pos/checkout")
async def pos_direct_checkout(req: PosCheckoutRequest):
    """Kasir melakukan transaksi penjualan langsung di toko secara cepat."""
    if not req.items:
        raise HTTPException(status_code=400, detail="Keranjang belanja kosong.")

    db = SessionLocal()
    tenant_id = req.tenant_id or 1
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    store_name = tenant.store_name if tenant else "Toko Ciamis"

    subtotal = sum(it.price * it.quantity for it in req.items)
    discount = req.discount or 0
    grand_total = max(0, subtotal - discount)
    now = datetime.now()

    method_lower = req.payment_method.lower()
    is_qris = method_lower == "qris"
    is_photo_qris = method_lower in ["photo", "qris_foto", "qris_toko"]

    if is_qris:
        pay_label = "QRIS Sandbox"
        trx_status = "pending"
    elif is_photo_qris:
        pay_label = "QRIS Toko (Fisik)"
        trx_status = "completed"
    else:
        pay_label = "TUNAI (Kasir Toko)"
        trx_status = "completed"

    new_trx = Transaction(
        user_id=req.user_id or 0,
        tenant_id=tenant_id,
        payment_method=pay_label,
        subtotal=subtotal,
        total_discount=discount,
        grand_total=grand_total,
        status=trx_status,
        created_at=now
    )
    db.add(new_trx)
    db.commit()
    db.refresh(new_trx)

    trx_no = f"INV-{new_trx.id:06d}"
    new_trx.invoice_no = trx_no

    # Deduct stock & save transaction items
    for it in req.items:
        trx_item = TransactionItem(
            transaction_id=new_trx.id,
            product_id=it.id,
            product_name=it.name,
            unit_price=it.price,
            quantity=it.quantity,
            discount_type=None,
            discount_value=0,
            discount_amount=0,
            subtotal=it.price * it.quantity
        )
        db.add(trx_item)

        prod = db.query(Product).filter(Product.id == it.id).first()
        if prod:
            prod.stock = max(0, prod.stock - it.quantity)
            movement = StockMovement(
                product_id=it.id,
                tenant_id=tenant_id,
                movement_type="out",
                quantity=-it.quantity,
                reference=trx_no,
                notes="Penjualan Langsung Kasir POS",
                created_by=req.user_id or 0
            )
            db.add(movement)

    db.commit()

    qris_data = None
    if is_qris:
        order_id = f"POS-{new_trx.id:05d}-{secrets.token_hex(2).upper()}"
        try:
            qris_res = await qris_service.create_qris_transaction(
                order_id=order_id,
                amount=grand_total,
                keterangan=f"Kasir POS {trx_no}"
            )
            qris_trx = QrisTransaction(
                order_id=order_id,
                invoice_no=trx_no,
                tenant_id=tenant_id,
                amount=int(qris_res["amount"]),
                amount_uniq=int(qris_res["amount_uniq"]),
                total_amount=int(qris_res["total_amount"]),
                status=qris_res["status"],
                signature=qris_res["signature"],
                qris_url=qris_res["qris_url"],
                qris_image=qris_res["qris_image"],
                expired_at=qris_res["expired_at"],
                keterangan=f"Kasir POS {trx_no}"
            )
            db.add(qris_trx)
            db.commit()
            qris_data = qris_res
        except Exception as e:
            logger.error(f"POS KlikQRIS error: {e}")

    db.close()

    change_amount = max(0, (req.amount_paid or grand_total) - grand_total) if not is_qris else 0

    return {
        "success": True,
        "invoice_no": trx_no,
        "subtotal": subtotal,
        "grand_total": grand_total,
        "amount_paid": req.amount_paid or grand_total,
        "change": change_amount,
        "is_qris": is_qris,
        "qris": qris_data,
        "receipt_url": f"/api/receipt/{trx_no}",
        "message": "Transaksi Kasir POS berhasil dicatat!"
    }


@app.post("/api/pos/transactions/{invoice_no}/void")
async def pos_void_transaction(invoice_no: str):
    """Membatalkan/meretur transaksi kasir untuk mengembalikan stok (mengatasi salah pencet kasir)."""
    db = SessionLocal()
    trx = db.query(Transaction).filter(Transaction.invoice_no == invoice_no).first()
    if not trx:
        db.close()
        raise HTTPException(status_code=404, detail="Transaksi tidak ditemukan.")

    if trx.status in ["void", "cancelled"]:
        db.close()
        raise HTTPException(status_code=400, detail="Transaksi ini sudah pernah dibatalkan sebelumnya.")

    # Kembalikan stok barang yang sebelumnya keluar
    items = db.query(TransactionItem).filter(TransactionItem.transaction_id == trx.id).all()
    for it in items:
        prod = db.query(Product).filter(Product.id == it.product_id).first()
        if prod:
            prod.stock += it.quantity
            movement = StockMovement(
                product_id=it.product_id,
                tenant_id=trx.tenant_id,
                movement_type="in",
                quantity=it.quantity,
                reference=f"VOID-{invoice_no}",
                notes="Pembatalan Transaksi Kasir (Salah Pencet / Retur)",
                created_by=trx.user_id or 0
            )
            db.add(movement)

    trx.status = "void"
    db.commit()
    db.close()
    return {
        "success": True,
        "message": f"Transaksi {invoice_no} berhasil dibatalkan dan semua stok produk telah dikembalikan!"
    }


@app.post("/api/pos/transactions/{invoice_no}/restore")
async def pos_restore_transaction(invoice_no: str):
    """Memulihkan transaksi yang sempat dibatalkan: status kembali lunas dan stok kembali terpotong (keambil)."""
    db = SessionLocal()
    trx = db.query(Transaction).filter(Transaction.invoice_no == invoice_no).first()
    if not trx:
        db.close()
        raise HTTPException(status_code=404, detail="Transaksi tidak ditemukan.")

    if trx.status not in ["void", "cancelled"]:
        db.close()
        raise HTTPException(status_code=400, detail="Transaksi ini sedang aktif (tidak dalam status batal).")

    # Ambil kembali stok barang yang dipulihkan
    items = db.query(TransactionItem).filter(TransactionItem.transaction_id == trx.id).all()
    for it in items:
        prod = db.query(Product).filter(Product.id == it.product_id).first()
        if prod:
            prod.stock = max(0, prod.stock - it.quantity)
            movement = StockMovement(
                product_id=it.product_id,
                tenant_id=trx.tenant_id,
                movement_type="out",
                quantity=it.quantity,
                reference=f"RESTORE-{invoice_no}",
                notes="Pemulihan Transaksi Kasir (Stok Kembali Keambil)",
                created_by=trx.user_id or 0
            )
            db.add(movement)

    trx.status = "completed"
    db.commit()
    db.close()
    return {
        "success": True,
        "message": f"Transaksi {invoice_no} berhasil dipulihkan! Stok produk kembali dipotong."
    }


@app.get("/api/pos/transactions/recent")
async def get_recent_pos_transactions(tenant_id: int | None = None, limit: int = 10):
    """Daftar riwayat transaksi kasir terkini untuk kontrol kasir / opsi pembatalan jika salah pencet."""
    db = SessionLocal()
    tid = tenant_id or 1
    trxs = db.query(Transaction).filter(
        Transaction.tenant_id == tid
    ).order_by(desc(Transaction.created_at)).limit(limit).all()

    results = []
    for t in trxs:
        items = db.query(TransactionItem).filter(TransactionItem.transaction_id == t.id).all()
        results.append({
            "id": t.id,
            "invoice_no": t.invoice_no or f"INV-{t.id:06d}",
            "payment_method": t.payment_method,
            "grand_total": t.grand_total or t.subtotal or 0,
            "status": t.status or "completed",
            "created_at": t.created_at.strftime("%d/%m/%Y %H:%M") if t.created_at else "-",
            "items": [{"name": it.product_name, "qty": it.quantity, "price": it.unit_price} for it in items]
        })
    db.close()
    return {"transactions": results}


# ==============================================================================
# ONLINE ORDERS MANAGEMENT (Khusus Kasir & Owner)
# ==============================================================================

@app.get("/api/pos/orders")
async def get_pos_online_orders(tenant_id: int | None = None, limit: int = 30):
    """Daftar pesanan online masuk untuk diproses oleh kasir/owner."""
    db = SessionLocal()
    tid = tenant_id or 1
    # Hanya tampilkan pesanan dalam 1 bulan terakhir (30 hari terakhir)
    one_month_ago = datetime.now() - timedelta(days=30)
    orders = db.query(Transaction).filter(
        Transaction.tenant_id == tid,
        Transaction.created_at >= one_month_ago
    ).order_by(desc(Transaction.created_at)).limit(limit).all()

    results = []
    for o in orders:
        items = db.query(TransactionItem).filter(TransactionItem.transaction_id == o.id).all()
        results.append({
            "id": o.id,
            "invoice_no": o.invoice_no or f"INV-{o.id:06d}",
            "payment_method": o.payment_method,
            "grand_total": o.grand_total or o.subtotal or 0,
            "status": o.status or "completed",
            "created_at": o.created_at.strftime("%d/%m/%Y %H:%M") if o.created_at else "-",
            "items": [{"name": it.product_name, "qty": it.quantity, "price": it.unit_price} for it in items]
        })

    db.close()
    return {"orders": results}


@app.put("/api/pos/orders/{trx_id}/status")
async def update_pos_order_status(trx_id: int, req: OrderStatusUpdateRequest):
    """Kasir memperbarui status pesanan online (misal: 'siap_diambil' atau 'completed')."""
    db = SessionLocal()
    trx = db.query(Transaction).filter(Transaction.id == trx_id).first()
    if not trx:
        db.close()
        raise HTTPException(status_code=404, detail="Pesanan tidak ditemukan.")

    trx.status = req.status
    db.commit()

    # Kirim notifikasi bot Telegram ke pembeli jika status berubah
    status_label = {
        "siap_diambil": "🛍️ *PESANAN ANDA SUDAH SIAP DIAMBIL!*\n\nSilakan datang ke toko kelontong untuk mengambil pesanan Anda.",
        "completed": "✅ *PESANAN SELESAI / LUNAS!*\n\nTerima kasih telah berbelanja di Toko Ciamis.",
        "diproses": "⏳ *PESANAN SEDANG DISIAPKAN* oleh kasir toko.",
        "cancelled": "❌ *PESANAN DIBATALKAN* oleh pihak toko."
    }.get(req.status, f"Status pesanan Anda kini: *{req.status}*")

    if BOT_TOKEN and trx.user_id:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                await client.post(
                    f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                    json={
                        "chat_id": trx.user_id,
                        "text": f"📢 *UPDATE PESANAN `{trx.invoice_no}`*\n\n{status_label}",
                        "parse_mode": "Markdown"
                    }
                )
        except Exception as e:
            logger.error(f"Failed to notify user about order status: {e}")

    db.close()
    return {"success": True, "message": f"Status pesanan berhasil diubah menjadi '{req.status}'"}



# ==============================================================================
# PRODUCT MANAGEMENT ENDPOINTS (Owner & Kasir)
# ==============================================================================

@app.get("/api/mini/user-role")
async def mini_user_role(request: Request, user_id: int | None = None):
    """Detect current user's role: 'owner', 'kasir', or 'customer'."""
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    tg_user = None
    if init_data:
        try:
            tg_user = validate_telegram_init_data(init_data)
        except Exception:
            pass

    target_id = None
    if tg_user and tg_user.get("id"):
        target_id = tg_user.get("id")
    elif user_id:
        target_id = user_id

    role = "customer"
    tenant_id = None
    full_name = "Pelanggan"

    db = SessionLocal()
    if target_id:
        bot_user = db.query(BotUser).filter(
            BotUser.telegram_id == target_id,
            BotUser.is_active == True
        ).first()
        if bot_user:
            role = bot_user.role
            tenant_id = bot_user.tenant_id
            full_name = bot_user.full_name or "Kasir/Owner"
    db.close()

    return {
        "role": role,
        "tenant_id": tenant_id,
        "full_name": full_name,
        "is_staff": role in ["owner", "kasir"]
    }


@app.post("/api/mini/product")
async def mini_create_product(req: ProductManageRequest):
    """Add a new product to store catalog (Owner & Kasir)."""
    db = SessionLocal()
    tid = req.tenant_id
    if not tid:
        first_with_prod = db.query(Product.tenant_id).filter(Product.tenant_id != None).first()
        tid = first_with_prod[0] if first_with_prod else 2

    max_id = db.query(func.max(Product.id)).scalar() or 0
    new_id = max_id + 1

    new_prod = Product(
        id=new_id,
        category=req.category,
        subcategory=req.subcategory or req.category,
        item_name=req.item_name,
        price=req.price,
        stock=req.stock,
        image_url=req.image_url,
        tenant_id=tid
    )
    db.add(new_prod)
    db.commit()
    db.refresh(new_prod)
    db.close()

    return {
        "success": True,
        "message": f"Produk '{req.item_name}' berhasil ditambahkan!",
        "product": {
            "id": new_prod.id,
            "item_name": new_prod.item_name,
            "category": new_prod.category,
            "price": new_prod.price,
            "stock": new_prod.stock,
            "image_url": new_prod.image_url
        }
    }


@app.put("/api/mini/product/{product_id}")
async def mini_update_product(product_id: int, req: ProductManageRequest):
    """Update an existing product (Owner & Kasir)."""
    db = SessionLocal()
    prod = db.query(Product).filter(Product.id == product_id).first()
    if not prod:
        db.close()
        raise HTTPException(status_code=404, detail="Produk tidak ditemukan.")

    prod.item_name = req.item_name
    prod.category = req.category
    if req.subcategory:
        prod.subcategory = req.subcategory
    prod.price = req.price
    prod.stock = req.stock
    if req.image_url is not None:
        prod.image_url = req.image_url

    db.commit()
    db.refresh(prod)
    db.close()

    return {
        "success": True,
        "message": f"Produk '{prod.item_name}' berhasil diperbarui!",
        "product": {
            "id": prod.id,
            "item_name": prod.item_name,
            "category": prod.category,
            "price": prod.price,
            "stock": prod.stock,
            "image_url": prod.image_url
        }
    }


@app.delete("/api/mini/product/{product_id}")
async def mini_delete_product(product_id: int):
    """Delete a product from store catalog (Owner & Kasir)."""
    db = SessionLocal()
    prod = db.query(Product).filter(Product.id == product_id).first()
    if not prod:
        db.close()
        raise HTTPException(status_code=404, detail="Produk tidak ditemukan.")

    name = prod.item_name
    db.delete(prod)
    db.commit()
    db.close()

    return {
        "success": True,
        "message": f"Produk '{name}' berhasil dihapus!"
    }


@app.post("/api/mini/upload-image")
async def mini_upload_image(
    file: UploadFile = File(...),
    product_id: int | None = Form(None)
):
    """
    Upload an image file directly from local storage/device.
    Saves image to uploads/ folder and optionally updates product's image_url.
    """
    if not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File harus berupa gambar (JPEG, PNG, WEBP, dll).")

    # Generate unique filename
    ext = os.path.splitext(file.filename or "")[1].lower()
    if not ext or ext not in [".jpg", ".jpeg", ".png", ".webp", ".gif"]:
        ext = ".jpg"

    safe_name = f"prod_{secrets.token_hex(8)}{ext}"
    uploads_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")
    os.makedirs(uploads_dir, exist_ok=True)
    target_path = os.path.join(uploads_dir, safe_name)

    # Save contents
    contents = await file.read()
    with open(target_path, "wb") as f:
        f.write(contents)

    image_rel_url = f"/uploads/{safe_name}"

    # If product_id given, immediately update product in DB
    updated_prod = None
    if product_id:
        db = SessionLocal()
        prod = db.query(Product).filter(Product.id == product_id).first()
        if prod:
            prod.image_url = image_rel_url
            db.commit()
            db.refresh(prod)
            updated_prod = {
                "id": prod.id,
                "item_name": prod.item_name,
                "image_url": prod.image_url
            }
        db.close()

    return {
        "success": True,
        "message": "Gambar berhasil diunggah!",
        "image_url": image_rel_url,
        "product": updated_prod
    }


# ==============================================================================
# STATIC FILE SERVING (Mini App, Website & Uploads)
# ==============================================================================
import os
_base_dir = os.path.dirname(os.path.abspath(__file__))

_uploads_dir = os.path.join(_base_dir, "uploads")
os.makedirs(_uploads_dir, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=_uploads_dir), name="uploads")

_miniapp_dir = os.path.join(_base_dir, "miniapp")
if os.path.isdir(_miniapp_dir):
    app.mount("/miniapp", StaticFiles(directory=_miniapp_dir, html=True), name="miniapp")

_website_dir = os.path.join(_base_dir, "website")
if os.path.isdir(_website_dir):
    app.mount("/website", StaticFiles(directory=_website_dir, html=True), name="website")
