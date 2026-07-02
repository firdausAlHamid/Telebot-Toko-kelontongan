from sqlalchemy import create_engine, Column, Integer, String
from sqlalchemy.orm import declarative_base, sessionmaker


# --- Database Foundation ---

Base = declarative_base()


# --- Table Model ---


class CartItem(Base):
    __tablename__ = "cart_items"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer)
    product_id = Column(Integer)
    quantity = Column(Integer, default=1)


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True)
    category = Column(String)
    subcategory = Column(String)
    item_name = Column(String)
    price = Column(Integer)


class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer)
    payment_method = Column(String)
    total_amount = Column(Integer)
    created_at = Column(String)



# --- Engine & Session ---

engine = create_engine("sqlite:///shop.db")
SessionLocal = sessionmaker(bind=engine)

# Create the table schema if it doesn't exist yet
Base.metadata.create_all(engine)
