"""
auth.py — Centralized Role-Based Access Control (RBAC) — V2
=============================================================
Single source of truth for ALL permission checks in the bot.
No other file should implement its own role check.

Role hierarchy:   owner  >  kasir

Registration Flow:
  1. Owner registers via web app → receives an "owner token"
  2. Owner opens the bot → sends the token → account activated
  3. Owner generates "kasir tokens" via the Mini App dashboard
  4. Kasir opens the bot → sends the token → account activated

There is no in-bot registration. The bot only VALIDATES tokens.
"""

import logging
import secrets
from datetime import datetime, timedelta

from database import SessionLocal, BotUser, Tenant, RegistrationToken

logger = logging.getLogger(__name__)


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
    'unknown' means the user is not registered (no access).
    """
    user = _get_bot_user(telegram_id)
    return user.role if user else "unknown"


def is_kasir(telegram_id: int) -> bool:
    """True if role is kasir OR owner (owners can also use all kasir features)."""
    return get_role(telegram_id) in ("kasir", "owner")


def is_owner(telegram_id: int) -> bool:
    """True ONLY if role is owner (can manage staff & view full reports)."""
    return get_role(telegram_id) == "owner"


def is_registered(telegram_id: int) -> bool:
    """True if the user has any active role (owner or kasir)."""
    return get_role(telegram_id) in ("owner", "kasir")


def get_tenant_id(telegram_id: int):
    """Return the tenant_id for a user, or None."""
    user = _get_bot_user(telegram_id)
    return user.tenant_id if user else None


def get_store_name(telegram_id: int) -> str | None:
    """Return the store name for a user's tenant, or None."""
    tenant_id = get_tenant_id(telegram_id)
    if not tenant_id:
        return None
    db = SessionLocal()
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    db.close()
    return tenant.store_name if tenant else None


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
# TOKEN VALIDATION — Core Auth Function
# ==============================================================================

def validate_and_activate_token(
    telegram_id: int,
    token_str: str,
    username: str | None = None,
    full_name: str | None = None,
) -> tuple[bool, str]:
    """
    Validate a registration token submitted by a Telegram user.

    - Checks if token exists, is not expired, and is not already used.
    - Creates a BotUser with the correct role and tenant.
    - Marks the token as used.

    Returns:
        (success: bool, message: str)
    """
    db = SessionLocal()

    # Check if user already registered
    existing = db.query(BotUser).filter(BotUser.telegram_id == telegram_id).first()
    if existing and existing.is_active:
        db.close()
        role_label = "Pemilik Toko (Owner)" if existing.role == "owner" else "Kasir"
        return False, f"Akun kamu sudah aktif sebagai *{role_label}*. Tidak perlu input token lagi."

    # Find the token
    token = db.query(RegistrationToken).filter(
        RegistrationToken.token == token_str.strip().upper()
    ).first()

    if not token:
        db.close()
        return False, "❌ Token tidak ditemukan. Pastikan kamu menyalin token dengan benar."

    if token.is_used:
        db.close()
        return False, "❌ Token ini sudah pernah digunakan sebelumnya."

    if datetime.now() > token.expires_at:
        db.close()
        return False, "❌ Token sudah kadaluarsa. Minta token baru dari website atau owner kamu."

    # For kasir tokens, verify the tenant still exists and is active
    if token.role == "kasir" and token.tenant_id:
        tenant = db.query(Tenant).filter(
            Tenant.id == token.tenant_id,
            Tenant.is_active == True
        ).first()
        if not tenant:
            db.close()
            return False, "❌ Toko yang terkait dengan token ini sudah tidak aktif."

    # Activate the user
    user = BotUser(
        telegram_id=telegram_id,
        telegram_username=username,
        full_name=full_name,
        role=token.role,
        tenant_id=token.tenant_id,
        added_by=token.created_by,
        is_active=True,
        token_validated_at=datetime.now(),
    )
    db.add(user)

    # Mark token as used
    token.is_used = True
    token.used_by = telegram_id
    db.commit()

    store_name = None
    if token.tenant_id:
        tenant = db.query(Tenant).filter(Tenant.id == token.tenant_id).first()
        store_name = tenant.store_name if tenant else None

    db.close()

    role_label = "Pemilik Toko (Owner)" if token.role == "owner" else "Kasir"
    store_info = f" di toko *{store_name}*" if store_name else ""
    logger.info(f"Token activated: telegram_id={telegram_id}, role={token.role}, tenant_id={token.tenant_id}")
    return True, f"✅ Berhasil! Kamu sekarang terdaftar sebagai *{role_label}*{store_info}."


# ==============================================================================
# TOKEN GENERATION — Called by Owner (via Mini App / Bot)
# ==============================================================================

def generate_kasir_token(owner_telegram_id: int) -> tuple[bool, str]:
    """
    Generate a one-time kasir token for the owner's tenant.
    Token expires in 48 hours.

    Returns:
        (success: bool, token_string_or_error_message: str)
    """
    db = SessionLocal()

    owner = db.query(BotUser).filter(
        BotUser.telegram_id == owner_telegram_id,
        BotUser.role == "owner",
        BotUser.is_active == True
    ).first()

    if not owner or not owner.tenant_id:
        db.close()
        return False, "Akun owner atau tenant tidak ditemukan."

    token_str = "POS-KASIR-" + secrets.token_hex(4).upper()
    expires = datetime.now() + timedelta(hours=48)

    new_token = RegistrationToken(
        token=token_str,
        role="kasir",
        tenant_id=owner.tenant_id,
        created_by=owner_telegram_id,
        expires_at=expires,
    )
    db.add(new_token)
    db.commit()
    db.close()

    logger.info(f"Kasir token generated by owner={owner_telegram_id}, token={token_str}")
    return True, token_str


# ==============================================================================
# USER MANAGEMENT
# ==============================================================================

def deactivate_user(target_telegram_id: int) -> tuple[bool, str]:
    """Soft-deactivate a user (is_active = False)."""
    db = SessionLocal()
    user = db.query(BotUser).filter(BotUser.telegram_id == target_telegram_id).first()

    if not user:
        db.close()
        return False, "User tidak ditemukan."

    if user.role == "owner":
        db.close()
        return False, "Owner tidak bisa dinonaktifkan melalui bot. Hubungi admin sistem."

    user.is_active = False
    db.commit()
    db.close()

    logger.info(f"User deactivated: telegram_id={target_telegram_id}")
    return True, "User berhasil dinonaktifkan."


def list_kasir_for_owner(owner_telegram_id: int) -> list[dict]:
    """List all active kasir belonging to the same tenant as the owner."""
    db = SessionLocal()
    owner = db.query(BotUser).filter(BotUser.telegram_id == owner_telegram_id).first()

    if not owner or not owner.tenant_id:
        db.close()
        return []

    kasirs = (
        db.query(BotUser)
        .filter(
            BotUser.tenant_id == owner.tenant_id,
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
