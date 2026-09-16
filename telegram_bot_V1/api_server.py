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

from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from database import SessionLocal, BotUser, Tenant, RegistrationToken, Transaction, Product, TransactionItem
from sqlalchemy import func, desc

# ── Try to import config, fall back to env vars ───────────────────────────────
try:
    from config import API_SECRET_KEY, BOT_TOKEN
except ImportError:
    import os
    API_SECRET_KEY = os.getenv("API_SECRET_KEY", "")
    BOT_TOKEN = os.getenv("BOT_TOKEN", "")

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


# ==============================================================================
# Pydantic Schemas
# ==============================================================================

class RegisterOwnerRequest(BaseModel):
    store_name: str
    telegram_username: str   # @username without @, for display only


class GenerateKasirTokenRequest(BaseModel):
    api_secret: str          # Shared secret to protect this endpoint


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

    # Stock overview (total products, low stock count)
    total_products = db.query(Product).count()
    low_stock = db.query(Product).filter((Product.stock <= Product.min_stock) | (Product.stock == 0)).count()

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
    summary = db.query(Product.category, func.sum(Product.stock)).group_by(Product.category).all()
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
    items = db.query(Product).filter(Product.is_consignment == True).all()
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
# STATIC FILE SERVING (Mini App & Website)
# ==============================================================================
import os
_base_dir = os.path.dirname(os.path.abspath(__file__))

_miniapp_dir = os.path.join(_base_dir, "miniapp")
if os.path.isdir(_miniapp_dir):
    app.mount("/miniapp", StaticFiles(directory=_miniapp_dir, html=True), name="miniapp")

_website_dir = os.path.join(_base_dir, "website")
if os.path.isdir(_website_dir):
    app.mount("/website", StaticFiles(directory=_website_dir, html=True), name="website")
