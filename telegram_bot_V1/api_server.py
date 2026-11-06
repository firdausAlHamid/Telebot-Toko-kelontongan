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
import math
from datetime import datetime, timedelta, date
from typing import Optional, List, Dict, Any
from urllib.parse import unquote, parse_qsl

from fastapi import (
    FastAPI, HTTPException, Header, Request, Response,
    UploadFile, File, Form, Depends, status
)
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx

from database import (
    SessionLocal, BotUser, Tenant, RegistrationToken, Transaction,
    Product, TransactionItem, StockMovement, Promotion, StoreSchedule,
    QrisTransaction, SeasonalPeriod, Category
)
from sqlalchemy import func, desc
from receipt_generator import generate_receipt_image
import qris_service
from transaction_service import (
    apply_sale_stock,
    restore_sale_stock,
    settle_qris_paid,
    mark_qris_terminal,
    find_insufficient_stock,
    format_stock_error,
    VOID_STATUSES,
    QRIS_PAID_STATUSES,
    QRIS_DEAD_STATUSES,
)

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

@app.middleware("http")
async def disable_cache_for_miniapp(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/miniapp") or request.url.path.startswith("/api"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        response.headers["ngrok-skip-browser-warning"] = "true"
    return response

from fastapi.responses import RedirectResponse, StreamingResponse

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


class CategoryManageRequest(BaseModel):
    tenant_id: int | None = None
    name: str
    icon: str | None = "📦"


class ProductManageRequest(BaseModel):
    item_name: str
    category: str
    subcategory: str | None = None
    price: int
    stock: int = 0
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


class AuthUser:
    """Represents an authenticated staff/owner or customer user."""
    def __init__(self, telegram_id: int, role: str, tenant_id: int, full_name: str = ""):
        self.telegram_id = telegram_id
        self.role = role
        self.tenant_id = tenant_id
        self.full_name = full_name

    def to_dict(self):
        return {
            "telegram_id": self.telegram_id,
            "role": self.role,
            "tenant_id": self.tenant_id,
            "full_name": self.full_name,
        }

    def __getitem__(self, item):
        return getattr(self, item)

    def get(self, item, default=None):
        return getattr(self, item, default)


def get_user_from_init_data(init_data: str, request: Request = None):
    """Parse initData, validate it, and look up the BotUser. Returns (tg_user_dict, BotUser)."""
    tg_user = None
    if init_data and "hash=" in init_data:
        try:
            tg_user = validate_telegram_init_data(init_data)
        except Exception:
            pass

    db = SessionLocal()
    user = None

    if tg_user and tg_user.get("id"):
        telegram_id = tg_user.get("id")
        user = db.query(BotUser).filter(
            BotUser.telegram_id == telegram_id,
            BotUser.is_active == True,
        ).first()

    # Fallback for browser / ngrok testing (outside Telegram WebApp)
    if not user:
        dev_role = None
        if request:
            dev_role = request.headers.get("X-Dev-Role") or request.query_params.get("role")
        if not dev_role and init_data:
            if "role=owner" in init_data or "dev_role=owner" in init_data:
                dev_role = "owner"
            elif "role=kasir" in init_data or "dev_role=kasir" in init_data:
                dev_role = "kasir"

        if dev_role:
            q = db.query(BotUser).filter(BotUser.is_active == True, BotUser.role == dev_role)
            user = q.first()
            if not user:
                user = db.query(BotUser).filter(BotUser.is_active == True, BotUser.role.in_(["kasir", "owner"])).first()

            if user:
                tg_user = {
                    "id": user.telegram_id,
                    "first_name": user.full_name or ("Kasir" if user.role == "kasir" else "Owner"),
                    "username": user.telegram_username or user.role
                }

    db.close()

    if not user:
        raise HTTPException(status_code=401, detail="User belum terdaftar atau tidak memiliki akses.")

    return tg_user, user


def get_current_user(request: Request) -> AuthUser:
    """
    FastAPI dependency that extracts and validates caller identity & role:
    1. Cryptographic HMAC-SHA256 signature via Telegram Mini App initData (X-Telegram-Init-Data)
    2. Server admin secret key via X-API-Secret or Authorization: Bearer
    3. Explicit Dev Role header (X-Dev-Role) for local browser testing & automated tests

    Raises HTTPException(401) if no valid credentials provided.
    """
    init_data = request.headers.get("X-Telegram-Init-Data") or request.query_params.get("init_data", "")
    api_secret = request.headers.get("X-API-Secret")
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        bearer_token = auth_header[7:].strip()
        if API_SECRET_KEY and bearer_token == API_SECRET_KEY:
            api_secret = API_SECRET_KEY

    # 1. API Secret / Admin Key Bypass
    if API_SECRET_KEY and api_secret == API_SECRET_KEY:
        req_tid = request.headers.get("X-Tenant-Id")
        tenant_id = int(req_tid) if (req_tid and req_tid.isdigit()) else 2
        return AuthUser(telegram_id=0, role="owner", tenant_id=tenant_id, full_name="Admin Server")

    db = SessionLocal()
    try:
        # 2. Telegram WebApp cryptographic initData validation
        if init_data and "hash=" in init_data:
            tg_data = validate_telegram_init_data(init_data)
            if not tg_data:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Signature Telegram initData tidak valid atau sudah kedaluwarsa."
                )
            tg_id = tg_data.get("id")
            user = db.query(BotUser).filter(
                BotUser.telegram_id == tg_id,
                BotUser.is_active == True
            ).first()
            if not user:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="User Telegram belum terdaftar atau tidak aktif di sistem."
                )
            return AuthUser(
                telegram_id=user.telegram_id,
                role=user.role,
                tenant_id=user.tenant_id or 2,
                full_name=user.full_name or user.role
            )

        # 3. Development / Localhost browser testing (X-Dev-Role)
        dev_role = request.headers.get("X-Dev-Role")
        if not dev_role and "role" in request.query_params:
            dev_role = request.query_params.get("role")
        if not dev_role and init_data:
            if "role=owner" in init_data or "dev_role=owner" in init_data:
                dev_role = "owner"
            elif "role=kasir" in init_data or "dev_role=kasir" in init_data:
                dev_role = "kasir"

        if dev_role in ("owner", "kasir"):
            req_tenant_id = request.headers.get("X-Tenant-Id")
            q = db.query(BotUser).filter(BotUser.is_active == True, BotUser.role == dev_role)
            if req_tenant_id and req_tenant_id.isdigit():
                q = q.filter(BotUser.tenant_id == int(req_tenant_id))
            user = q.first()
            if not user:
                user = db.query(BotUser).filter(BotUser.is_active == True, BotUser.role == dev_role).first()
            tenant_id = int(req_tenant_id) if (req_tenant_id and req_tenant_id.isdigit()) else (user.tenant_id if user else 2)
            uid = user.telegram_id if user else (999999 if dev_role == "owner" else 888888)
            name = user.full_name if user else f"Dev {dev_role.capitalize()}"
            return AuthUser(telegram_id=uid, role=dev_role, tenant_id=tenant_id, full_name=name)

        # Direct calls without credentials: reject unauthorized
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Autentikasi gagal: Kredensial tidak ditemukan. Harap sertakan autentikasi Telegram Mini App (X-Telegram-Init-Data) atau otorisasi peran."
        )
    finally:
        db.close()


def require_roles(allowed_roles: list[str]):
    """
    FastAPI dependency factory enforcing RBAC on endpoints.
    Rejects with 403 Forbidden if user's role is not in allowed_roles.
    """
    def _role_checker(current_user: AuthUser = Depends(get_current_user)) -> AuthUser:
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Akses ditolak: Operasi ini membutuhkan peran {allowed_roles}, namun peran Anda adalah '{current_user.role}'."
            )
        return current_user
    return _role_checker


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
    override_tid = request.query_params.get("tenant_id") or request.headers.get("X-Tenant-Id")
    if override_tid:
        try:
            tenant_id = int(override_tid)
        except ValueError:
            pass

    # Get today's date range
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)

    # Base query
    base_q = db.query(Transaction).filter(
        Transaction.status == "completed",
        Transaction.created_at >= today_start,
        Transaction.created_at < today_end,
    )

    if tenant_id:
        base_q = base_q.filter(Transaction.tenant_id == tenant_id)
        if bot_user.role == "kasir" and not override_tid:
            # Kasir can only see their own transactions when not in explicit tenant mode
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

    # Monthly revenue
    month_revenue = None
    if tenant_id:
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
        "tenant_id": tenant_id,
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
    override_tid = request.query_params.get("tenant_id") or request.headers.get("X-Tenant-Id")
    if override_tid:
        try:
            tenant_id = int(override_tid)
        except ValueError:
            pass

    summary = db.query(Product.category, func.sum(Product.stock), func.count(Product.id)).filter(
        Product.tenant_id == tenant_id
    ).group_by(Product.category).order_by(func.sum(Product.stock).desc()).all()
    db.close()

    return [{"category": s[0] or "Lainnya", "total_stock": int(s[1] or 0), "product_count": int(s[2] or 0)} for s in summary]


@app.get("/api/mini/top-products")
async def mini_top_products(request: Request):
    """Return top 5 best-selling products in the last 7 days."""
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    tg_user, bot_user = get_user_from_init_data(init_data)
    if not bot_user:
        raise HTTPException(status_code=403, detail="User belum terdaftar.")

    db = SessionLocal()
    tenant_id = bot_user.tenant_id
    override_tid = request.query_params.get("tenant_id") or request.headers.get("X-Tenant-Id")
    if override_tid:
        try:
            tenant_id = int(override_tid)
        except ValueError:
            pass

    seven_days_ago = datetime.now() - timedelta(days=7)
    
    q = (
        db.query(TransactionItem.product_name, func.sum(TransactionItem.quantity).label("qty"))
        .join(Transaction, Transaction.id == TransactionItem.transaction_id)
        .filter(Transaction.status == "completed", Transaction.created_at >= seven_days_ago)
    )
    if tenant_id:
        q = q.filter(Transaction.tenant_id == tenant_id)

    top_items = (
        q.group_by(TransactionItem.product_name)
        .order_by(desc("qty"))
        .limit(5)
        .all()
    )
    db.close()

    return [{"product_name": t[0], "quantity": int(t[1])} for t in top_items]


# ==============================================================================
# PRODUCT ANALYTICS (Analisis Produk — gaya dashboard indeks/risiko)
# ==============================================================================

_HARI = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]
_BULAN = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"]


def _sales_rows(db, tenant_id, start, end=None):
    """Return raw sales rows: (product_id, qty, subtotal, trx_id, created_at, payment_method)."""
    q = (
        db.query(
            TransactionItem.product_id,
            TransactionItem.quantity,
            TransactionItem.subtotal,
            TransactionItem.unit_price,
            Transaction.id,
            Transaction.created_at,
            Transaction.payment_method,
        )
        .join(Transaction, Transaction.id == TransactionItem.transaction_id)
        .filter(Transaction.status == "completed", Transaction.created_at >= start)
    )
    if end is not None:
        q = q.filter(Transaction.created_at < end)
    if tenant_id:
        q = q.filter(Transaction.tenant_id == tenant_id)
    return q.all()


def _aggregate(rows):
    """Aggregate per product: qty, revenue, trx set, active days set."""
    agg = {}
    for pid, qty, sub, unit, trx_id, created, _pm in rows:
        a = agg.setdefault(pid, {"qty": 0, "revenue": 0, "trx": set(), "days": set()})
        q = qty or 0
        a["qty"] += q
        a["revenue"] += sub if sub is not None else (unit or 0) * q
        a["trx"].add(trx_id)
        if created:
            a["days"].add(created.date())
    return agg


def _scores(products, agg, period_days):
    """Composite performance score 0-100 per product + rank (1 = best)."""
    max_qty = max([agg.get(p.id, {}).get("qty", 0) for p in products] + [1])
    max_rev = max([agg.get(p.id, {}).get("revenue", 0) for p in products] + [1])
    max_trx = max([len(agg.get(p.id, {}).get("trx", ())) for p in products] + [1])
    result = {}
    for p in products:
        a = agg.get(p.id)
        if not a:
            result[p.id] = 0.0
            continue
        s = (
            0.35 * a["qty"] / max_qty
            + 0.30 * a["revenue"] / max_rev
            + 0.20 * len(a["trx"]) / max_trx
            + 0.15 * min(len(a["days"]) / period_days, 1)
        ) * 100
        result[p.id] = round(s, 2)
    ordered = sorted(products, key=lambda p: (-result[p.id], p.item_name or ""))
    ranks = {p.id: i + 1 for i, p in enumerate(ordered)}
    return result, ranks


def _perf_class(score):
    if score >= 60:
        return "Laris", "#22c55e"
    if score >= 30:
        return "Sedang", "#f59e0b"
    if score > 0:
        return "Lambat", "#ef4444"
    return "Tidak Terjual", "#64748b"


def _stock_health(stock, qty_30):
    """Days-of-cover → gauge score 0-10 + label."""
    stock = stock or 0
    avg_daily = qty_30 / 30.0
    if avg_daily <= 0:
        if stock <= 0:
            return {"score": 0.0, "label": "Habis", "color": "#ef4444", "days_cover": 0, "avg_daily": 0}
        return {"score": 5.0, "label": "Tidak Bergerak", "color": "#94a3b8", "days_cover": None, "avg_daily": 0}
    days = stock / avg_daily
    score = round(min(days / 3.0, 10.0), 2)  # 30 hari stok = skor 10
    if days < 3:
        label, color = "Kritis", "#ef4444"
    elif days < 7:
        label, color = "Menipis", "#f59e0b"
    elif days <= 30:
        label, color = "Aman", "#22c55e"
    else:
        label, color = "Berlebih", "#38bdf8"
    return {"score": score, "label": label, "color": color,
            "days_cover": round(days, 1), "avg_daily": round(avg_daily, 2)}


def _analytics_tenant(request: Request):
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    _tg, bot_user = get_user_from_init_data(init_data, request)
    if not bot_user:
        raise HTTPException(status_code=403, detail="User belum terdaftar.")
    override_tid = request.query_params.get("tenant_id") or request.headers.get("X-Tenant-Id")
    if override_tid:
        try:
            return int(override_tid)
        except ValueError:
            pass
    return bot_user.tenant_id


@app.get("/api/mini/product-analytics")
async def mini_product_analytics_list(request: Request):
    """Ranking semua produk (30 hari terakhir) dengan skor performa & status stok."""
    tenant_id = _analytics_tenant(request)
    db = SessionLocal()
    try:
        products = db.query(Product).filter(Product.tenant_id == tenant_id).all()
        now = datetime.now()
        agg = _aggregate(_sales_rows(db, tenant_id, now - timedelta(days=30)))
        scores, ranks = _scores(products, agg, 30)
        out = []
        for p in products:
            a = agg.get(p.id, {"qty": 0, "revenue": 0, "trx": set()})
            cls, color = _perf_class(scores[p.id])
            sh = _stock_health(p.stock, a["qty"])
            out.append({
                "id": p.id, "name": p.item_name, "category": p.category or "Lainnya",
                "image_url": p.image_url, "stock": p.stock or 0, "price": p.price or 0,
                "qty_30d": a["qty"], "revenue_30d": a["revenue"],
                "score": scores[p.id], "rank": ranks[p.id],
                "class": cls, "class_color": color,
                "stock_label": sh["label"], "stock_color": sh["color"],
                "days_cover": sh.get("days_cover"),
                "avg_daily": round(sh.get("avg_daily", 0), 1)
            })
        out.sort(key=lambda x: x["rank"])
        return {"total_products": len(products), "items": out}
    finally:
        db.close()


@app.get("/api/mini/financial-ledger")
async def mini_financial_ledger(request: Request):
    """Multi-period financial breakdown for deep audit ledger view."""
    tenant_id = _analytics_tenant(request)
    db = SessionLocal()
    try:
        now = datetime.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        yesterday_start = today_start - timedelta(days=1)
        d7 = now - timedelta(days=7)
        d30 = now - timedelta(days=30)

        periods_conf = [
            ("today", "Hari Ini", today_start, now),
            ("yesterday", "Kemarin", yesterday_start, today_start),
            ("last_7d", "7 Hari Terakhir", d7, now),
            ("last_30d", "30 Hari Terakhir", d30, now),
        ]

        ledger = []
        for key, label, start, end in periods_conf:
            txns = db.query(Transaction).filter(
                Transaction.tenant_id == tenant_id,
                Transaction.status == "completed",
                Transaction.created_at >= start,
                Transaction.created_at <= end
            ).all()

            trx_count = len(txns)
            gross = sum(t.subtotal or t.total_amount or 0 for t in txns)
            disc = sum(t.total_discount or 0 for t in txns)
            net = sum(t.grand_total or t.total_amount or 0 for t in txns)
            avg_basket = int(net / trx_count) if trx_count > 0 else 0
            est_profit = int(net * 0.18)  # Estimasi margin laba kotor retail 18%

            ledger.append({
                "key": key,
                "label": label,
                "trx_count": trx_count,
                "gross_revenue": gross,
                "discount": disc,
                "net_revenue": net,
                "avg_basket": avg_basket,
                "est_profit": est_profit
            })
        return {"ledger": ledger}
    finally:
        db.close()


@app.get("/api/mini/product-analytics/{product_id}")
async def mini_product_analytics_detail(product_id: int, request: Request):
    """Detail analisis 1 produk — KPI, tren, peringkat, pola hari, kesehatan stok, profil radar."""
    tenant_id = _analytics_tenant(request)
    db = SessionLocal()
    try:
        product = db.query(Product).filter(Product.id == product_id, Product.tenant_id == tenant_id).first()
        if not product:
            raise HTTPException(status_code=404, detail="Produk tidak ditemukan.")

        products = db.query(Product).filter(Product.tenant_id == tenant_id).all()
        now = datetime.now()
        d30, d60 = now - timedelta(days=30), now - timedelta(days=60)

        rows_30 = _sales_rows(db, tenant_id, d30)
        rows_prev = _sales_rows(db, tenant_id, d60, d30)
        agg_30, agg_prev = _aggregate(rows_30), _aggregate(rows_prev)
        scores, ranks = _scores(products, agg_30, 30)
        prev_scores, prev_ranks = _scores(products, agg_prev, 30)

        me = agg_30.get(product_id, {"qty": 0, "revenue": 0, "trx": set(), "days": set()})
        me_prev = agg_prev.get(product_id, {"qty": 0, "revenue": 0, "trx": set(), "days": set()})

        # --- Split metode bayar (seperti split populasi L/P) ---
        cash_qty = qris_qty = 0
        for pid, qty, _s, _u, _t, _c, pm in rows_30:
            if pid != product_id:
                continue
            if pm and "qris" in pm.lower():
                qris_qty += qty or 0
            else:
                cash_qty += qty or 0
        tot_pm = cash_qty + qris_qty

        # --- Tren 6 bulan ---
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        months = []
        y, m = month_start.year, month_start.month
        for _ in range(6):
            months.append((y, m))
            m -= 1
            if m == 0:
                y, m = y - 1, 12
        months.reverse()
        first = datetime(months[0][0], months[0][1], 1)
        trend_map = {k: {"qty": 0, "revenue": 0} for k in months}
        for pid, qty, sub, unit, _t, created, _pm in _sales_rows(db, tenant_id, first):
            if pid != product_id or not created:
                continue
            k = (created.year, created.month)
            if k in trend_map:
                trend_map[k]["qty"] += qty or 0
                trend_map[k]["revenue"] += sub if sub is not None else (unit or 0) * (qty or 0)
        trend = [{"label": f"{_BULAN[mm - 1]} {str(yy)[2:]}", **trend_map[(yy, mm)]} for yy, mm in months]

        # --- Pola hari (90 hari): % transaksi per hari yang memuat produk ini ---
        rows_90 = _sales_rows(db, tenant_id, now - timedelta(days=90))
        all_trx = [set() for _ in range(7)]
        hit_trx = [set() for _ in range(7)]
        hour_qty = [0] * 24
        for pid, qty, _s, _u, trx_id, created, _pm in rows_90:
            if not created:
                continue
            wd = created.weekday()
            all_trx[wd].add(trx_id)
            if pid == product_id:
                hit_trx[wd].add(trx_id)
                hour_qty[created.hour] += qty or 0
        weekday = []
        for i in range(7):
            total = len(all_trx[i])
            pct = round(len(hit_trx[i]) / total * 100, 1) if total else 0
            weekday.append({"day": _HARI[i], "pct": pct, "hits": len(hit_trx[i]), "total": total})
        peak_hour = max(range(24), key=lambda h: hour_qty[h]) if any(hour_qty) else None

        # --- Kesehatan stok (gauge) ---
        sh = _stock_health(product.stock, me["qty"])

        # --- Profil radar (dinormalisasi terhadap produk terbaik) ---
        max_qty = max([a["qty"] for a in agg_30.values()] + [1])
        max_rev = max([a["revenue"] for a in agg_30.values()] + [1])
        max_trx = max([len(a["trx"]) for a in agg_30.values()] + [1])
        if me_prev["qty"] > 0:
            growth = (me["qty"] - me_prev["qty"]) / me_prev["qty"] * 100
        else:
            growth = 100.0 if me["qty"] > 0 else 0.0
        cover = sh["days_cover"]
        availability = 0 if (product.stock or 0) <= 0 else (100 if cover is None else min(cover / 30 * 100, 100))
        radar = [
            {"axis": "Volume", "value": round(me["qty"] / max_qty * 100, 1)},
            {"axis": "Omzet", "value": round(me["revenue"] / max_rev * 100, 1)},
            {"axis": "Frekuensi", "value": round(len(me["trx"]) / max_trx * 100, 1)},
            {"axis": "Konsistensi", "value": round(min(len(me["days"]) / 30, 1) * 100, 1)},
            {"axis": "Pertumbuhan", "value": round(max(min((growth + 100) / 2, 100), 0), 1)},
            {"axis": "Ketersediaan", "value": round(availability, 1)},
        ]

        # --- Kontribusi kategori ---
        cat_rev = sum(agg_30.get(p.id, {}).get("revenue", 0) for p in products if p.category == product.category)
        store_rev = sum(a["revenue"] for a in agg_30.values())

        # --- Insight / rekomendasi ---
        insights = []
        if sh["label"] in ("Kritis", "Habis"):
            insights.append(("danger", f"Stok {sh['label'].lower()} — segera restock (rata-rata laku {sh['avg_daily']}/hari)."))
        elif sh["label"] == "Menipis":
            insights.append(("warn", f"Stok cukup ±{sh['days_cover']} hari lagi. Siapkan pemesanan ulang."))
        elif sh["label"] == "Berlebih":
            insights.append(("info", f"Stok cukup ±{sh['days_cover']} hari — pertimbangkan promo agar perputaran lebih cepat."))
        elif sh["label"] == "Tidak Bergerak":
            insights.append(("warn", "Tidak ada penjualan 30 hari terakhir. Coba promo/bundling atau pindah posisi display."))
        if growth >= 20 and me["qty"] > 0:
            insights.append(("good", f"Penjualan naik {growth:.0f}% dibanding 30 hari sebelumnya."))
        elif growth <= -20:
            insights.append(("warn", f"Penjualan turun {abs(growth):.0f}% dibanding 30 hari sebelumnya."))
        best_day = max(weekday, key=lambda w: w["pct"]) if weekday else None
        if best_day and best_day["pct"] > 0:
            insights.append(("info", f"Paling sering dibeli hari {best_day['day']} ({best_day['pct']}% transaksi)."))
        if peak_hour is not None:
            insights.append(("info", f"Jam ramai produk ini: {peak_hour:02d}:00–{(peak_hour + 1) % 24:02d}:00."))

        cls, color = _perf_class(scores[product_id])
        return {
            "product": {
                "id": product.id, "name": product.item_name, "category": product.category or "Lainnya",
                "price": product.price or 0, "stock": product.stock or 0, "min_stock": product.min_stock or 0,
                "image_url": product.image_url,
            },
            "updated_at": now.strftime("%d %b %Y %H:%M"),
            "kpi": {
                "qty_30d": me["qty"], "revenue_30d": me["revenue"], "trx_30d": len(me["trx"]),
                "active_days": len(me["days"]),
                "cash_qty": cash_qty, "qris_qty": qris_qty,
                "cash_pct": round(cash_qty / tot_pm * 100, 1) if tot_pm else 0,
                "qris_pct": round(qris_qty / tot_pm * 100, 1) if tot_pm else 0,
            },
            "score": scores[product_id],
            "rank": ranks[product_id],
            "total_products": len(products),
            "class": cls, "class_color": color,
            "prev_rank": prev_ranks[product_id],
            "rank_change": prev_ranks[product_id] - ranks[product_id],
            "growth_pct": round(growth, 1),
            "trend": trend,
            "weekday": weekday,
            "peak_hour": peak_hour,
            "stock_health": sh,
            "radar": radar,
            "category_share_pct": round(me["revenue"] / cat_rev * 100, 1) if cat_rev else 0,
            "store_share_pct": round(me["revenue"] / store_rev * 100, 2) if store_rev else 0,
            "insights": [{"type": t, "text": x} for t, x in insights],
        }
    finally:
        db.close()

# ── Seasonal Academic Cycles & Predictive Restock Analytics ───────────────
class SeasonCreateRequest(BaseModel):
    name: str
    phase_type: str = "active"  # "active", "short_break", "long_break"
    start_date: str
    end_date: str
    target_daily_revenue: float = 8500000.0
    notes: Optional[str] = ""

class SeasonUpdateRequest(BaseModel):
    name: Optional[str] = None
    phase_type: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    target_daily_revenue: Optional[float] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None


@app.get("/api/mini/seasons")
async def list_seasons(request: Request):
    """List all academic semester and holiday seasons for tenant."""
    tenant_id = _analytics_tenant(request)
    db = SessionLocal()
    try:
        seasons = (
            db.query(SeasonalPeriod)
            .filter(SeasonalPeriod.tenant_id == tenant_id)
            .order_by(SeasonalPeriod.start_date.asc())
            .all()
        )
        return [
            {
                "id": s.id,
                "name": s.name,
                "phase_type": s.phase_type,
                "start_date": s.start_date.isoformat(),
                "end_date": s.end_date.isoformat(),
                "target_daily_revenue": s.target_daily_revenue or 0,
                "notes": s.notes or "",
                "is_active": s.is_active,
            }
            for s in seasons
        ]
    finally:
        db.close()


@app.post("/api/mini/seasons")
async def create_season(
    req: SeasonCreateRequest,
    request: Request,
    current_user: AuthUser = Depends(require_roles(["owner"]))
):
    """Owner creates a new seasonal phase (active semester / holiday break)."""
    tenant_id = _analytics_tenant(request) or current_user.tenant_id
    db = SessionLocal()
    try:
        try:
            s_date = datetime.strptime(req.start_date, "%Y-%m-%d").date()
            e_date = datetime.strptime(req.end_date, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(status_code=400, detail="Format tanggal harus YYYY-MM-DD")

        if s_date > e_date:
            raise HTTPException(status_code=400, detail="Tanggal mulai tidak boleh lebih besar dari tanggal selesai")

        season = SeasonalPeriod(
            tenant_id=tenant_id,
            name=req.name,
            phase_type=req.phase_type,
            start_date=s_date,
            end_date=e_date,
            target_daily_revenue=req.target_daily_revenue,
            notes=req.notes or "",
            is_active=True
        )
        db.add(season)
        db.commit()
        db.refresh(season)
        return {
            "success": True,
            "season": {
                "id": season.id,
                "name": season.name,
                "phase_type": season.phase_type,
                "start_date": season.start_date.isoformat(),
                "end_date": season.end_date.isoformat(),
                "target_daily_revenue": season.target_daily_revenue,
                "notes": season.notes,
                "is_active": season.is_active
            }
        }
    finally:
        db.close()


@app.put("/api/mini/seasons/{season_id}")
async def update_season(
    season_id: int,
    req: SeasonUpdateRequest,
    request: Request,
    current_user: AuthUser = Depends(require_roles(["owner"]))
):
    """Owner updates an existing academic season period."""
    tenant_id = _analytics_tenant(request) or current_user.tenant_id
    db = SessionLocal()
    try:
        season = db.query(SeasonalPeriod).filter(
            SeasonalPeriod.id == season_id,
            SeasonalPeriod.tenant_id == tenant_id
        ).first()
        if not season:
            raise HTTPException(status_code=404, detail="Musim/periode tidak ditemukan")

        if req.name is not None:
            season.name = req.name
        if req.phase_type is not None:
            season.phase_type = req.phase_type
        if req.start_date is not None:
            season.start_date = datetime.strptime(req.start_date, "%Y-%m-%d").date()
        if req.end_date is not None:
            season.end_date = datetime.strptime(req.end_date, "%Y-%m-%d").date()
        if season.start_date > season.end_date:
            raise HTTPException(status_code=400, detail="Tanggal mulai tidak boleh lebih besar dari tanggal selesai")
        if req.target_daily_revenue is not None:
            season.target_daily_revenue = req.target_daily_revenue
        if req.notes is not None:
            season.notes = req.notes
        if req.is_active is not None:
            season.is_active = req.is_active

        db.commit()
        db.refresh(season)
        return {
            "success": True,
            "season": {
                "id": season.id,
                "name": season.name,
                "phase_type": season.phase_type,
                "start_date": season.start_date.isoformat(),
                "end_date": season.end_date.isoformat(),
                "target_daily_revenue": season.target_daily_revenue,
                "notes": season.notes,
                "is_active": season.is_active
            }
        }
    finally:
        db.close()


@app.delete("/api/mini/seasons/{season_id}")
async def delete_season(
    season_id: int,
    request: Request,
    current_user: AuthUser = Depends(require_roles(["owner"]))
):
    """Owner deletes an academic season period."""
    tenant_id = _analytics_tenant(request) or current_user.tenant_id
    db = SessionLocal()
    try:
        season = db.query(SeasonalPeriod).filter(
            SeasonalPeriod.id == season_id,
            SeasonalPeriod.tenant_id == tenant_id
        ).first()
        if not season:
            raise HTTPException(status_code=404, detail="Musim/periode tidak ditemukan")
        db.delete(season)
        db.commit()
        return {"success": True, "message": "Periode musim berhasil dihapus"}
    finally:
        db.close()


@app.get("/api/mini/seasonal-analytics")
async def get_seasonal_analytics(request: Request):
    """Intelligent seasonal forecast and restock recommendation engine."""
    tenant_id = _analytics_tenant(request)
    db = SessionLocal()
    try:
        now = datetime.now()
        today = now.date()

        # Fetch configured seasons
        periods = (
            db.query(SeasonalPeriod)
            .filter(SeasonalPeriod.tenant_id == tenant_id, SeasonalPeriod.is_active == True)
            .order_by(SeasonalPeriod.start_date.asc())
            .all()
        )

        current_period = None
        next_period = None

        for p in periods:
            if p.start_date <= today <= p.end_date:
                current_period = p
            elif p.start_date > today and next_period is None:
                next_period = p

        if not current_period and periods:
            current_period = periods[0]

        # Phase timeline metrics
        if current_period:
            total_days = max(1, (current_period.end_date - current_period.start_date).days + 1)
            elapsed_days = max(0, min(total_days, (today - current_period.start_date).days + 1))
            remaining_days = max(0, (current_period.end_date - today).days)
            current_week = min(16, (elapsed_days // 7) + 1)
            total_weeks = math.ceil(total_days / 7)
            progress_pct = round(min(100.0, (elapsed_days / total_days) * 100), 1)
            target_rev = current_period.target_daily_revenue or 8500000
        else:
            total_days = 112
            elapsed_days = 56
            remaining_days = 56
            current_week = 9
            total_weeks = 16
            progress_pct = 50.0
            target_rev = 8500000

        # Today's actual achievement
        today_rev_res = db.query(func.sum(Transaction.total_amount), func.count(Transaction.id)).filter(
            Transaction.tenant_id == tenant_id,
            Transaction.status == "completed",
            func.date(Transaction.created_at) == today
        ).first()
        today_actual_rev = float(today_rev_res[0] or 0)
        today_trx_count = int(today_rev_res[1] or 0)
        today_achievement_pct = round((today_actual_rev / target_rev) * 100, 1) if target_rev else 0

        # Days until next phase
        days_until_next = (next_period.start_date - today).days if next_period else None

        # Distinct days & sales by phase for tenant
        active_start = current_period.start_date if current_period and current_period.phase_type == "active" else (today - timedelta(days=60))
        act_distinct_days = db.query(func.count(func.distinct(func.date(Transaction.created_at)))).filter(
            Transaction.tenant_id == tenant_id,
            Transaction.status == "completed",
            Transaction.created_at >= active_start
        ).scalar() or 1

        total_act_rev = db.query(func.sum(Transaction.total_amount)).filter(
            Transaction.tenant_id == tenant_id,
            Transaction.status == "completed",
            Transaction.created_at >= active_start
        ).scalar() or 0
        avg_active_daily = round(float(total_act_rev) / max(1, act_distinct_days))

        # Break sales
        break_periods = [p for p in periods if "break" in p.phase_type]
        if break_periods:
            bp = break_periods[0]
            brk_start, brk_end = bp.start_date, bp.end_date
        else:
            brk_start, brk_end = today - timedelta(days=150), today - timedelta(days=61)

        brk_distinct_days = db.query(func.count(func.distinct(func.date(Transaction.created_at)))).filter(
            Transaction.tenant_id == tenant_id,
            Transaction.status == "completed",
            func.date(Transaction.created_at) >= brk_start,
            func.date(Transaction.created_at) <= brk_end
        ).scalar() or 1

        total_brk_rev = db.query(func.sum(Transaction.total_amount)).filter(
            Transaction.tenant_id == tenant_id,
            Transaction.status == "completed",
            func.date(Transaction.created_at) >= brk_start,
            func.date(Transaction.created_at) <= brk_end
        ).scalar() or 0
        avg_break_daily = round(float(total_brk_rev) / max(1, brk_distinct_days))
        ratio_multiplier = round(avg_active_daily / max(1, avg_break_daily), 1)

        # Product level velocity
        q_act = (
            db.query(TransactionItem.product_id, func.sum(TransactionItem.quantity), func.sum(TransactionItem.subtotal))
            .join(Transaction, Transaction.id == TransactionItem.transaction_id)
            .filter(
                Transaction.tenant_id == tenant_id,
                Transaction.status == "completed",
                Transaction.created_at >= active_start
            )
            .group_by(TransactionItem.product_id)
            .all()
        )
        act_map = {p[0]: {"qty": int(p[1]), "rev": float(p[2])} for p in q_act}

        q_brk = (
            db.query(TransactionItem.product_id, func.sum(TransactionItem.quantity), func.sum(TransactionItem.subtotal))
            .join(Transaction, Transaction.id == TransactionItem.transaction_id)
            .filter(
                Transaction.tenant_id == tenant_id,
                Transaction.status == "completed",
                func.date(Transaction.created_at) >= brk_start,
                func.date(Transaction.created_at) <= brk_end
            )
            .group_by(TransactionItem.product_id)
            .all()
        )
        brk_map = {p[0]: {"qty": int(p[1]), "rev": float(p[2])} for p in q_brk}

        products = db.query(Product).filter(Product.tenant_id == tenant_id).all()

        student_restock = []
        hold_warnings = []
        stable_staples = []
        capital_saved_total = 0

        for p in products:
            a_data = act_map.get(p.id, {"qty": 0, "rev": 0.0})
            b_data = brk_map.get(p.id, {"qty": 0, "rev": 0.0})
            
            v_act = round(a_data["qty"] / max(1, act_distinct_days), 2)
            v_brk = round(b_data["qty"] / max(1, brk_distinct_days), 2)
            
            elasticity = round(v_act / max(v_brk, 0.05), 1)
            stock = p.stock or 0
            days_cover = round(stock / max(v_act, 0.1), 1)
            threshold_days = days_until_next if days_until_next else 45

            is_staple = (
                p.category == "Sembako" or
                any(k in p.item_name.lower() for k in ["beras", "minyak", "gula", "telur", "tepung", "garam", "sunlight", "wipol", "sarden", "roma", "baygon"])
            )

            # 1. Kebutuhan Pokok Warga Lokal (Stabil)
            if is_staple:
                stab_score = round(max(60.0, min(98.0, 100.0 - abs(elasticity - 2.5) * 8)), 1)
                stable_staples.append({
                    "id": p.id,
                    "name": p.item_name,
                    "category": p.category or "Sembako",
                    "stock": stock,
                    "price": p.price,
                    "daily_velocity_active": v_act,
                    "daily_velocity_break": v_brk,
                    "stability_score": stab_score,
                    "days_cover": days_cover,
                    "status": "Stok Stabil (Tahan Musim)",
                    "image_url": p.image_url
                })
            else:
                # 2. Produk Musiman Favorit Mahasiswa (Mie, Kopi, Air, Mandi, Snack)
                needed_14d = math.ceil(v_act * 14)
                suggested_order = max(0, needed_14d - stock)
                
                # Cek apakah stok berlebih menjelang libur
                if stock >= 80 or days_cover >= 6.0:
                    deadstock_risk = "Tinggi" if days_cover > 8.0 or stock >= 120 else "Sedang"
                    savings = round(stock * p.price)
                    capital_saved_total += savings
                    hold_warnings.append({
                        "id": p.id,
                        "name": p.item_name,
                        "category": p.category or "Lainnya",
                        "stock": stock,
                        "price": p.price,
                        "daily_sales": v_act,
                        "days_cover": days_cover,
                        "days_until_holiday": threshold_days,
                        "risk_level": deadstock_risk,
                        "action": f"TAHAN BELI! Stok {stock} pcs cukup untuk {days_cover} hari ke depan.",
                        "capital_tied_up": savings,
                        "image_url": p.image_url
                    })

                priority = "Mendesak" if days_cover < 3.0 else ("Sedang" if days_cover < 6.0 else "Aman")
                student_restock.append({
                    "id": p.id,
                    "name": p.item_name,
                    "category": p.category or "Lainnya",
                    "stock": stock,
                    "price": p.price,
                    "daily_velocity_active": v_act,
                    "daily_velocity_break": v_brk,
                    "elasticity_ratio": elasticity,
                    "days_cover": days_cover,
                    "suggested_order_qty": suggested_order,
                    "priority": priority,
                    "image_url": p.image_url
                })

        student_restock.sort(key=lambda x: (0 if x["priority"] == "Mendesak" else (1 if x["priority"] == "Sedang" else 2), -x["daily_velocity_active"]))
        hold_warnings.sort(key=lambda x: (0 if x["risk_level"] == "Tinggi" else 1, -x["capital_tied_up"]))
        stable_staples.sort(key=lambda x: -x["daily_velocity_active"])

        return {
            "current_period": {
                "id": current_period.id if current_period else 0,
                "name": current_period.name if current_period else "Semester Ganjil 2026/2027",
                "phase_type": current_period.phase_type if current_period else "active",
                "start_date": current_period.start_date.isoformat() if current_period else "2026-09-01",
                "end_date": current_period.end_date.isoformat() if current_period else "2026-12-20",
                "total_days": total_days,
                "elapsed_days": elapsed_days,
                "remaining_days": remaining_days,
                "current_week": current_week,
                "total_weeks": total_weeks,
                "progress_pct": progress_pct,
                "target_daily_revenue": target_rev,
                "today_actual_revenue": today_actual_rev,
                "today_trx_count": today_trx_count,
                "today_achievement_pct": today_achievement_pct,
                "notes": current_period.notes if current_period else ""
            },
            "next_period": {
                "id": next_period.id if next_period else None,
                "name": next_period.name if next_period else "Liburan Akhir Semester",
                "phase_type": next_period.phase_type if next_period else "short_break",
                "start_date": next_period.start_date.isoformat() if next_period else None,
                "days_until_next": days_until_next
            },
            "macro_comparison": {
                "avg_active_daily_revenue": avg_active_daily,
                "avg_break_daily_revenue": avg_break_daily,
                "ratio_multiplier": ratio_multiplier,
                "student_boost_pct": round(((avg_active_daily - avg_break_daily) / max(1, avg_break_daily)) * 100, 1)
            },
            "student_restock": student_restock[:20],
            "hold_warnings": hold_warnings[:20],
            "stable_staples": stable_staples[:20],
            "counts": {
                "student_items": len(student_restock),
                "hold_warnings": len(hold_warnings),
                "stable_staples": len(stable_staples),
                "capital_saved_total": capital_saved_total
            }
        }
    finally:
        db.close()



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
async def mini_generate_kasir_token(request: Request, current_user: AuthUser = Depends(require_roles(["owner"]))):
    """Owner generates a new kasir invitation token."""
    db = SessionLocal()
    token_str = "POS-KASIR-" + secrets.token_hex(4).upper()
    expires = datetime.now() + timedelta(hours=48)

    new_token = RegistrationToken(
        token=token_str,
        role="kasir",
        tenant_id=current_user.tenant_id,
        created_by=current_user.telegram_id,
        expires_at=expires,
    )
    db.add(new_token)
    db.commit()
    db.close()

    logger.info(f"Kasir token generated via MiniApp by owner={current_user.telegram_id}: {token_str}")

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
async def mini_deactivate_kasir(telegram_id: int, request: Request, current_user: AuthUser = Depends(require_roles(["owner"]))):
    """Owner deactivates a kasir from their tenant."""
    db = SessionLocal()
    kasir = db.query(BotUser).filter(
        BotUser.telegram_id == telegram_id,
        BotUser.tenant_id == current_user.tenant_id,
        BotUser.role == "kasir",
    ).first()

    if not kasir:
        db.close()
        raise HTTPException(status_code=404, detail="Kasir tidak ditemukan di toko kamu.")

    kasir.is_active = False
    db.commit()
    db.close()

    logger.info(f"Kasir {telegram_id} deactivated by owner={current_user.telegram_id}")
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
    if not tenant and not tenant_id:
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
async def mini_set_store_qris(req: StoreQrisRequest, current_user: AuthUser = Depends(require_roles(["owner"]))):
    """Menyimpan atau mengubah foto QRIS toko milik tenant (Khusus Owner)."""
    db = SessionLocal()
    tid = req.tenant_id or current_user.tenant_id or 1
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
async def mini_set_store_schedule(req: StoreScheduleRequest, current_user: AuthUser = Depends(require_roles(["owner"]))):
    """Atur status buka/tutup dan jam operasional toko (Khusus Owner)."""
    db = SessionLocal()
    tid = req.tenant_id or current_user.tenant_id or 1
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
    if tenant_id is not None:
        tid = tenant_id
    else:
        first_with_prod = db.query(Product.tenant_id).filter(Product.tenant_id != None).first()
        tid = first_with_prod[0] if first_with_prod else None

    # Base filter for tenant
    base_cond = (Product.tenant_id == tid) if tid is not None else (Product.tenant_id == None)

    # Categories (ambil dari tabel Category database + distinct produk)
    db_cats = db.query(Category).filter(
        (Category.tenant_id == tid) if tid is not None else (Category.tenant_id == None)
    ).order_by(Category.id).all()
    categories = [c.name for c in db_cats]

    cat_query = db.query(Product.category).distinct().filter(base_cond)
    for c in cat_query.all():
        if c[0] and c[0] not in categories:
            categories.append(c[0])

    if not categories:
        categories = ["Sembako", "Makanan", "Minuman", "Kebersihan", "Obat & Mandi"]

    # Products with sale counts for top-seller sorting
    prod_query = db.query(Product).filter(base_cond)
    if category and category != "Semua":
        prod_query = prod_query.filter(Product.category == category)
    if q and q.strip():
        search_term = f"%{q.strip()}%"
        prod_query = prod_query.filter(
            (Product.item_name.ilike(search_term)) | (Product.subcategory.ilike(search_term))
        )

    products = prod_query.order_by(Product.category, Product.item_name).all()

    # Count sales per product for popularity sorting
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    sales_count = db.query(
        TransactionItem.product_id,
        func.sum(TransactionItem.quantity).label("total_qty")
    ).join(
        Transaction, TransactionItem.transaction_id == Transaction.id
    ).filter(
        Transaction.tenant_id == tid,
        Transaction.created_at >= today_start,
        Transaction.status == "completed"
    ).group_by(TransactionItem.product_id).all()

    sales_map = {sc[0]: sc[1] or 0 for sc in sales_count}

    # Active Promotions
    today = datetime.now().date()
    promos = db.query(Promotion).filter(
        Promotion.is_active == True,
        Promotion.start_date <= today,
        Promotion.end_date >= today,
        Promotion.tenant_id == tid
    ).all()
    promo_map = {p.product_id: p for p in promos}

    items = []
    for p in products:
        promo = promo_map.get(p.id)
        discount_amount = 0
        discount_label = ""
        discount_price = p.price
        sales_today = sales_map.get(p.id, 0)

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
            "sales_today": sales_today,  # NEW: untuk sorting top sellers
        })

    db.close()
    return {
        "tenant_id": tid,
        "categories": categories,
        "products": items
    }


def _resolve_sale_products(db, items, tenant_id):
    """Load products from DB (not client prices) and strictly reject oversell / out-of-stock."""
    resolved = []
    for it in items:
        q = db.query(Product).filter(Product.id == it.id)
        if tenant_id:
            q = q.filter((Product.tenant_id == tenant_id) | (Product.tenant_id == None))
        prod = q.first()
        if not prod:
            raise HTTPException(status_code=400, detail=f"Produk tidak ditemukan: {it.name or it.id}")
        qty = int(it.quantity or 0)
        if qty <= 0:
            raise HTTPException(status_code=400, detail=f"Jumlah tidak valid untuk {prod.item_name}")
        curr_stock = prod.stock or 0
        if curr_stock <= 0:
            raise HTTPException(
                status_code=400,
                detail=f"Stok produk '{prod.item_name}' sudah HABIS (0). Transaksi tidak dapat diproses."
            )
        if curr_stock < qty:
            raise HTTPException(
                status_code=400,
                detail=f"Stok '{prod.item_name}' tidak mencukupi (diminta: {qty}, sisa tersedia: {curr_stock})."
            )
        resolved.append((prod, qty))
    missing = find_insufficient_stock(db, {p.id: qty for p, qty in resolved})
    if missing:
        raise HTTPException(status_code=400, detail=format_stock_error(missing))
    return resolved


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

    try:
        resolved = _resolve_sale_products(db, req.items, tenant_id)
    except HTTPException:
        db.close()
        raise

    # Calculate totals from database prices
    subtotal = sum(prod.price * qty for prod, qty in resolved)
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

    for prod, qty in resolved:
        item_subtotal = prod.price * qty
        db.add(TransactionItem(
            transaction_id=new_trx.id,
            product_id=prod.id,
            product_name=prod.item_name,
            unit_price=prod.price,
            quantity=qty,
            discount_type=None,
            discount_value=0,
            discount_amount=0,
            subtotal=item_subtotal
        ))

    db.commit()

    # Cash/COD deduct now; QRIS waits until paid
    if not is_qris:
        apply_sale_stock(
            db, new_trx,
            notes=f"Pesanan Mini App ({req.delivery_type})",
            created_by=user_id,
        )
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
            new_trx.status = "cancelled"
            db.commit()
            db.close()
            raise HTTPException(
                status_code=502,
                detail="Gagal membuat QRIS. Silakan coba metode lain atau ulangi pesanan."
            )

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
        status = (res.get("status") or "").upper()
        if status in QRIS_PAID_STATUSES or res.get("is_paid"):
            settle_qris_paid(order_id, res.get("paid_at"))
        elif status in QRIS_DEAD_STATUSES:
            mark_qris_terminal(order_id, status)

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
    stored_sig = qris_trx.signature if qris_trx else None
    db.close()

    if not qris_trx:
        return {"status": False, "message": "Unknown order_id"}

    if not qris_service.validate_webhook_signature(stored_sig, incoming_sig, payload):
        raise HTTPException(status_code=403, detail="Invalid QRIS signature")

    if (qris_trx.status or "").upper() in QRIS_PAID_STATUSES:
        return {"status": True, "message": "Transaction already paid/processed"}

    if incoming_status in QRIS_DEAD_STATUSES:
        mark_qris_terminal(order_id, incoming_status)
        return {"status": True, "message": f"Marked {incoming_status}"}

    if incoming_status not in QRIS_PAID_STATUSES:
        return {"status": True, "message": f"Ignored status {incoming_status or 'EMPTY'}"}

    result = settle_qris_paid(order_id, payload.get("payment_date") or payload.get("paid_at"))
    if result.get("ok") and not result.get("already") and BOT_TOKEN and result.get("user_id"):
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                await client.post(
                    f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                    json={
                        "chat_id": result["user_id"],
                        "text": (
                            f"✅ *PEMBAYARAN QRIS TERVERIFIKASI!*\n\n"
                            f"Pesanan `{result.get('invoice_no')}` sebesar "
                            f"*Rp{result.get('grand_total') or 0:,}* telah berhasil dibayar.\n"
                            f"Silakan datang ke toko untuk mengambil pesanan Anda."
                        ),
                        "parse_mode": "Markdown"
                    }
                )
        except Exception as e:
            logger.error(f"Failed to notify user about paid webhook: {e}")

    return {"status": True, "message": "Webhook processed successfully"}


# ==============================================================================
# SALES CHART & ANALYTICS ENDPOINTS
# ==============================================================================

@app.get("/api/mini/sales-chart")
async def sales_chart_data(tenant_id: int | None = None, period: str = "today"):
    """
    Get sales data grouped by time periods for chart visualization.
    Periods: today, 24h, 1week, 1month, 6month, 1year
    """
    db = SessionLocal()
    tid = tenant_id or 1
    now = datetime.now()

    # Define time ranges based on period
    ranges = {
        "today": (now.replace(hour=0, minute=0, second=0, microsecond=0), now),
        "24h": (now - timedelta(days=1), now),
        "1week": (now - timedelta(days=7), now),
        "1month": (now - timedelta(days=30), now),
        "6month": (now - timedelta(days=180), now),
        "1year": (now - timedelta(days=365), now),
    }

    start_date, end_date = ranges.get(period, ranges["today"])

    # Query sales per day for the period
    sales_data = db.query(
        func.date(Transaction.created_at).label("date"),
        func.sum(Transaction.grand_total).label("total_sales"),
        func.count(Transaction.id).label("trx_count"),
        func.sum(TransactionItem.quantity).label("total_qty")
    ).join(
        TransactionItem, Transaction.id == TransactionItem.transaction_id
    ).filter(
        Transaction.tenant_id == tid,
        Transaction.status == "completed",
        Transaction.created_at >= start_date,
        Transaction.created_at <= end_date
    ).group_by(func.date(Transaction.created_at)).order_by("date").all()

    # Format chart data
    chart_data = []
    for row in sales_data:
        date_obj = row[0]
        if date_obj:
            date_str = date_obj.strftime("%d %b" if period in ["1week", "1month", "6month", "1year"] else "%H:%M")
        else:
            date_str = "Unknown"

        chart_data.append({
            "date": date_str,
            "sales": int(row[1] or 0),
            "transactions": int(row[2] or 0),
            "quantity": int(row[3] or 0)
        })

    # Calculate summary stats
    total_sales = sum(d["sales"] for d in chart_data)
    total_trx = sum(d["transactions"] for d in chart_data)
    avg_sale = total_sales // total_trx if total_trx > 0 else 0

    db.close()

    return {
        "period": period,
        "chart_data": chart_data,
        "summary": {
            "total_sales": total_sales,
            "total_transactions": total_trx,
            "avg_per_trx": avg_sale,
            "data_points": len(chart_data)
        }
    }


# ==============================================================================
# IN-STORE POS DIRECT CHECKOUT (Khusus Kasir di Toko)
# ==============================================================================

@app.post("/api/pos/checkout")
async def pos_direct_checkout(
    req: PosCheckoutRequest,
    current_user: AuthUser = Depends(require_roles(["owner", "kasir"]))
):
    """Kasir / Owner melakukan transaksi penjualan langsung di toko secara cepat."""
    if not req.items:
        raise HTTPException(status_code=400, detail="Keranjang belanja kosong.")

    db = SessionLocal()
    tenant_id = req.tenant_id or current_user.tenant_id or 1
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    store_name = tenant.store_name if tenant else "Toko Ciamis"

    try:
        resolved = _resolve_sale_products(db, req.items, tenant_id)
    except HTTPException:
        db.close()
        raise

    subtotal = sum(prod.price * qty for prod, qty in resolved)
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

    for prod, qty in resolved:
        db.add(TransactionItem(
            transaction_id=new_trx.id,
            product_id=prod.id,
            product_name=prod.item_name,
            unit_price=prod.price,
            quantity=qty,
            discount_type=None,
            discount_value=0,
            discount_amount=0,
            subtotal=prod.price * qty
        ))

    db.commit()

    if not is_qris:
        apply_sale_stock(
            db, new_trx,
            notes="Penjualan Langsung Kasir POS",
            created_by=req.user_id or 0,
        )
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
            new_trx.status = "cancelled"
            db.commit()
            db.close()
            raise HTTPException(
                status_code=502,
                detail="Gagal membuat QRIS. Transaksi dibatalkan, stok tidak dipotong."
            )

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
async def pos_void_transaction(
    invoice_no: str,
    current_user: AuthUser = Depends(require_roles(["owner"]))
):
    """Membatalkan/meretur transaksi kasir untuk mengembalikan stok (Khusus Hak Akses Owner)."""
    db = SessionLocal()
    trx = db.query(Transaction).filter(Transaction.invoice_no == invoice_no).first()
    if not trx:
        db.close()
        raise HTTPException(status_code=404, detail="Transaksi tidak ditemukan.")

    if (trx.status or "") in VOID_STATUSES:
        db.close()
        raise HTTPException(status_code=400, detail="Transaksi ini sudah pernah dibatalkan sebelumnya.")

    restore_sale_stock(
        db, trx,
        notes="Pembatalan Transaksi Kasir (Salah Pencet / Retur)",
        created_by=current_user.telegram_id,
    )
    trx.status = "voided"
    trx.voided_at = datetime.now()
    trx.void_reason = f"Dibatalkan oleh owner ({current_user.full_name or current_user.telegram_id})"
    db.commit()
    db.close()
    return {
        "success": True,
        "message": f"Transaksi {invoice_no} berhasil dibatalkan dan semua stok produk telah dikembalikan!"
    }


@app.post("/api/pos/transactions/{invoice_no}/restore")
async def pos_restore_transaction(
    invoice_no: str,
    current_user: AuthUser = Depends(require_roles(["owner"]))
):
    """Memulihkan transaksi yang sempat dibatalkan: status kembali lunas dan stok kembali terpotong (Khusus Hak Akses Owner)."""
    db = SessionLocal()
    trx = db.query(Transaction).filter(Transaction.invoice_no == invoice_no).first()
    if not trx:
        db.close()
        raise HTTPException(status_code=404, detail="Transaksi tidak ditemukan.")

    if (trx.status or "") not in VOID_STATUSES:
        db.close()
        raise HTTPException(status_code=400, detail="Transaksi ini sedang aktif (tidak dalam status batal).")

    apply_sale_stock(
        db, trx,
        notes="Pemulihan Transaksi Kasir (Stok Kembali Keambil)",
        created_by=current_user.telegram_id,
    )
    trx.status = "completed"
    trx.voided_at = None
    trx.void_reason = None
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
    tid = tenant_id or 2
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
    tid = tenant_id or 2
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
async def update_pos_order_status(
    trx_id: int,
    req: OrderStatusUpdateRequest,
    current_user: AuthUser = Depends(require_roles(["owner", "kasir"]))
):
    """Kasir / Owner memperbarui status pesanan online (misal: 'siap_diambil', 'completed', atau 'cancelled')."""
    db = SessionLocal()
    trx = db.query(Transaction).filter(Transaction.id == trx_id).first()
    if not trx:
        db.close()
        raise HTTPException(status_code=404, detail="Pesanan tidak ditemukan.")

    old_status = (trx.status or "").lower()
    new_status = (req.status or "").lower()

    # Restorasi stok barang jika kasir membatalkan pesanan online (Bug Retur Stok Fix)
    if new_status == "cancelled" and old_status != "cancelled":
        restored = restore_sale_stock(
            db, trx,
            notes=f"Pembatalan Pesanan Online #{trx.id} oleh {current_user.role}",
            created_by=current_user.telegram_id,
        )
        logger.info(f"Pesanan #{trx_id} dibatalkan oleh {current_user.telegram_id} ({current_user.role}). Stok diretur: {restored}")
    elif old_status == "cancelled" and new_status != "cancelled":
        # Jika kasir mengaktifkan kembali pesanan yang sebelumnya dibatalkan
        applied = apply_sale_stock(
            db, trx,
            notes=f"Reaktivasi Pesanan Online #{trx.id} oleh {current_user.role}",
            created_by=current_user.telegram_id,
        )
        logger.info(f"Pesanan #{trx_id} diaktifkan kembali oleh {current_user.telegram_id}. Stok dipotong ulang: {applied}")

    trx.status = new_status
    db.commit()

    # Kirim notifikasi bot Telegram ke pembeli jika status berubah
    status_label = {
        "siap_diambil": "🛍️ *PESANAN ANDA SUDAH SIAP DIAMBIL!*\n\nSilakan datang ke toko kelontong untuk mengambil pesanan Anda.",
        "completed": "✅ *PESANAN SELESAI / LUNAS!*\n\nTerima kasih telah berbelanja di Toko Ciamis.",
        "diproses": "⏳ *PESANAN SEDANG DISIAPKAN* oleh kasir toko.",
        "cancelled": "❌ *PESANAN DIBATALKAN* oleh pihak toko. Stok barang telah dikembalikan ke etalase toko."
    }.get(new_status, f"Status pesanan Anda kini: *{new_status}*")

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
    return {"success": True, "message": f"Status pesanan berhasil diubah menjadi '{new_status}'"}



# ==============================================================================
# PRODUCT MANAGEMENT ENDPOINTS (Owner & Kasir)
# ==============================================================================

@app.get("/api/mini/user-role")
async def mini_user_role(request: Request, user_id: int | None = None, role: str | None = None):
    """Detect current user's role: 'owner', 'kasir', or 'customer'."""
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    dev_role = request.headers.get("X-Dev-Role") or role
    if not dev_role and init_data:
        if "role=owner" in init_data or "dev_role=owner" in init_data:
            dev_role = "owner"
        elif "role=kasir" in init_data or "dev_role=kasir" in init_data:
            dev_role = "kasir"

    tg_user = None
    if init_data and "hash=" in init_data:
        try:
            tg_user = validate_telegram_init_data(init_data)
        except Exception:
            pass

    target_id = None
    if tg_user and tg_user.get("id"):
        target_id = tg_user.get("id")
    elif user_id:
        target_id = user_id

    role_val = "customer"
    tenant_id = None
    full_name = "Pelanggan"

    db = SessionLocal()
    if target_id:
        bot_user = db.query(BotUser).filter(
            BotUser.telegram_id == target_id,
            BotUser.is_active == True
        ).first()
        if bot_user:
            role_val = bot_user.role
            tenant_id = bot_user.tenant_id
            full_name = bot_user.full_name or "Kasir/Owner"
    elif dev_role:
        # Browser / standalone testing mode
        bot_user = db.query(BotUser).filter(
            BotUser.role == dev_role,
            BotUser.is_active == True
        ).first()
        if bot_user:
            role_val = bot_user.role
            tenant_id = bot_user.tenant_id
            full_name = bot_user.full_name or ("Kasir" if dev_role == "kasir" else "Owner")
        else:
            role_val = dev_role
            tenant_id = 1
            full_name = "Kasir" if dev_role == "kasir" else "Owner"
    db.close()

    return {
        "role": role_val,
        "tenant_id": tenant_id or 1,
        "full_name": full_name,
        "is_staff": role_val in ["owner", "kasir"]
    }


@app.post("/api/mini/product")
async def mini_create_product(
    req: ProductManageRequest,
    current_user: AuthUser = Depends(require_roles(["owner", "kasir"]))
):
    """Add a new product to store catalog (Owner & Kasir)."""
    db = SessionLocal()
    tid = req.tenant_id or current_user.tenant_id or 2

    clean_stock = max(0, min(int(req.stock or 0), 99999))
    clean_price = max(0, int(req.price or 0))
    clean_cat = (req.category or "Lainnya").strip()

    # Pastikan kategori tersimpan di tabel categories database
    if clean_cat:
        cat_exists = db.query(Category).filter(
            Category.tenant_id == tid,
            func.lower(Category.name) == clean_cat.lower()
        ).first()
        if not cat_exists:
            db.add(Category(tenant_id=tid, name=clean_cat, icon="📦"))
            db.commit()

    max_id = db.query(func.max(Product.id)).scalar() or 0
    new_id = max_id + 1

    new_prod = Product(
        id=new_id,
        category=clean_cat,
        subcategory=req.subcategory or clean_cat,
        item_name=req.item_name.strip(),
        price=clean_price,
        stock=clean_stock,
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
async def mini_update_product(
    product_id: int,
    req: ProductManageRequest,
    current_user: AuthUser = Depends(require_roles(["owner", "kasir"]))
):
    """Update an existing product (Owner & Kasir)."""
    db = SessionLocal()
    prod = db.query(Product).filter(Product.id == product_id).first()
    if not prod:
        db.close()
        raise HTTPException(status_code=404, detail="Produk tidak ditemukan.")

    clean_stock = max(0, min(int(req.stock or 0), 99999))
    clean_price = max(0, int(req.price or 0))
    clean_cat = (req.category or prod.category or "Lainnya").strip()

    tid = prod.tenant_id or req.tenant_id or current_user.tenant_id or 2

    # Pastikan kategori tersimpan di tabel categories database
    if clean_cat:
        cat_exists = db.query(Category).filter(
            Category.tenant_id == tid,
            func.lower(Category.name) == clean_cat.lower()
        ).first()
        if not cat_exists:
            db.add(Category(tenant_id=tid, name=clean_cat, icon="📦"))

    prod.item_name = req.item_name.strip()
    prod.category = clean_cat
    if req.subcategory:
        prod.subcategory = req.subcategory
    prod.price = clean_price
    prod.stock = clean_stock
    if req.image_url == "" or req.image_url is None:
        if req.image_url == "":
            prod.image_url = None
    else:
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
async def mini_delete_product(
    product_id: int,
    current_user: AuthUser = Depends(require_roles(["owner"]))
):
    """Delete a product from store catalog (Khusus Owner)."""
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


# ==============================================================================
# CATEGORY MANAGEMENT (Persist ke Database MySQL per Tenant)
# ==============================================================================

@app.get("/api/mini/categories")
async def mini_get_categories(tenant_id: int | None = None):
    """Ambil daftar kategori toko per tenant yang tersimpan di database MySQL."""
    db = SessionLocal()
    tid = tenant_id or 2

    cats = db.query(Category).filter(
        (Category.tenant_id == tid) | (Category.tenant_id == None)
    ).order_by(Category.id).all()

    # Jika database belum ada kategori untuk tenant ini, inisialisasi default categories
    if not cats:
        defaults = [
            ("Sembako", "🍚"),
            ("Makanan", "🍟"),
            ("Minuman", "🥤"),
            ("Kebersihan", "🧼"),
            ("Obat & Mandi", "💊")
        ]
        cats = []
        for name, icon in defaults:
            c = Category(tenant_id=tid, name=name, icon=icon)
            db.add(c)
            cats.append(c)
        db.commit()
        for c in cats:
            db.refresh(c)

    # Pastikan kategori dari produk yang ada di DB juga terdaftar di tabel categories
    existing_cat_names = {c.name.strip().lower(): c for c in cats}
    prod_cats = db.query(Product.category).filter(
        (Product.tenant_id == tid) | (Product.tenant_id == None)
    ).distinct().all()

    new_from_prods = False
    for pc in prod_cats:
        c_name = (pc[0] or "").strip()
        if c_name and c_name.lower() not in existing_cat_names:
            new_cat = Category(tenant_id=tid, name=c_name, icon="📦")
            db.add(new_cat)
            cats.append(new_cat)
            existing_cat_names[c_name.lower()] = new_cat
            new_from_prods = True
    if new_from_prods:
        db.commit()

    results = [{"id": c.id, "name": c.name, "icon": c.icon or "📦"} for c in cats]
    db.close()
    return {"categories": results}


@app.post("/api/mini/categories")
async def mini_create_category(
    req: CategoryManageRequest,
    current_user: AuthUser = Depends(require_roles(["owner", "kasir"]))
):
    """Tambah kategori baru ke database (meski belum ada produknya)."""
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Nama kategori tidak boleh kosong.")

    db = SessionLocal()
    tid = req.tenant_id or current_user.tenant_id or 2

    # Cek duplikat per tenant
    exists = db.query(Category).filter(
        Category.tenant_id == tid,
        func.lower(Category.name) == name.lower()
    ).first()
    if exists:
        db.close()
        raise HTTPException(status_code=400, detail=f"Kategori '{name}' sudah ada di database.")

    new_cat = Category(
        tenant_id=tid,
        name=name,
        icon=req.icon or "📦"
    )
    db.add(new_cat)
    db.commit()
    db.refresh(new_cat)
    db.close()

    return {
        "success": True,
        "message": f"Kategori '{name}' berhasil disimpan ke database!",
        "category": {
            "id": new_cat.id,
            "name": new_cat.name,
            "icon": new_cat.icon
        }
    }


@app.put("/api/mini/categories/{category_id}")
async def mini_update_category(
    category_id: int,
    req: CategoryManageRequest,
    current_user: AuthUser = Depends(require_roles(["owner", "kasir"]))
):
    """Ubah nama/icon kategori di database dan sinkronisasi produk terkait."""
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Nama kategori tidak boleh kosong.")

    db = SessionLocal()
    cat = db.query(Category).filter(Category.id == category_id).first()
    if not cat:
        db.close()
        raise HTTPException(status_code=404, detail="Kategori tidak ditemukan.")

    old_name = cat.name
    tid = cat.tenant_id or req.tenant_id or current_user.tenant_id or 2

    # Cek duplikat jika nama berubah
    if old_name.lower() != name.lower():
        exists = db.query(Category).filter(
            Category.tenant_id == tid,
            Category.id != category_id,
            func.lower(Category.name) == name.lower()
        ).first()
        if exists:
            db.close()
            raise HTTPException(status_code=400, detail=f"Kategori '{name}' sudah ada di database.")

    cat.name = name
    if req.icon:
        cat.icon = req.icon

    # Sinkronkan produk yang memakai kategori lama di tenant ini
    db.query(Product).filter(
        Product.tenant_id == tid,
        Product.category == old_name
    ).update({Product.category: name}, synchronize_session=False)

    db.commit()
    db.refresh(cat)
    db.close()

    return {
        "success": True,
        "message": f"Kategori berhasil diperbarui menjadi '{name}'!",
        "category": {
            "id": cat.id,
            "name": cat.name,
            "icon": cat.icon
        }
    }


@app.delete("/api/mini/categories/{category_id}")
async def mini_delete_category(
    category_id: int,
    tenant_id: int | None = None,
    current_user: AuthUser = Depends(require_roles(["owner"]))
):
    """Hapus kategori dari database (Khusus Owner)."""
    db = SessionLocal()
    cat = db.query(Category).filter(Category.id == category_id).first()
    if not cat:
        db.close()
        raise HTTPException(status_code=404, detail="Kategori tidak ditemukan.")

    cat_name = cat.name
    tid = cat.tenant_id or tenant_id or 2

    # Set kategori produk yang menggunakan kategori ini menjadi 'Lainnya'
    db.query(Product).filter(
        Product.tenant_id == tid,
        Product.category == cat_name
    ).update({Product.category: "Lainnya"}, synchronize_session=False)

    db.delete(cat)
    db.commit()
    db.close()

    return {
        "success": True,
        "message": f"Kategori '{cat_name}' berhasil dihapus dari database."
    }


@app.post("/api/mini/upload-image")
async def mini_upload_image(
    file: UploadFile = File(...),
    product_id: int | None = Form(None),
    current_user: AuthUser = Depends(require_roles(["owner", "kasir"]))
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
            # Also sync to same product name across tenants so customer & cashier always see it
            same_name_prods = db.query(Product).filter(Product.item_name == prod.item_name).all()
            for sp in same_name_prods:
                sp.image_url = image_rel_url
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
# STOCK MANAGEMENT: OCR FOTO CATATAN & SPREADSHEET (EXCEL/CSV)
# ==============================================================================
import base64
import io
try:
    import pandas as pd
except ImportError:
    pd = None
from openai import AsyncOpenAI
from config import OPENROUTER_API_KEY, OPENROUTER_CHAT_MODEL

class BatchProductItem(BaseModel):
    name: str
    category: str | None = "Sembako"
    price: int = 0
    stock: int = 100

class BatchProductRequest(BaseModel):
    tenant_id: int | None = 1
    items: list[BatchProductItem]


@app.post("/api/mini/stock/ocr-photo")
async def mini_stock_ocr_photo(
    file: UploadFile = File(...),
    current_user: AuthUser = Depends(require_roles(["owner", "kasir"]))
):
    """Membaca catatan stok / bon / tulisan tangan di kertas menggunakan AI Vision."""
    if not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File harus berupa gambar (JPG, PNG, dll).")
    
    contents = await file.read()
    b64_img = base64.b64encode(contents).decode("utf-8")
    media_type = file.content_type or "image/jpeg"
    
    prompt = """
Kamu adalah asisten kasir toko kelontong Indonesia yang sangat teliti.
Tolong baca dan analisa catatan kertas / tulisan tangan / faktur / bon barang masuk ini.
Ekstrak setiap item barang yang ada ke dalam format JSON array murni.

PENTING TENTANG STOK DAN HARGA (HINDARI ANOMALI):
- JANGAN TERTUKAR antara Qty/Kuantitas/Stok barang dengan Harga Satuan atau Total Rupiah.
  Contoh: 'Indomie 10 bks @ 3.500 = 35.000' -> stock: 10, price: 3500 (BUKAN stock: 35000).
- Kuantitas fisik toko kelontong umumnya bernilai 1 s/d 200 pcs. Jika melihat angka di atas 1000 (misal: 3500, 15000), itu adalah HARGA dalam Rupiah, BUKAN stok!
- stock: kuantitas/stok barang fisik dalam angka integer (default 10 jika tidak tertera di catatan).
- price: harga satuan jual dalam rupiah integer bulat.

Untuk setiap produk yang ditemukan, berikan field:
- name: nama produk yang jelas dan rapi (misal: "Beras Rojolele 5kg", "Telur Ayam Negeri 1kg", "Indomie Goreng", "Sabun Lifebuoy")
- category: pilih salah satu kategori yang paling cocok dari: "Sembako", "Makanan", "Minuman", "Kebersihan", "Obat & Mandi", atau "Lainnya"
- price: harga jual dalam angka integer bulat (jika tidak tertera atau tidak jelas di kertas, berikan 0 atau perkiraan wajar)
- stock: jumlah stok/kuantitas dalam angka integer (default 10 jika tidak tertera)

Jawab HANYA dalam format JSON array valid, contoh:
[
  {"name": "Beras Rojolele 5kg", "category": "Sembako", "price": 75000, "stock": 10},
  {"name": "Minyak Goreng 2L", "category": "Sembako", "price": 35000, "stock": 5}
]
Jangan tambahkan teks pembuka atau markdown lain, hanya JSON array.
"""
    try:
        client = AsyncOpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=OPENROUTER_API_KEY
        )
        res = await client.chat.completions.create(
            model=OPENROUTER_CHAT_MODEL,
            max_tokens=2500,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{b64_img}"}}
                ]
            }]
        )
        raw_text = res.choices[0].message.content.strip()
        if raw_text.startswith("```json"):
            raw_text = raw_text[7:]
        if raw_text.startswith("```"):
            raw_text = raw_text[3:]
        if raw_text.endswith("```"):
            raw_text = raw_text[:-3]
        raw_text = raw_text.strip()
        
        parsed = json.loads(raw_text)
        if not isinstance(parsed, list):
            parsed = [parsed]
        return {
            "success": True,
            "items": parsed,
            "count": len(parsed)
        }
    except Exception as e:
        logger.error(f"Error OCR photo: {e}")
        raise HTTPException(status_code=500, detail=f"Gagal memproses gambar catatan: {str(e)}")


@app.post("/api/mini/stock/save-batch")
async def mini_stock_save_batch(
    req: BatchProductRequest,
    current_user: AuthUser = Depends(require_roles(["owner", "kasir"]))
):
    """Menyimpan banyak produk sekaligus ke database hasil OCR atau input massal."""
    db = SessionLocal()
    tid = req.tenant_id or current_user.tenant_id or 1
    added_count = 0
    updated_count = 0
    
    for it in req.items:
        clean_name = it.name.strip()
        if not clean_name:
            continue

        clean_price = max(0, int(it.price or 0))
        clean_stock = max(0, int(it.stock or 0))

        # Pencegahan anomali stok: jika stok terisi angka ribuan dan harga kosong/0
        if clean_stock >= 1000 and clean_price == 0:
            clean_price = clean_stock
            clean_stock = 10
        elif clean_stock > 5000:
            clean_stock = min(clean_stock, 9999)

        cat_name = (it.category or "Sembako").strip()
        if cat_name:
            cat_exists = db.query(Category).filter(
                Category.tenant_id == tid,
                func.lower(Category.name) == cat_name.lower()
            ).first()
            if not cat_exists:
                db.add(Category(tenant_id=tid, name=cat_name, icon="📦"))

        existing = db.query(Product).filter(
            Product.tenant_id == tid,
            Product.item_name.ilike(clean_name)
        ).first()
        if existing:
            if clean_price > 0:
                existing.price = clean_price
            existing.stock = min(99999, (existing.stock or 0) + clean_stock)
            if cat_name:
                existing.category = cat_name
            updated_count += 1
        else:
            new_p = Product(
                item_name=clean_name,
                category=cat_name,
                price=clean_price,
                stock=clean_stock,
                tenant_id=tid,
                is_consignment=False
            )
            db.add(new_p)
            added_count += 1
    
    db.commit()
    db.close()
    return {
        "success": True,
        "message": f"Berhasil menyimpan {added_count} produk baru dan memperbarui {updated_count} produk!",
        "added": added_count,
        "updated": updated_count
    }


@app.get("/api/mini/stock/export-excel")
async def mini_stock_export_excel(tenant_id: int | None = 1):
    """Ekspor seluruh stok produk ke spreadsheet Excel (.xlsx) / template."""
    db = SessionLocal()
    tid = tenant_id or 2
    products = db.query(Product).filter(
        (Product.tenant_id == tid) | (Product.tenant_id == None)
    ).order_by(Product.category, Product.item_name).all()
    
    data = []
    if products:
        for p in products:
            data.append({
                "Nama Produk": p.item_name,
                "Kategori": p.category or "Umum",
                "Harga Jual": p.price or 0,
                "Stok": p.stock or 0
            })
    else:
        data = [
            {"Nama Produk": "Beras Rojolele 5kg", "Kategori": "Sembako", "Harga Jual": 75000, "Stok": 20},
            {"Nama Produk": "Minyak Goreng 2L", "Kategori": "Sembako", "Harga Jual": 36000, "Stok": 50},
            {"Nama Produk": "Indomie Goreng", "Kategori": "Makanan", "Harga Jual": 3500, "Stok": 100},
            {"Nama Produk": "Sabun Lifebuoy", "Kategori": "Kebersihan", "Harga Jual": 4500, "Stok": 40}
        ]
    db.close()
    
    df = pd.DataFrame(data)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name="Daftar Stok")
    buf.seek(0)
    
    filename = f"stok_toko_ciamis.xlsx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-cache"
        }
    )


def _infer_smart_category(name: str) -> str:
    lower = name.lower()
    if any(k in lower for k in ["beras", "telur", "gula", "tepung", "minyak", "terigu", "filma", "bimoli", "sembako"]):
        return "Sembako"
    if any(k in lower for k in ["mie", "indomie", "sedaap", "snack", "chitato", "biskuit", "roti", "makanan", "wafer", "permen"]):
        return "Makanan"
    if any(k in lower for k in ["kopi", "teh", "aqua", "minerale", "susu", "ultra", "pucuk", "jus", "minuman", "sirup"]):
        return "Minuman"
    if any(k in lower for k in ["sabun", "rinso", "soklin", "daia", "downy", "wipol", "baygon", "sunlight", "mama lemon", "pembersih", "kebersihan"]):
        return "Kebersihan"
    if any(k in lower for k in ["bodrex", "tolak angin", "obat", "paracetamol", "kayu putih", "pepsodent", "shampoo", "clear", "lifebuoy"]):
        return "Obat & Mandi"
    return "Lainnya"


@app.post("/api/mini/stock/import-excel")
async def mini_stock_import_excel(
    file: UploadFile = File(...),
    mode: str = Form("update"),  # "update" or "replace"
    tenant_id: int = Form(1),
    current_user: AuthUser = Depends(require_roles(["owner", "kasir"]))
):
    """Import spreadsheet (.xlsx / .csv) dengan opsi Update / Tambah atau Timpa Keseluruhan."""
    contents = await file.read()
    filename = file.filename or ""
    
    try:
        if filename.endswith(".csv"):
            df = pd.read_csv(io.BytesIO(contents))
        else:
            df = pd.read_excel(io.BytesIO(contents))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Gagal membaca file spreadsheet: {str(e)}")
    
    col_map = {}
    for col in df.columns:
        c_low = str(col).strip().lower()
        if any(k in c_low for k in ["nama barang", "nama produk", "nama item", "nama", "item", "produk", "product"]):
            if "name" not in col_map:
                col_map["name"] = col
        elif any(k in c_low for k in ["kategori", "category"]):
            if "category" not in col_map:
                col_map["category"] = col
        elif any(k in c_low for k in ["harga jual", "harga satuan", "harga", "price", "unit price", "jual"]):
            if "price" not in col_map:
                col_map["price"] = col
        elif any(k in c_low for k in ["stok fisik", "sisa stok", "stok", "stock", "kuantitas", "qty", "banyaknya"]):
            if "stock" not in col_map:
                col_map["stock"] = col

    # Fallback stok jika kolom bernama 'jumlah' murni (bukan jumlah harga/rupiah/bayar)
    if "stock" not in col_map:
        for col in df.columns:
            c_low = str(col).strip().lower()
            if "jumlah" in c_low and not any(k in c_low for k in ["harga", "rp", "total", "bayar", "biaya"]):
                col_map["stock"] = col
                break
            
    if "name" not in col_map:
        raise HTTPException(status_code=400, detail="Kolom 'Nama Produk' tidak ditemukan dalam spreadsheet.")
    
    db = SessionLocal()
    tid = tenant_id or 2
    
    if mode == "replace":
        db.query(Product).filter(Product.tenant_id == tid).delete()
        db.commit()
        
    added = 0
    updated = 0
    
    for _, row in df.iterrows():
        raw_name = str(row[col_map["name"]]).strip()
        if not raw_name or raw_name.lower() in ["nan", "none", "null"]:
            continue
            
        cat = None
        if "category" in col_map and pd.notna(row[col_map["category"]]):
            cat = str(row[col_map["category"]]).strip()
        if not cat or cat.lower() in ["nan", "none", "null", ""]:
            cat = _infer_smart_category(raw_name)

        # Pastikan kategori tersimpan di database
        if cat:
            cat_exists = db.query(Category).filter(
                Category.tenant_id == tid,
                func.lower(Category.name) == cat.lower()
            ).first()
            if not cat_exists:
                db.add(Category(tenant_id=tid, name=cat, icon="📦"))
            
        price = 0
        if "price" in col_map and pd.notna(row[col_map["price"]]):
            try:
                price = max(0, int(float(row[col_map["price"]])))
            except Exception:
                price = 0
                
        stock = 0
        if "stock" in col_map and pd.notna(row[col_map["stock"]]):
            try:
                raw_stock = float(row[col_map["stock"]])
                stock = max(0, int(raw_stock))
                # Deteksi anomali: tertukar harga vs stok
                if stock >= 1000 and price == 0:
                    price = stock
                    stock = 10
                elif stock > 5000:
                    stock = min(stock, 9999)
            except Exception:
                stock = 0
                
        if mode == "replace":
            new_p = Product(
                item_name=raw_name,
                category=cat,
                price=price,
                stock=stock,
                tenant_id=tid,
                is_consignment=False
            )
            db.add(new_p)
            added += 1
        else:
            existing = db.query(Product).filter(
                Product.tenant_id == tid,
                Product.item_name.ilike(raw_name)
            ).first()
            if existing:
                if price > 0:
                    existing.price = price
                existing.stock = stock
                if cat:
                    existing.category = cat
                updated += 1
            else:
                new_p = Product(
                    item_name=raw_name,
                    category=cat,
                    price=price,
                    stock=stock,
                    tenant_id=tid,
                    is_consignment=False
                )
                db.add(new_p)
                added += 1
                
    db.commit()
    db.close()
    
    mode_text = "Timpa Keseluruhan" if mode == "replace" else "Update / Tambah"
    return {
        "success": True,
        "mode": mode,
        "message": f"Import Excel berhasil [{mode_text}]! Ditambahkan: {added}, Diperbarui: {updated}",
        "added": added,
        "updated": updated,
        "total_processed": len(df)
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
