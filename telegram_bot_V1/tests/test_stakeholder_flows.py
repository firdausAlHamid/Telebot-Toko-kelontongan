import os
import sys

from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api_server import app
from auth import (
    can,
    generate_kasir_token,
    get_role,
    get_tenant_id,
    is_registered,
    validate_and_activate_token,
)
from config import OWNER_TELEGRAM_ID
from database import BotUser, RegistrationToken, SessionLocal


client = TestClient(app)


def test_stakeholder_owner_kasir_customer_end_to_end():
    """Verify full Owner -> generate Kasir token -> Kasir activation -> Customer isolation."""
    test_kasir_id = 777666555
    test_other_id = 777666444
    test_customer_id = 666555444
    generated_token = None

    db = SessionLocal()
    # Clean up any leftover test users
    db.query(BotUser).filter(BotUser.telegram_id.in_([test_kasir_id, test_other_id])).delete(synchronize_session=False)
    db.commit()
    db.close()

    try:
        # 1. OWNER (configured OWNER_TELEGRAM_ID)
        assert OWNER_TELEGRAM_ID > 0
        assert get_role(OWNER_TELEGRAM_ID) == "owner"
        assert is_registered(OWNER_TELEGRAM_ID) is True
        assert can(OWNER_TELEGRAM_ID, "panel:manage") is True
        owner_tid = get_tenant_id(OWNER_TELEGRAM_ID)
        assert owner_tid is not None

        # Owner generates a kasir token
        ok, token_or_err = generate_kasir_token(OWNER_TELEGRAM_ID)
        assert ok is True, token_or_err
        assert token_or_err.startswith("POS-KASIR-")
        generated_token = token_or_err

        # 2. KASIR (unregistered -> paste token -> active kasir)
        assert get_role(test_kasir_id) == "unknown"
        assert can(test_kasir_id, "trx:create") is False

        ok_act, msg_act = validate_and_activate_token(
            telegram_id=test_kasir_id,
            token_str=generated_token,
            username="kasir_uji",
            full_name="Kasir Uji",
        )
        assert ok_act is True, msg_act
        assert get_role(test_kasir_id) == "kasir"
        assert get_tenant_id(test_kasir_id) == owner_tid
        assert can(test_kasir_id, "trx:create") is True
        assert can(test_kasir_id, "panel:manage") is False

        # Token cannot be reused by another user
        ok_reuse, _ = validate_and_activate_token(
            telegram_id=test_other_id,
            token_str=generated_token,
            username="penyusup",
            full_name="Penyusup",
        )
        assert ok_reuse is False
        assert get_role(test_other_id) == "unknown"

        # 3. CUSTOMER (public catalog & store info, blocked from staff endpoints)
        assert get_role(test_customer_id) == "unknown"
        cat_res = client.get(f"/api/mini/catalog?tenant_id={owner_tid}")
        assert cat_res.status_code == 200
        products = cat_res.json()["products"]
        assert len(products) > 0
        assert all(p.get("sku") for p in products[:10])

        info_res = client.get(f"/api/mini/store-info?tenant_id={owner_tid}")
        assert info_res.status_code == 200

        # Unauthenticated customer cannot generate kasir token or add product
        assert client.post("/api/mini/generate-kasir-token").status_code in (401, 403)
        assert client.post(
            "/api/mini/product",
            json={"item_name": "Illegal", "category": "Sembako", "price": 1000, "stock": 1},
        ).status_code in (401, 403)
    finally:
        db = SessionLocal()
        db.query(BotUser).filter(BotUser.telegram_id.in_([test_kasir_id, test_other_id])).delete(synchronize_session=False)
        if generated_token:
            db.query(RegistrationToken).filter(RegistrationToken.token == generated_token).delete(synchronize_session=False)
        db.commit()
        db.close()
