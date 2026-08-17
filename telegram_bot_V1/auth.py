"""
auth.py — Centralized Role-Based Access Control (RBAC)
=========================================================
Single source of truth for ALL permission checks in the bot.
No other file should implement its own role check.

Role hierarchy:   developer  >  vendor  >  kasir
TOTP 2FA is required for developer-level sensitive actions only.
"""

import logging
import io
import pyotp
import qrcode
from datetime import datetime, timedelta

from database import SessionLocal, BotUser, Tenant

logger = logging.getLogger(__name__)

# ── TOTP settings ──────────────────────────────────────────────────────────────
TOTP_ISSUER    = "TokoBangunan POS"
TOTP_INTERVAL  = 30          # seconds per code (RFC 6238 standard)
DEV_SESSION_SEC = 600        # developer session stays unlocked for 10 minutes after TOTP


# ==============================================================================
# ROLE QUERIES
# ==============================================================================

def _get_bot_user(telegram_id: int):
    """Return the active BotUser record or None."""
    db = SessionLocal()
    user = db.query(BotUser).filter(
        BotUser.telegram_id == telegram_id,
        BotUser.is_active == True
    ).first()
    db.close()
    return user


def get_role(telegram_id: int) -> str:
    """
    Returns the role string for a telegram_id.
    'unknown' means the user is not registered (no access to admin features).
    """
    user = _get_bot_user(telegram_id)
    return user.role if user else "unknown"


def is_kasir(telegram_id: int) -> bool:
    """True if role is kasir, vendor, OR developer (can use all POS features)."""
    return get_role(telegram_id) in ("kasir", "vendor", "developer")


def is_vendor(telegram_id: int) -> bool:
    """True if role is vendor OR developer (can manage staff & view all reports)."""
    return get_role(telegram_id) in ("vendor", "developer")


def is_developer(telegram_id: int) -> bool:
    """True ONLY if role is developer (can register new vendors, see system stats)."""
    return get_role(telegram_id) == "developer"


def get_tenant_id(telegram_id: int):
    """Return the tenant_id for a user, or None (developer has no tenant)."""
    user = _get_bot_user(telegram_id)
    return user.tenant_id if user else None


def sync_user_info(telegram_id: int, username: str | None, full_name: str | None):
    """
    Keep telegram_username and full_name up-to-date in DB.
    Called passively on /start — does nothing if user not registered.
    """
    db = SessionLocal()
    user = db.query(BotUser).filter(BotUser.telegram_id == telegram_id).first()
    if user:
        changed = False
        if username is not None and user.telegram_username != username:
            user.telegram_username = username
            changed = True
        if full_name is not None and user.full_name != full_name:
            user.full_name = full_name
            changed = True
        if changed:
            db.commit()
    db.close()


# ==============================================================================
# TOTP — Two-Factor Authentication (Developer Only)
# ==============================================================================

def _get_or_create_totp_secret(telegram_id: int) -> tuple[str, bool]:
    """
    Return (secret, is_new_secret).
    Creates and persists a new Base32 secret if one doesn't exist yet.
    """
    db = SessionLocal()
    user = db.query(BotUser).filter(BotUser.telegram_id == telegram_id).first()

    if not user:
        db.close()
        raise ValueError(f"No BotUser found for telegram_id={telegram_id}")

    if user.totp_secret:
        secret = user.totp_secret
        db.close()
        return secret, False

    secret = pyotp.random_base32()
    user.totp_secret = secret
    db.commit()
    db.close()
    return secret, True


def generate_totp_qr(telegram_id: int, display_name: str) -> tuple[bytes, str, bool]:
    """
    Generate TOTP QR code image for Google Authenticator / Authy.

    Returns:
        (qr_image_bytes: bytes, secret: str, is_first_time: bool)
    """
    secret, is_new = _get_or_create_totp_secret(telegram_id)
    totp = pyotp.TOTP(secret, interval=TOTP_INTERVAL)
    uri  = totp.provisioning_uri(name=display_name, issuer_name=TOTP_ISSUER)

    qr  = qrcode.make(uri)
    buf = io.BytesIO()
    qr.save(buf, format="PNG")
    buf.seek(0)

    return buf.getvalue(), secret, is_new


def verify_totp(telegram_id: int, code: str) -> bool:
    """
    Verify a 6-digit TOTP code.
    Accepts ±1 window (30 sec drift) to handle clock differences.
    Returns False if user has no TOTP secret set up.
    """
    db = SessionLocal()
    user = db.query(BotUser).filter(BotUser.telegram_id == telegram_id).first()
    db.close()

    if not user or not user.totp_secret:
        return False

    totp = pyotp.TOTP(user.totp_secret, interval=TOTP_INTERVAL)
    return totp.verify(code.strip(), valid_window=1)


def has_totp_setup(telegram_id: int) -> bool:
    """Return True if the developer already has a TOTP secret in DB."""
    db = SessionLocal()
    user = db.query(BotUser).filter(BotUser.telegram_id == telegram_id).first()
    db.close()
    return bool(user and user.totp_secret)


# ==============================================================================
# DEVELOPER SESSION  (stored in context.user_data, valid 10 min after TOTP)
# ==============================================================================

_SESSION_KEY = "dev_session_until"


def is_dev_session_active(context) -> bool:
    """True if developer already passed TOTP within the last 10 minutes."""
    expiry = context.user_data.get(_SESSION_KEY)
    return bool(expiry and datetime.now() < expiry)


def activate_dev_session(context):
    """Mark session as active for DEV_SESSION_SEC seconds."""
    context.user_data[_SESSION_KEY] = datetime.now() + timedelta(seconds=DEV_SESSION_SEC)


def deactivate_dev_session(context):
    """Explicitly lock the developer session."""
    context.user_data.pop(_SESSION_KEY, None)


def dev_session_remaining(context) -> int:
    """Return remaining session seconds (0 if inactive)."""
    expiry = context.user_data.get(_SESSION_KEY)
    if not expiry:
        return 0
    delta = expiry - datetime.now()
    return max(0, int(delta.total_seconds()))


# ==============================================================================
# USER MANAGEMENT
# ==============================================================================

def register_vendor(telegram_id: int, store_name: str, added_by: int) -> tuple[bool, str, int | None]:
    """
    Register a new vendor and create their Tenant record.

    Returns:
        (success, message, tenant_id or None)
    """
    db = SessionLocal()

    existing = db.query(BotUser).filter(BotUser.telegram_id == telegram_id).first()
    if existing:
        role = existing.role
        db.close()
        return False, f"User ini sudah terdaftar sebagai *{role}*.", None

    # Create tenant first
    tenant = Tenant(store_name=store_name, owner_id=telegram_id, is_active=True)
    db.add(tenant)
    db.flush()   # Populate tenant.id before commit

    vendor = BotUser(
        telegram_id=telegram_id,
        role="vendor",
        tenant_id=tenant.id,
        added_by=added_by,
        is_active=True,
    )
    db.add(vendor)
    db.commit()
    tenant_id = tenant.id
    db.close()

    logger.info(f"Vendor registered: telegram_id={telegram_id}, store='{store_name}', tenant_id={tenant_id}")
    return True, f"Vendor *{store_name}* berhasil didaftarkan.", tenant_id


def register_kasir(kasir_telegram_id: int, vendor_telegram_id: int) -> tuple[bool, str]:
    """
    Register a new kasir under a vendor's tenant.

    Returns:
        (success, message)
    """
    db = SessionLocal()

    vendor = db.query(BotUser).filter(
        BotUser.telegram_id == vendor_telegram_id,
        BotUser.role.in_(["vendor", "developer"]),
        BotUser.is_active == True,
    ).first()

    if not vendor or not vendor.tenant_id:
        db.close()
        return False, "Vendor / tenant tidak ditemukan."

    existing = db.query(BotUser).filter(BotUser.telegram_id == kasir_telegram_id).first()
    if existing:
        role = existing.role
        db.close()
        return False, f"User ini sudah terdaftar sebagai *{role}*."

    kasir = BotUser(
        telegram_id=kasir_telegram_id,
        role="kasir",
        tenant_id=vendor.tenant_id,
        added_by=vendor_telegram_id,
        is_active=True,
    )
    db.add(kasir)
    db.commit()
    db.close()

    logger.info(f"Kasir registered: telegram_id={kasir_telegram_id}, tenant_id={vendor.tenant_id}")
    return True, "Kasir berhasil didaftarkan."


def deactivate_user(target_telegram_id: int) -> tuple[bool, str]:
    """Soft-deactivate a user (is_active = False). Developer cannot be deactivated."""
    db = SessionLocal()
    user = db.query(BotUser).filter(BotUser.telegram_id == target_telegram_id).first()

    if not user:
        db.close()
        return False, "User tidak ditemukan."

    if user.role == "developer":
        db.close()
        return False, "Developer tidak bisa dinonaktifkan."

    user.is_active = False
    db.commit()
    db.close()

    logger.info(f"User deactivated: telegram_id={target_telegram_id}")
    return True, "User berhasil dinonaktifkan."


def list_users_by_role(role: str) -> list[dict]:
    """List all ACTIVE users with the given role, with their tenant info."""
    db = SessionLocal()
    rows = (
        db.query(BotUser, Tenant)
        .outerjoin(Tenant, BotUser.tenant_id == Tenant.id)
        .filter(BotUser.role == role, BotUser.is_active == True)
        .all()
    )
    db.close()

    return [
        {
            "telegram_id":       u.telegram_id,
            "telegram_username": u.telegram_username,
            "full_name":         u.full_name,
            "role":              u.role,
            "tenant_id":         u.tenant_id,
            "store_name":        t.store_name if t else "-",
            "created_at":        u.created_at,
        }
        for u, t in rows
    ]


def list_kasir_for_vendor(vendor_telegram_id: int) -> list[dict]:
    """List all active kasir belonging to the same tenant as the vendor."""
    db = SessionLocal()
    vendor = db.query(BotUser).filter(BotUser.telegram_id == vendor_telegram_id).first()

    if not vendor or not vendor.tenant_id:
        db.close()
        return []

    kasirs = (
        db.query(BotUser)
        .filter(
            BotUser.tenant_id == vendor.tenant_id,
            BotUser.role == "kasir",
            BotUser.is_active == True,
        )
        .all()
    )
    db.close()

    return [
        {
            "telegram_id":       k.telegram_id,
            "telegram_username": k.telegram_username,
            "full_name":         k.full_name,
            "created_at":        k.created_at,
        }
        for k in kasirs
    ]


# ==============================================================================
# BOOTSTRAP — Called once at bot startup
# ==============================================================================

def bootstrap_developer(telegram_id: int, username: str = "", full_name: str = ""):
    """
    Ensure the developer is registered in DB.
    Safe to call every startup — only acts when the record is missing or wrong.
    """
    if telegram_id == 0:
        logger.warning(
            "⚠️  DEVELOPER_TELEGRAM_ID is 0 in config.py — bootstrap skipped. "
            "Set your real Telegram ID!"
        )
        return

    db = SessionLocal()
    user = db.query(BotUser).filter(BotUser.telegram_id == telegram_id).first()

    if not user:
        db.add(BotUser(
            telegram_id=telegram_id,
            telegram_username=username or None,
            full_name=full_name or None,
            role="developer",
            is_active=True,
        ))
        db.commit()
        logger.info(f"✅ Developer bootstrapped: telegram_id={telegram_id}")
    elif user.role != "developer":
        # Safety: if somehow registered with wrong role, fix it
        user.role = "developer"
        db.commit()
        logger.info(f"✅ Developer role corrected for: telegram_id={telegram_id}")
    else:
        logger.info(f"ℹ️  Developer already in DB: telegram_id={telegram_id}")

    db.close()
