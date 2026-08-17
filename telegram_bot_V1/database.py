from sqlalchemy import (
    create_engine, Column, Integer, String, BigInteger,
    Date, DateTime, Boolean, ForeignKey
)
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime


# --- Database Foundation ---

Base = declarative_base()


# --- Table Models ---


class Tenant(Base):
    """One record per store/kiosk registered in the system."""
    __tablename__ = "tenants"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    store_name   = Column(String(255), nullable=False)      # e.g. "Toko Budi", "Kios Melati"
    owner_id     = Column(BigInteger, nullable=False)       # telegram_id of the vendor
    is_active    = Column(Boolean, default=True)
    created_at   = Column(DateTime, default=datetime.now)
    updated_at   = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class BotUser(Base):
    """
    Registered users with assigned roles.
    Auth is always based on telegram_id (permanent), never telegram_username (changeable).

    Role hierarchy:
        developer  > vendor  > kasir
    """
    __tablename__ = "bot_users"

    id                 = Column(Integer, primary_key=True, autoincrement=True)
    telegram_id        = Column(BigInteger, unique=True, nullable=False)   # Immutable Telegram user ID
    telegram_username  = Column(String(100), nullable=True)               # For display only (@username)
    full_name          = Column(String(255), nullable=True)               # Display name
    role               = Column(String(20), nullable=False)               # developer / vendor / kasir
    tenant_id          = Column(Integer, ForeignKey("tenants.id"), nullable=True)  # NULL for developer
    is_active          = Column(Boolean, default=True)
    totp_secret        = Column(String(100), nullable=True)               # TOTP 2FA — developer only
    added_by           = Column(BigInteger, nullable=True)                # telegram_id of registrar
    created_at         = Column(DateTime, default=datetime.now)
    updated_at         = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class CartItem(Base):
    __tablename__ = "cart_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger)
    product_id = Column(Integer)
    quantity = Column(Integer, default=1)


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True)
    category = Column(String(100))
    subcategory = Column(String(100))
    item_name = Column(String(255))
    price = Column(Integer)


class Transaction(Base):
    """
    Transaction record — stores completed (or voided) sales.
    Phase 1 upgrade: added invoice_no, discount tracking, cash details, void support.
    """
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    invoice_no = Column(String(20), unique=True, nullable=True)   # INV-000001
    user_id = Column(BigInteger)
    payment_method = Column(String(50))

    # --- Amount breakdown ---
    total_amount = Column(Integer, nullable=True)          # LEGACY — kept for old data
    subtotal = Column(Integer, nullable=True)              # before discount
    total_discount = Column(Integer, default=0)            # total discount applied
    grand_total = Column(Integer, nullable=True)           # after discount (final)

    # --- Cash payment details ---
    cash_received = Column(Integer, nullable=True)         # money given by customer
    cash_change = Column(Integer, nullable=True)           # change returned

    # --- Status & Void ---
    status = Column(String(20), default="completed")       # completed / voided
    voided_at = Column(DateTime, nullable=True)
    void_reason = Column(String(255), nullable=True)

    created_at = Column(DateTime, default=datetime.now)    # FIX: was String(50)


class TransactionItem(Base):
    """Detail line-item per transaction — snapshot of what was purchased."""
    __tablename__ = "transaction_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    transaction_id = Column(Integer, ForeignKey("transactions.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    product_name = Column(String(255))       # snapshot nama produk saat beli
    unit_price = Column(Integer)             # snapshot harga satuan saat beli
    quantity = Column(Integer)
    discount_type = Column(String(20), nullable=True)    # percentage / fixed_amount / null
    discount_value = Column(Integer, default=0)          # e.g. 10 (for 10%)
    discount_amount = Column(Integer, default=0)         # total potongan dalam Rupiah
    subtotal = Column(Integer)               # (unit_price * qty) - discount_amount


class Promotion(Base):
    """Promotion attached to a specific product with optional category targeting."""
    __tablename__ = "promotions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    target_category = Column(String(100), nullable=True)   # category to recommend TO
    discount_type = Column(String(20), nullable=False)      # "percentage" or "fixed_amount"
    discount_value = Column(Integer, nullable=False)         # e.g. 10 = 10% or Rp10,000
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)



class StoreSchedule(Base):
    """Schedule for store operational hours with reasons."""
    __tablename__ = "store_schedules"

    id = Column(Integer, primary_key=True, autoincrement=True)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    status = Column(String(20), nullable=False)        # "Buka" or "Tutup"
    operating_hours = Column(String(50), nullable=True)  # e.g., "08:00 - 17:00"
    reason = Column(String(255), nullable=True)          # e.g., "Libur Lebaran"
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)



# --- Engine & Session ---

engine = create_engine(
    "mysql+pymysql://root@localhost/toko_kelontong?charset=utf8mb4",
    pool_recycle=3600,
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(bind=engine)

# Create the table schema if it doesn't exist yet
Base.metadata.create_all(engine)


