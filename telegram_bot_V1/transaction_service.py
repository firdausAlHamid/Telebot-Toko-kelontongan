"""
Transaction Service — Business logic for transaction history, reporting, and void.
Separated from Telegram handlers following Single Responsibility Principle.
"""

import logging
from datetime import datetime, timedelta, date
from sqlalchemy import func, desc, case, extract
from database import SessionLocal, Transaction, TransactionItem, Product

logger = logging.getLogger(__name__)

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


# =============================================================================
# TRANSACTION HISTORY
# =============================================================================

def get_transaction_history(user_id=None, limit=10, offset=0, status="completed"):
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
        query = query.filter(Transaction.status == status)

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

def void_transaction(transaction_id, reason="Dibatalkan oleh admin"):
    """
    Void (soft-cancel) a transaction.
    Only today's completed transactions can be voided.

    Returns:
        (success: bool, message: str)
    """
    db = SessionLocal()
    trx = db.query(Transaction).filter(Transaction.id == transaction_id).first()

    if not trx:
        db.close()
        return False, "Transaksi tidak ditemukan."

    if trx.status == "voided":
        db.close()
        return False, "Transaksi ini sudah di-void sebelumnya."

    # Check if transaction is from today
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    if isinstance(trx.created_at, datetime) and trx.created_at < today_start:
        db.close()
        return False, "Hanya transaksi hari ini yang bisa di-void."

    trx.status = "voided"
    trx.voided_at = datetime.now()
    trx.void_reason = reason

    db.commit()
    db.close()

    logger.info(f"Voided transaction #{transaction_id}: {reason}")
    return True, f"Transaksi {trx.invoice_no or f'INV-{trx.id:06d}'} berhasil di-void."


# =============================================================================
# SALES REPORTS
# =============================================================================

def get_daily_summary(target_date=None):
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

    # Completed transactions
    completed = db.query(Transaction).filter(
        Transaction.created_at >= start_dt,
        Transaction.created_at < end_dt,
        Transaction.status == "completed"
    ).all()

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
    voided = db.query(Transaction).filter(
        Transaction.created_at >= start_dt,
        Transaction.created_at < end_dt,
        Transaction.status == "voided"
    ).all()

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


def get_period_summary(start_date, end_date):
    """
    Get sales summary for a date range.
    Useful for weekly/monthly reports.

    Returns:
        dict similar to daily_summary but for the period
    """
    db = SessionLocal()

    start_dt = datetime.combine(start_date, datetime.min.time())
    end_dt = datetime.combine(end_date, datetime.min.time()) + timedelta(days=1)

    completed = db.query(Transaction).filter(
        Transaction.created_at >= start_dt,
        Transaction.created_at < end_dt,
        Transaction.status == "completed"
    ).all()

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

    voided = db.query(Transaction).filter(
        Transaction.created_at >= start_dt,
        Transaction.created_at < end_dt,
        Transaction.status == "voided"
    ).all()

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


def get_top_products(start_date=None, end_date=None, limit=10):
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

    results = db.query(
        TransactionItem.product_name,
        func.sum(TransactionItem.quantity).label("total_qty"),
        func.sum(TransactionItem.subtotal).label("total_revenue")
    ).join(
        Transaction, TransactionItem.transaction_id == Transaction.id
    ).filter(
        Transaction.created_at >= start_dt,
        Transaction.created_at < end_dt,
        Transaction.status == "completed"
    ).group_by(
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
