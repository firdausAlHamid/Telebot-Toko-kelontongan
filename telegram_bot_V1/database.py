from sqlalchemy import (
    create_engine, Column, Integer, String, BigInteger,
    Date, DateTime, Boolean, ForeignKey
)
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime


# --- Database Foundation ---

Base = declarative_base()


# --- Table Models ---


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
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger)
    payment_method = Column(String(50))
    total_amount = Column(Integer)
    created_at = Column(String(50))


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


