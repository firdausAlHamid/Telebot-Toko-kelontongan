"""
Promotion Service — Business logic for discounts and recommendations.
Separated from Telegram handlers following Single Responsibility Principle.
"""

import logging
from datetime import date
from database import SessionLocal, Promotion, Product

logger = logging.getLogger(__name__)

# --- Indonesian locale helpers ---

BULAN_INDO = {
    1: "Januari", 2: "Februari", 3: "Maret", 4: "April",
    5: "Mei", 6: "Juni", 7: "Juli", 8: "Agustus",
    9: "September", 10: "Oktober", 11: "November", 12: "Desember"
}


def format_date_indo(d):
    """Format a date object to Indonesian locale string (e.g. '10 Juli 2026')."""
    return f"{d.day} {BULAN_INDO[d.month]} {d.year}"


# =============================================================================
# PROMO QUERIES
# =============================================================================

def get_active_promos_for_products(product_ids):
    """
    Batch query active promotions for multiple products.
    Returns dict keyed by product_id:
        {product_id: {"id", "discount_type", "discount_value", "start_date", "end_date", "target_category"}}
    """
    if not product_ids:
        return {}

    today = date.today()
    db = SessionLocal()

    promos = db.query(Promotion).filter(
        Promotion.product_id.in_(product_ids),
        Promotion.is_active == True,
        Promotion.start_date <= today,
        Promotion.end_date >= today,
    ).all()

    result = {}
    for p in promos:
        result[p.product_id] = {
            "id": p.id,
            "discount_type": p.discount_type,
            "discount_value": p.discount_value,
            "start_date": p.start_date,
            "end_date": p.end_date,
            "target_category": p.target_category,
        }

    db.close()
    return result


def get_active_promo_for_product(product_id):
    """Get active promotion for a single product. Returns dict or None."""
    result = get_active_promos_for_products([product_id])
    return result.get(product_id)


# =============================================================================
# DISCOUNT CALCULATION
# =============================================================================

def calculate_discount(price, qty, promo):
    """
    Calculate discount for a line item.

    Args:
        price: unit price
        qty: quantity
        promo: dict from get_active_promos_for_products, or None

    Returns:
        (discount_amount, final_subtotal) tuple
    """
    subtotal = price * qty

    if promo is None:
        return 0, subtotal

    if promo["discount_type"] == "percentage":
        discount_per_unit = int(price * promo["discount_value"] / 100)
    elif promo["discount_type"] == "fixed_amount":
        discount_per_unit = min(promo["discount_value"], price)
    else:
        return 0, subtotal

    discount_amount = discount_per_unit * qty
    final_subtotal = max(subtotal - discount_amount, 0)

    return discount_amount, final_subtotal


def calculate_cart_with_discounts(cart_items):
    """
    Process cart items and apply active promotions.

    Args:
        cart_items: list of tuples (product_id, item_name, price, qty)

    Returns:
        dict with keys: items, subtotal, total_discount, grand_total,
                        purchased_categories, discount_details
    """
    product_ids = [item[0] for item in cart_items]
    promo_lookup = get_active_promos_for_products(product_ids)

    # Get categories for purchased products
    db = SessionLocal()
    products = db.query(Product).filter(Product.id.in_(product_ids)).all()
    category_lookup = {p.id: p.category for p in products}
    db.close()

    items = []
    subtotal = 0
    total_discount = 0
    purchased_categories = set()
    discount_details = {}  # For receipt generator: {product_id: {"type", "value", "amount"}}

    for product_id, item_name, price, qty in cart_items:
        if product_id in category_lookup:
            purchased_categories.add(category_lookup[product_id])

        promo = promo_lookup.get(product_id)
        line_subtotal = price * qty
        discount_amount, final_subtotal = calculate_discount(price, qty, promo)

        subtotal += line_subtotal
        total_discount += discount_amount

        items.append({
            "product_id": product_id,
            "item_name": item_name,
            "price": price,
            "qty": qty,
            "subtotal": line_subtotal,
            "discount_type": promo["discount_type"] if promo else None,
            "discount_value": promo["discount_value"] if promo else None,
            "discount_amount": discount_amount,
            "final_subtotal": final_subtotal,
        })

        if discount_amount > 0 and promo:
            discount_details[product_id] = {
                "type": promo["discount_type"],
                "value": promo["discount_value"],
                "amount": discount_amount,
            }

    return {
        "items": items,
        "subtotal": subtotal,
        "total_discount": total_discount,
        "grand_total": subtotal - total_discount,
        "purchased_categories": purchased_categories,
        "discount_details": discount_details,
    }


# =============================================================================
# RECOMMENDATION ENGINE
# =============================================================================

def get_recommendations(purchased_categories, limit=2):
    """
    Get promo recommendations based on purchased categories.
    Finds promos that TARGET purchased categories, for products in DIFFERENT categories.
    Priority: highest discount first, then nearest expiry.

    Args:
        purchased_categories: set of category strings the customer bought
        limit: max number of recommendations

    Returns:
        list of dicts with: product_name, discount_text, end_date_str, etc.
    """
    if not purchased_categories:
        return []

    today = date.today()
    db = SessionLocal()

    promos = db.query(Promotion, Product).join(
        Product, Promotion.product_id == Product.id
    ).filter(
        Promotion.is_active == True,
        Promotion.start_date <= today,
        Promotion.end_date >= today,
        Promotion.target_category.in_(list(purchased_categories)),
    ).all()

    recommendations = []
    seen_products = set()

    for promo, product in promos:
        # Only recommend products from DIFFERENT categories than what was purchased
        if product.category in purchased_categories:
            continue

        # Skip duplicates
        if product.id in seen_products:
            continue
        seen_products.add(product.id)

        if promo.discount_type == "percentage":
            effective_pct = promo.discount_value
            discount_text = f"Diskon {promo.discount_value}%"
        else:
            effective_pct = (promo.discount_value / product.price * 100) if product.price > 0 else 0
            discount_text = f"Diskon Rp{promo.discount_value:,}"

        recommendations.append({
            "product_name": product.item_name,
            "product_category": product.category,
            "discount_text": discount_text,
            "end_date": promo.end_date,
            "end_date_str": format_date_indo(promo.end_date),
            "effective_pct": effective_pct,
        })

    db.close()

    # Sort: highest discount first, then nearest expiry
    recommendations.sort(key=lambda x: (-x["effective_pct"], x["end_date"]))

    return recommendations[:limit]


# =============================================================================
# CRUD OPERATIONS
# =============================================================================

def create_promotion(product_id, discount_type, discount_value, start_date, end_date, target_category=None):
    """
    Create a new promotion. Enforces max 1 active promo per product.
    Returns (promo_id, message) — promo_id is None on failure.
    """
    db = SessionLocal()

    # Check for existing active promo on this product
    existing = db.query(Promotion).filter(
        Promotion.product_id == product_id,
        Promotion.is_active == True,
    ).first()

    if existing:
        db.close()
        return None, "Produk ini sudah memiliki promosi aktif. Hapus dulu yang lama."

    promo = Promotion(
        product_id=product_id,
        target_category=target_category,
        discount_type=discount_type,
        discount_value=discount_value,
        start_date=start_date,
        end_date=end_date,
        is_active=True,
    )
    db.add(promo)
    db.commit()
    promo_id = promo.id
    db.close()

    logger.info(f"Created promotion #{promo_id} for product #{product_id}")
    return promo_id, "Promosi berhasil ditambahkan!"


def list_promotions(active_only=True):
    """List promotions with product info and status labels."""
    db = SessionLocal()

    query = db.query(Promotion, Product).join(
        Product, Promotion.product_id == Product.id
    )

    if active_only:
        query = query.filter(Promotion.is_active == True)

    promos = query.order_by(Promotion.id.desc()).all()

    result = []
    today = date.today()

    for promo, product in promos:
        is_expired = promo.end_date < today
        is_upcoming = promo.start_date > today

        if promo.discount_type == "percentage":
            disc_text = f"{promo.discount_value}%"
        else:
            disc_text = f"Rp{promo.discount_value:,}"

        status = "🔴 Expired" if is_expired else ("🟡 Upcoming" if is_upcoming else "🟢 Aktif")

        result.append({
            "id": promo.id,
            "product_id": promo.product_id,
            "product_name": product.item_name,
            "product_category": product.category,
            "target_category": promo.target_category or "-",
            "discount_type": promo.discount_type,
            "discount_value": promo.discount_value,
            "discount_text": disc_text,
            "start_date": promo.start_date,
            "end_date": promo.end_date,
            "start_date_str": format_date_indo(promo.start_date),
            "end_date_str": format_date_indo(promo.end_date),
            "is_active": promo.is_active,
            "status": status,
        })

    db.close()
    return result


def delete_promotion(promo_id):
    """Soft-delete a promotion (set is_active=False)."""
    db = SessionLocal()
    promo = db.query(Promotion).filter(Promotion.id == promo_id).first()

    if not promo:
        db.close()
        return False, "Promosi tidak ditemukan."

    promo.is_active = False
    db.commit()
    db.close()

    logger.info(f"Deleted (soft) promotion #{promo_id}")
    return True, "Promosi berhasil dihapus."


def update_promotion(promo_id, **kwargs):
    """Update specific fields of a promotion."""
    db = SessionLocal()
    promo = db.query(Promotion).filter(Promotion.id == promo_id).first()

    if not promo:
        db.close()
        return False, "Promosi tidak ditemukan."

    for key, value in kwargs.items():
        if hasattr(promo, key):
            setattr(promo, key, value)

    db.commit()
    db.close()

    logger.info(f"Updated promotion #{promo_id}: {kwargs}")
    return True, "Promosi berhasil diupdate."
