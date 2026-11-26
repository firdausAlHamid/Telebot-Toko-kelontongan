"""
sku_service.py — Unique SKU generation & duplicate/similar product name detection.
"""

from __future__ import annotations

import difflib
import re
import secrets
from typing import Any

from database import Product


def _clean_code_part(text: str | None, fallback: str, length: int = 3) -> str:
    """Extract uppercase alphanumeric prefix for readable SKU codes."""
    if not text:
        return fallback
    cleaned = re.sub(r"[^A-Za-z0-9]", "", text).upper()
    if not cleaned:
        return fallback
    return (cleaned[:length]).ljust(length, "X")


def generate_unique_sku(
    db,
    item_name: str,
    category: str | None = None,
    tenant_id: int | None = None,
) -> str:
    """Generate a guaranteed-unique SKU code for a product."""
    cat_part = _clean_code_part(category, "PRD", 3)
    name_part = _clean_code_part(item_name, "ITM", 3)
    prefix = f"SKU-{cat_part}-{name_part}"

    for _ in range(50):
        suffix = secrets.token_hex(2).upper()
        candidate = f"{prefix}-{suffix}"
        exists = db.query(Product.id).filter(Product.sku == candidate).first()
        if not exists:
            return candidate

    # Fallback with longer random suffix
    while True:
        suffix = secrets.token_hex(4).upper()
        candidate = f"{prefix}-{suffix}"
        exists = db.query(Product.id).filter(Product.sku == candidate).first()
        if not exists:
            return candidate


def _normalize_name(name: str) -> str:
    return " ".join((name or "").lower().split())


def find_similar_products(
    db,
    item_name: str,
    tenant_id: int | None = None,
    exclude_id: int | None = None,
    threshold: float = 0.72,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """
    Detect exact or similar product names in the same tenant (or global catalog).
    Returns a list of matching product dicts sorted by similarity descending.
    """
    norm_new = _normalize_name(item_name)
    if not norm_new:
        return []

    q = db.query(Product)
    if tenant_id is not None:
        q = q.filter((Product.tenant_id == tenant_id) | (Product.tenant_id == None))  # noqa: E711
    if exclude_id is not None:
        q = q.filter(Product.id != exclude_id)

    matches: list[dict[str, Any]] = []
    for p in q.all():
        norm_existing = _normalize_name(p.item_name or "")
        if not norm_existing:
            continue

        if norm_existing == norm_new:
            sim = 1.0
            match_type = "exact"
        else:
            sim = difflib.SequenceMatcher(None, norm_new, norm_existing).ratio()
            # Also catch substring containment for multi-word product names (e.g. "Beras Ramos" vs "Beras Ramos 5kg")
            if len(norm_new) >= 4 and len(norm_existing) >= 4 and (
                norm_new in norm_existing or norm_existing in norm_new
            ):
                sim = max(sim, 0.85)
            match_type = "similar"

        if sim >= threshold:
            matches.append({
                "id": p.id,
                "sku": p.sku,
                "item_name": p.item_name,
                "category": p.category,
                "price": p.price,
                "match_type": match_type,
                "similarity": round(sim, 2),
            })

    matches.sort(key=lambda x: x["similarity"], reverse=True)
    return matches[:limit]


def format_similarity_warning(similar_products: list[dict[str, Any]]) -> str | None:
    """Build a human-readable warning message for duplicate/similar product names."""
    if not similar_products:
        return None
    has_exact = any(p.get("match_type") == "exact" for p in similar_products)
    names = ", ".join(
        f"{p['item_name']} (SKU: {p.get('sku') or '-'})"
        for p in similar_products[:3]
    )
    if has_exact:
        return (
            f"⚠️ Peringatan Duplikasi: Nama produk sama persis dengan produk yang sudah ada ({names}). "
            "Produk tetap diberi SKU unik, pastikan bukan salah input/duplikat."
        )
    return (
        f"⚠️ Peringatan Kemiripan Nama: Ditemukan produk dengan nama mirip ({names}). "
        "Produk tetap diberi SKU unik, periksa kembali agar tidak terjadi duplikasi."
    )


def ensure_product_skus(db) -> int:
    """Backfill unique SKUs for any existing products missing one."""
    missing = db.query(Product).filter((Product.sku == None) | (Product.sku == "")).all()  # noqa: E711
    count = 0
    for p in missing:
        p.sku = generate_unique_sku(db, p.item_name or "Produk", p.category, p.tenant_id)
        count += 1
    if count:
        db.commit()
    return count
