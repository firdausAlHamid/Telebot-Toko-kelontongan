"""
Schedule Service — Business logic for store operational hours.
Separated from Telegram handlers following Single Responsibility Principle.
"""

import logging
from datetime import date
from database import SessionLocal, StoreSchedule
from promotion_service import format_date_indo

logger = logging.getLogger(__name__)

# =============================================================================
# STATUS CHECK
# =============================================================================

def get_today_schedule_status():
    """
    Get the operational status for today based on active schedules.
    Returns a formatted string message to be sent to the user.
    """
    today = date.today()
    db = SessionLocal()

    # Find an active schedule that covers today.
    # Order by ID descending so the most recently added schedule overrides older ones.
    schedule = db.query(StoreSchedule).filter(
        StoreSchedule.is_active == True,
        StoreSchedule.start_date <= today,
        StoreSchedule.end_date >= today
    ).order_by(StoreSchedule.id.desc()).first()

    db.close()

    if not schedule:
        return "🏪 *Jadwal Toko Hari Ini*\n\nKami buka 24 jam."

    if schedule.status == "Tutup":
        text = f"🏪 *Informasi Toko*\n\nMohon maaf, hari ini toko kami *TUTUP*."
        if schedule.reason:
            text += f"\n*Keterangan:* {schedule.reason}"
    else:
        text = f"🏪 *Jadwal Toko Hari Ini*\n\nToko *BUKA*."
        if schedule.operating_hours:
            text += f"\n*Jam Buka:* {schedule.operating_hours}"
        if schedule.reason:
            text += f"\n*Keterangan:* {schedule.reason}"

    return text


def get_upcoming_schedules_receipt():
    """Get a list of upcoming schedule strings for the printed receipt."""
    from datetime import timedelta
    today = date.today()
    future = today + timedelta(days=30)
    db = SessionLocal()

    schedules = db.query(StoreSchedule).filter(
        StoreSchedule.is_active == True,
        StoreSchedule.end_date >= today,
        StoreSchedule.start_date <= future
    ).order_by(StoreSchedule.start_date.asc()).limit(3).all()

    db.close()

    if not schedules:
        return ["Info Jadwal: Buka 24 Jam"]

    lines = ["Info Jadwal Mendatang:"]
    for s in schedules:
        date_str = f"{s.start_date.strftime('%d/%m')} - {s.end_date.strftime('%d/%m')}"
        if s.start_date == s.end_date:
            date_str = f"{s.start_date.strftime('%d/%m')}"
            
        if s.status == "Tutup":
            reason = f" ({s.reason})" if s.reason else ""
            lines.append(f"• {date_str}: TUTUP{reason}")
        else:
            lines.append(f"• {date_str}: {s.operating_hours or 'Buka'}")

    return lines


# =============================================================================
# CRUD OPERATIONS
# =============================================================================

def create_schedule(start_date, end_date, status, operating_hours=None, reason=None):
    """Create a new schedule period."""
    db = SessionLocal()
    
    schedule = StoreSchedule(
        start_date=start_date,
        end_date=end_date,
        status=status,
        operating_hours=operating_hours,
        reason=reason,
        is_active=True,
    )
    db.add(schedule)
    db.commit()
    schedule_id = schedule.id
    db.close()

    logger.info(f"Created store schedule #{schedule_id}")
    return schedule_id, "Jadwal operasional berhasil ditambahkan!"


def list_schedules(active_only=True):
    """List all store schedules."""
    db = SessionLocal()
    query = db.query(StoreSchedule)

    if active_only:
        query = query.filter(StoreSchedule.is_active == True)

    schedules = query.order_by(StoreSchedule.id.desc()).all()

    result = []
    today = date.today()

    for s in schedules:
        is_expired = s.end_date < today
        is_upcoming = s.start_date > today
        
        status_label = "🔴 Berakhir" if is_expired else ("🟡 Mendatang" if is_upcoming else "🟢 Berlangsung")

        result.append({
            "id": s.id,
            "start_date": s.start_date,
            "end_date": s.end_date,
            "start_date_str": format_date_indo(s.start_date),
            "end_date_str": format_date_indo(s.end_date),
            "status": s.status,
            "operating_hours": s.operating_hours or "-",
            "reason": s.reason or "-",
            "is_active": s.is_active,
            "status_label": status_label,
        })

    db.close()
    return result


def delete_schedule(schedule_id):
    """Soft-delete a schedule."""
    db = SessionLocal()
    schedule = db.query(StoreSchedule).filter(StoreSchedule.id == schedule_id).first()

    if not schedule:
        db.close()
        return False, "Jadwal tidak ditemukan."

    schedule.is_active = False
    db.commit()
    db.close()

    logger.info(f"Deleted (soft) schedule #{schedule_id}")
    return True, "Jadwal berhasil dihapus."


def update_schedule(schedule_id, **kwargs):
    """Update specific fields of a schedule."""
    db = SessionLocal()
    schedule = db.query(StoreSchedule).filter(StoreSchedule.id == schedule_id).first()

    if not schedule:
        db.close()
        return False, "Jadwal tidak ditemukan."

    for key, value in kwargs.items():
        if hasattr(schedule, key):
            setattr(schedule, key, value)

    db.commit()
    db.close()

    logger.info(f"Updated schedule #{schedule_id}: {kwargs}")
    return True, "Jadwal berhasil diupdate."
