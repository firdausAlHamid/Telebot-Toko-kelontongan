"""
Transaction Service — Business logic for transaction history, reporting, and void.
Separated from Telegram handlers following Single Responsibility Principle.
"""

import logging
from datetime import datetime, timedelta, date
from sqlalchemy import func, desc, case, extract
from database import SessionLocal, Transaction, TransactionItem, Product, StockMovement, QrisTransaction

logger = logging.getLogger(__name__)

VOID_STATUSES = ("voided", "void", "cancelled")
QRIS_PAID_STATUSES = ("PAID", "SUCCESS")
QRIS_DEAD_STATUSES = ("EXPIRED", "FAILED", "CANCELLED", "CANCEL")

# --- Indonesian locale helpers ---

BULAN_INDO = {
    1: "Januari", 2: "Februari", 3: "Maret", 4: "April",
    5: "Mei", 6: "Juni", 7: "Juli", 8: "Agustus",
    9: "September", 10: "Oktober", 11: "November", 12: "Desember"
}

HARI_INDO = {
    0: "Senin", 1: "Selasa", 2: "Rabu", 3: "Kamis",
    4: "Jumat", 5: "Sabtu", 6: "Minggu"
}


def format_datetime_indo(dt):
    """Format a datetime object to Indonesian locale (e.g. 'Sabtu, 19 Juli 2026 11:00')."""
    if dt is None:
        return "-"
    if isinstance(dt, str):
        # Handle legacy string dates
        return dt
    day_name = HARI_INDO.get(dt.weekday(), "")
    return f"{day_name}, {dt.day} {BULAN_INDO[dt.month]} {dt.year} {dt.strftime('%H:%M')}"


def format_date_indo(d):
    """Format a date object to Indonesian locale string (e.g. '19 Juli 2026')."""
    if d is None:
        return "-"
    return f"{d.day} {BULAN_INDO[d.month]} {d.year}"


def find_insufficient_stock(db, product_qty: dict):
    """Return list of {product_id, name, need, stock} when qty exceeds available stock."""
    missing = []
    for pid, qty in product_qty.items():
        prod = db.query(Product).filter(Product.id == pid).first()
        stock = (prod.stock or 0) if prod else 0
        name = prod.item_name if prod else f"Produk #{pid}"
        if not prod or stock < qty:
            missing.append({"product_id": pid, "name": name, "need": qty, "stock": stock})
    return missing


def format_stock_error(missing):
    if not missing:
        return "Stok tidak cukup."
    lines = ["Stok tidak cukup:"]
    for m in missing:
        lines.append(f"- {m['name']}: butuh {m['need']}, sisa {m['stock']}")
    return "\n".join(lines)


def save_line_items(db, trx, calc_items):
    """Persist cart calc items as TransactionItem rows."""
    for item in calc_items:
        db.add(TransactionItem(
            transaction_id=trx.id,
            product_id=item["product_id"],
            product_name=item["item_name"],
            unit_price=item["price"],
            quantity=item["qty"],
            discount_type=item.get("discount_type"),
            discount_value=item.get("discount_value") or 0,
            discount_amount=item.get("discount_amount") or 0,
            subtotal=item.get("final_subtotal", item.get("subtotal", 0)),
        ))


def _has_open_stock_out(db, invoice_no):
    """True if stock is currently deducted for this invoice (out after the last void)."""
    last_void = (
        db.query(StockMovement)
        .filter(StockMovement.reference == f"VOID-{invoice_no}")
        .order_by(StockMovement.id.desc())
        .first()
    )
    out_q = db.query(StockMovement).filter(
        StockMovement.movement_type == "out",
        StockMovement.reference.in_([invoice_no, f"RESTORE-{invoice_no}"]),
    )
    if last_void:
        out_q = out_q.filter(StockMovement.id > last_void.id)
    return out_q.first() is not None


def apply_sale_stock(db, trx, notes="Sale", created_by=None):
    """Deduct stock for a sale. Idempotent if stock is already deducted after the last void."""
    invoice_no = trx.invoice_no or f"INV-{trx.id:06d}"
    if _has_open_stock_out(db, invoice_no):
        return False

    had_void = (
        db.query(StockMovement)
        .filter(StockMovement.reference == f"VOID-{invoice_no}")
        .first()
    )
    ref = f"RESTORE-{invoice_no}" if had_void else invoice_no
    items = db.query(TransactionItem).filter(TransactionItem.transaction_id == trx.id).all()
    for it in items:
        prod = db.query(Product).filter(Product.id == it.product_id).first()
        if not prod:
            continue
        qty = it.quantity or 0
        prod.stock = max(0, (prod.stock or 0) - qty)
        db.add(StockMovement(
            product_id=prod.id,
            tenant_id=trx.tenant_id,
            movement_type="out",
            quantity=-qty,
            reference=ref,
            notes=notes,
            created_by=created_by if created_by is not None else trx.user_id,
        ))
    return True


def restore_sale_stock(db, trx, notes="Void", created_by=None):
    """Return stock for a voided sale. No-op if stock was never deducted (e.g. unpaid QRIS)."""
    invoice_no = trx.invoice_no or f"INV-{trx.id:06d}"
    if not _has_open_stock_out(db, invoice_no):
        return False

    items = db.query(TransactionItem).filter(TransactionItem.transaction_id == trx.id).all()
    for it in items:
        prod = db.query(Product).filter(Product.id == it.product_id).first()
        if not prod:
            continue
        qty = it.quantity or 0
        prod.stock = (prod.stock or 0) + qty
        db.add(StockMovement(
            product_id=prod.id,
            tenant_id=trx.tenant_id,
            movement_type="in",
            quantity=qty,
            reference=f"VOID-{invoice_no}",
            notes=notes,
            created_by=created_by if created_by is not None else trx.user_id,
        ))
    return True


def settle_qris_paid(order_id, paid_at=None):
    """
    Mark a QRIS order paid, complete the linked transaction, and deduct stock.
    Idempotent. Returns a result dict.
    """
    db = SessionLocal()
    try:
        qris_trx = db.query(QrisTransaction).filter(QrisTransaction.order_id == order_id).first()
        if not qris_trx:
            return {"ok": False, "reason": "not_found"}

        already = (qris_trx.status or "").upper() in QRIS_PAID_STATUSES
        qris_trx.status = "PAID"
        qris_trx.paid_at = paid_at or datetime.now().isoformat()

        trx = None
        if qris_trx.invoice_no:
            trx = db.query(Transaction).filter(Transaction.invoice_no == qris_trx.invoice_no).first()
            if trx and (trx.status or "") not in VOID_STATUSES:
                trx.status = "completed"
                apply_sale_stock(db, trx, notes="Sale (QRIS paid)", created_by=trx.user_id)

        db.commit()
        return {
            "ok": True,
            "already": already,
            "trx_id": trx.id if trx else None,
            "invoice_no": (trx.invoice_no if trx else qris_trx.invoice_no),
            "grand_total": (trx.grand_total if trx else qris_trx.total_amount) or 0,
            "user_id": trx.user_id if trx else None,
        }
    except Exception:
        db.rollback()
        logger.exception("Failed to settle QRIS order %s", order_id)
        return {"ok": False, "reason": "error"}
    finally:
        db.close()


def mark_qris_terminal(order_id, status="EXPIRED"):
    """Expire/cancel an unpaid QRIS order without counting it as revenue."""
    status = (status or "EXPIRED").upper()
    db = SessionLocal()
    try:
        qris_trx = db.query(QrisTransaction).filter(QrisTransaction.order_id == order_id).first()
        if not qris_trx:
            return {"ok": False, "reason": "not_found"}
        if (qris_trx.status or "").upper() in QRIS_PAID_STATUSES:
            return {"ok": False, "reason": "already_paid"}

        qris_trx.status = status
        trx = None
        if qris_trx.invoice_no:
            trx = db.query(Transaction).filter(Transaction.invoice_no == qris_trx.invoice_no).first()
            if trx and (trx.status or "") not in VOID_STATUSES:
                if (trx.status or "") == "pending":
                    restore_sale_stock(db, trx, notes=f"QRIS {status}", created_by=trx.user_id)
                    trx.status = "cancelled"
        db.commit()
        return {
            "ok": True,
            "invoice_no": qris_trx.invoice_no,
            "user_id": trx.user_id if trx else None,
        }
    except Exception:
        db.rollback()
        logger.exception("Failed to mark QRIS terminal %s", order_id)
        return {"ok": False, "reason": "error"}
    finally:
        db.close()


# =============================================================================
# TRANSACTION HISTORY
# =============================================================================

def get_transaction_history(user_id=None, limit=10, offset=0, status="completed", tenant_id=None):
    """
    Get transaction history, optionally filtered by user_id.

    Args:
        user_id: filter by user (None = all users / admin view)
        limit: max records to return
        offset: pagination offset
        status: filter by status (completed/voided/all)

    Returns:
        list of Transaction dicts, total_count
    """
    db = SessionLocal()

    query = db.query(Transaction)

    if user_id:
        query = query.filter(Transaction.user_id == user_id)

    if status != "all":
        if status in VOID_STATUSES:
            query = query.filter(Transaction.status.in_(VOID_STATUSES))
        else:
            query = query.filter(Transaction.status == status)

    if tenant_id:
        query = query.filter(Transaction.tenant_id == tenant_id)

    total_count = query.count()

    transactions = query.order_by(desc(Transaction.created_at)).offset(offset).limit(limit).all()

    result = []
    for trx in transactions:
        result.append({
            "id": trx.id,
            "invoice_no": trx.invoice_no or f"INV-{trx.id:06d}",
            "user_id": trx.user_id,
            "payment_method": trx.payment_method,
            "subtotal": trx.subtotal or trx.total_amount or 0,
            "total_discount": trx.total_discount or 0,
            "grand_total": trx.grand_total or trx.total_amount or 0,
            "cash_received": trx.cash_received,
            "cash_change": trx.cash_change,
            "status": trx.status or "completed",
            "created_at": trx.created_at,
            "created_at_str": format_datetime_indo(trx.created_at),
        })

    db.close()
    return result, total_count


def get_transaction_detail(transaction_id):
    """
    Get full transaction detail including line items.

    Returns:
        (transaction_dict, items_list) or (None, []) if not found
    """
    db = SessionLocal()

    trx = db.query(Transaction).filter(Transaction.id == transaction_id).first()
    if not trx:
        db.close()
        return None, []

    trx_dict = {
        "id": trx.id,
        "invoice_no": trx.invoice_no or f"INV-{trx.id:06d}",
        "user_id": trx.user_id,
        "payment_method": trx.payment_method,
        "subtotal": trx.subtotal or trx.total_amount or 0,
        "total_discount": trx.total_discount or 0,
        "grand_total": trx.grand_total or trx.total_amount or 0,
        "cash_received": trx.cash_received,
        "cash_change": trx.cash_change,
        "status": trx.status or "completed",
        "created_at": trx.created_at,
        "created_at_str": format_datetime_indo(trx.created_at),
        "voided_at": trx.voided_at,
        "void_reason": trx.void_reason,
    }

    items = db.query(TransactionItem).filter(
        TransactionItem.transaction_id == transaction_id
    ).all()

    items_list = []
    for item in items:
        items_list.append({
            "id": item.id,
            "product_id": item.product_id,
            "product_name": item.product_name,
            "unit_price": item.unit_price,
            "quantity": item.quantity,
            "discount_type": item.discount_type,
            "discount_value": item.discount_value,
            "discount_amount": item.discount_amount,
            "subtotal": item.subtotal,
        })

    db.close()
    return trx_dict, items_list


# =============================================================================
# VOID TRANSACTION
# =============================================================================

def void_transaction(transaction_id, reason="Dibatalkan oleh admin", tenant_id=None):
    """
    Void (soft-cancel) a transaction and restore stock if it was deducted.
    Only today's transactions can be voided.

    Returns:
        (success: bool, message: str)
    """
    db = SessionLocal()
    trx = db.query(Transaction).filter(Transaction.id == transaction_id).first()

    if not trx:
        db.close()
        return False, "Transaksi tidak ditemukan."

    if tenant_id and trx.tenant_id != tenant_id:
        db.close()
        return False, "Transaksi bukan dari toko ini."

    if (trx.status or "") in VOID_STATUSES:
        db.close()
        return False, "Transaksi ini sudah di-void sebelumnya."

    # Check if transaction is from today
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    if isinstance(trx.created_at, datetime) and trx.created_at < today_start:
        db.close()
        return False, "Hanya transaksi hari ini yang bisa di-void."

    restore_sale_stock(db, trx, notes=f"Void: {reason}", created_by=trx.user_id)
    trx.status = "voided"
    trx.voided_at = datetime.now()
    trx.void_reason = reason

    invoice_no = trx.invoice_no or f"INV-{trx.id:06d}"
    db.commit()
    db.close()

    logger.info(f"Voided transaction #{transaction_id}: {reason}")
    return True, f"Transaksi {invoice_no} berhasil di-void."


# =============================================================================
# SALES REPORTS
# =============================================================================

def get_daily_summary(target_date=None, tenant_id=None):
    """
    Get sales summary for a specific date.

    Returns:
        dict with: date, total_transactions, total_revenue, total_discount,
                   avg_transaction, payment_breakdown, voided_count, voided_amount
    """
    if target_date is None:
        target_date = date.today()

    db = SessionLocal()

    # Date range for query
    start_dt = datetime.combine(target_date, datetime.min.time())
    end_dt = start_dt + timedelta(days=1)

    query = db.query(Transaction).filter(
        Transaction.created_at >= start_dt,
        Transaction.created_at < end_dt,
        Transaction.status == "completed"
    )
    if tenant_id:
        query = query.filter(Transaction.tenant_id == tenant_id)
    completed = query.all()

    total_transactions = len(completed)
    total_revenue = sum(t.grand_total or t.total_amount or 0 for t in completed)
    total_discount = sum(t.total_discount or 0 for t in completed)
    avg_transaction = total_revenue // total_transactions if total_transactions > 0 else 0

    # Payment method breakdown
    payment_breakdown = {}
    for t in completed:
        method = t.payment_method or "Tidak diketahui"
        if method not in payment_breakdown:
            payment_breakdown[method] = {"count": 0, "amount": 0}
        payment_breakdown[method]["count"] += 1
        payment_breakdown[method]["amount"] += t.grand_total or t.total_amount or 0

    # Voided transactions
    v_query = db.query(Transaction).filter(
        Transaction.created_at >= start_dt,
        Transaction.created_at < end_dt,
        Transaction.status.in_(VOID_STATUSES)
    )
    if tenant_id:
        v_query = v_query.filter(Transaction.tenant_id == tenant_id)
    voided = v_query.all()

    voided_count = len(voided)
    voided_amount = sum(t.grand_total or t.total_amount or 0 for t in voided)

    db.close()

    return {
        "date": target_date,
        "date_str": format_date_indo(target_date),
        "total_transactions": total_transactions,
        "total_revenue": total_revenue,
        "total_discount": total_discount,
        "avg_transaction": avg_transaction,
        "payment_breakdown": payment_breakdown,
        "voided_count": voided_count,
        "voided_amount": voided_amount,
    }


def get_period_summary(start_date, end_date, tenant_id=None):
    """
    Get sales summary for a date range.
    Useful for weekly/monthly reports.

    Returns:
        dict similar to daily_summary but for the period
    """
    db = SessionLocal()

    start_dt = datetime.combine(start_date, datetime.min.time())
    end_dt = datetime.combine(end_date, datetime.min.time()) + timedelta(days=1)

    query = db.query(Transaction).filter(
        Transaction.created_at >= start_dt,
        Transaction.created_at < end_dt,
        Transaction.status == "completed"
    )
    if tenant_id:
        query = query.filter(Transaction.tenant_id == tenant_id)
    completed = query.all()

    total_transactions = len(completed)
    total_revenue = sum(t.grand_total or t.total_amount or 0 for t in completed)
    total_discount = sum(t.total_discount or 0 for t in completed)
    avg_transaction = total_revenue // total_transactions if total_transactions > 0 else 0

    payment_breakdown = {}
    for t in completed:
        method = t.payment_method or "Tidak diketahui"
        if method not in payment_breakdown:
            payment_breakdown[method] = {"count": 0, "amount": 0}
        payment_breakdown[method]["count"] += 1
        payment_breakdown[method]["amount"] += t.grand_total or t.total_amount or 0

    v_query = db.query(Transaction).filter(
        Transaction.created_at >= start_dt,
        Transaction.created_at < end_dt,
        Transaction.status.in_(VOID_STATUSES)
    )
    if tenant_id:
        v_query = v_query.filter(Transaction.tenant_id == tenant_id)
    voided = v_query.all()

    db.close()

    return {
        "start_date": start_date,
        "end_date": end_date,
        "start_date_str": format_date_indo(start_date),
        "end_date_str": format_date_indo(end_date),
        "total_transactions": total_transactions,
        "total_revenue": total_revenue,
        "total_discount": total_discount,
        "avg_transaction": avg_transaction,
        "payment_breakdown": payment_breakdown,
        "voided_count": len(voided),
        "voided_amount": sum(t.grand_total or t.total_amount or 0 for t in voided),
    }


def get_top_products(start_date=None, end_date=None, limit=10, tenant_id=None):
    """
    Get best-selling products by quantity for a period.

    Returns:
        list of dicts: product_name, total_qty, total_revenue
    """
    if start_date is None:
        start_date = date.today()
    if end_date is None:
        end_date = start_date

    start_dt = datetime.combine(start_date, datetime.min.time())
    end_dt = datetime.combine(end_date, datetime.min.time()) + timedelta(days=1)

    db = SessionLocal()

    query = db.query(
        TransactionItem.product_name,
        func.sum(TransactionItem.quantity).label("total_qty"),
        func.sum(TransactionItem.subtotal).label("total_revenue")
    ).join(
        Transaction, TransactionItem.transaction_id == Transaction.id
    ).filter(
        Transaction.created_at >= start_dt,
        Transaction.created_at < end_dt,
        Transaction.status == "completed"
    )
    
    if tenant_id:
        query = query.filter(Transaction.tenant_id == tenant_id)
        
    results = query.group_by(
        TransactionItem.product_name
    ).order_by(
        desc("total_qty")
    ).limit(limit).all()

    db.close()

    return [
        {
            "product_name": r.product_name,
            "total_qty": r.total_qty,
            "total_revenue": r.total_revenue,
        }
        for r in results
    ]
