import os
import sys
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api_server import app, AuthUser, get_current_user
from database import SessionLocal, Product, Tenant
from receipt_generator import generate_receipt_image
from sku_service import generate_unique_sku, find_similar_products, ensure_product_skus


client = TestClient(app)
BASE_DIR = Path(__file__).resolve().parent.parent


def _override_owner():
    return AuthUser(telegram_id=9276505257, role="owner", tenant_id=1, full_name="Owner Test")


def _override_kasir():
    return AuthUser(telegram_id=888888888, role="kasir", tenant_id=1, full_name="Kasir Test")


def test_unique_sku_and_duplicate_warning():
    """1. Every product gets a unique SKU and duplicate/similar names trigger warning/409."""
    app.dependency_overrides[get_current_user] = _override_owner
    db = SessionLocal()
    created_ids = []
    try:
        # First product
        res1 = client.post(
            "/api/mini/product",
            json={
                "item_name": "Produk Uji Unik Zx9182 500ml",
                "category": "Minuman",
                "price": 15000,
                "stock": 10,
                "tenant_id": 1,
                "allow_duplicate": False,
            },
        )
        assert res1.status_code == 200, res1.text
        d1 = res1.json()
        assert d1["product"]["sku"]
        created_ids.append(d1["product"]["id"])

        # Similar product with allow_duplicate=False -> 409 warning
        res2 = client.post(
            "/api/mini/product",
            json={
                "item_name": "Produk Uji Unik Zx9182",
                "category": "Minuman",
                "price": 15500,
                "stock": 5,
                "tenant_id": 1,
                "allow_duplicate": False,
            },
        )
        assert res2.status_code == 409, res2.text
        assert res2.json()["detail"]["similar_products"]

        # Similar product with allow_duplicate=True -> 200 with unique SKU + warning
        res3 = client.post(
            "/api/mini/product",
            json={
                "item_name": "Produk Uji Unik Zx9182",
                "category": "Minuman",
                "price": 15500,
                "stock": 5,
                "tenant_id": 1,
                "allow_duplicate": True,
            },
        )
        assert res3.status_code == 200, res3.text
        d3 = res3.json()
        assert d3["product"]["sku"]
        assert d3["product"]["sku"] != d1["product"]["sku"]
        assert d3["warning"]
        created_ids.append(d3["product"]["id"])

        # Duplicate custom SKU -> 400
        res4 = client.post(
            "/api/mini/product",
            json={
                "item_name": "Item Berbeda Total Qw4421",
                "category": "Minuman",
                "price": 5000,
                "stock": 1,
                "tenant_id": 1,
                "sku": d1["product"]["sku"],
            },
        )
        assert res4.status_code == 400

        # Check-duplicate endpoint
        chk = client.get("/api/mini/product/check-duplicate", params={"name": "Produk Uji Unik Zx9182", "tenant_id": 1})
        assert chk.status_code == 200
        assert chk.json()["has_similar"] is True
    finally:
        app.dependency_overrides.clear()
        if created_ids:
            db.query(Product).filter(Product.id.in_(created_ids)).delete(synchronize_session=False)
            db.commit()
        db.close()


def test_receipt_uses_telegram_not_whatsapp():
    """2. Receipt QR code is Telegram (no WhatsApp QR)."""
    src = (BASE_DIR / "receipt_generator.py").read_text(encoding="utf-8")
    assert "Hubungi Kami via Telegram" in src
    assert "https://t.me/" in src
    assert "wa.me" not in src
    assert "Hubungi Kami via WhatsApp" not in src

    img_io = generate_receipt_image(
        trx_no="INV-TEST-001",
        date_str="26 November 2026 22:00:00",
        cart_items=[(1, "Beras 5kg", 65000, 1)],
        total=65000,
        payment_method="TUNAI",
        telegram_username="tokociamis_bot",
    )
    data = img_io.getvalue()
    assert data.startswith(b"\x89PNG\r\n\x1a\n")


def test_dynamic_light_dark_mode_css():
    """5. Light/dark mode CSS handles inputs, selects, textareas, and options dynamically."""
    html = (BASE_DIR / "miniapp" / "dashboard.html").read_text(encoding="utf-8")
    assert "body.light-mode .custom-input" in html
    assert "body.light-mode select option" in html
    assert "color-scheme: light;" in html
    assert 'id="m-prod-cat" class="custom-input" style="background:#1c2738;"' not in html


def test_owner_can_generate_kasir_token():
    """6. Owner can generate kasir token; kasir cannot."""
    app.dependency_overrides[get_current_user] = _override_owner
    try:
        res_owner = client.post("/api/mini/generate-kasir-token")
        assert res_owner.status_code == 200, res_owner.text
        data = res_owner.json()
        assert data["success"] is True
        assert data["token"].startswith("POS-KASIR-")
    finally:
        app.dependency_overrides.clear()

    app.dependency_overrides[get_current_user] = _override_kasir
    try:
        res_kasir = client.post("/api/mini/generate-kasir-token")
        assert res_kasir.status_code == 403
    finally:
        app.dependency_overrides.clear()


def test_qris_photo_sync():
    """7. Store QRIS photo updates immediately and clears when deleted; frontend disables cache."""
    db = SessionLocal()
    tenant = db.query(Tenant).filter(Tenant.id == 1).first()
    orig_qris = tenant.qris_image_url if tenant else None
    db.close()

    app.dependency_overrides[get_current_user] = _override_owner
    try:
        res_set = client.post(
            "/api/mini/store-qris",
            json={"tenant_id": 1, "qris_image_url": "/uploads/test_qris_v2.png"},
        )
        assert res_set.status_code == 200
        assert res_set.json()["qris_image_url"] == "/uploads/test_qris_v2.png"

        info = client.get("/api/mini/store-info", params={"tenant_id": 1})
        assert info.status_code == 200
        assert info.json()["qris_image_url"] == "/uploads/test_qris_v2.png"

        # Restore
        client.post(
            "/api/mini/store-qris",
            json={"tenant_id": 1, "qris_image_url": orig_qris},
        )
    finally:
        app.dependency_overrides.clear()

    dash_html = (BASE_DIR / "miniapp" / "dashboard.html").read_text(encoding="utf-8")
    idx_html = (BASE_DIR / "miniapp" / "index.html").read_text(encoding="utf-8")
    assert "cache: 'no-store'" in dash_html
    assert "cache: 'no-store'" in idx_html
