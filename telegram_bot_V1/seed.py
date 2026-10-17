from database import SessionLocal, Product, Tenant, BotUser
from products import master_products
from datetime import datetime

def seed_db():
    db = SessionLocal()
    try:
        # ── Step 1: Create default tenant if not exists ──
        default_tenant = db.query(Tenant).filter(Tenant.id == 1).first()
        if not default_tenant:
            default_tenant = Tenant(
                id=1,
                store_name="Toko Kelontong Demo",
                owner_id=123456789,  # dummy telegram_id
                is_active=True
            )
            db.add(default_tenant)
            print("[OK] Created default tenant: 'Toko Kelontong Demo'")

        # ── Step 2: Clear existing products (cascade delete related tables first) ──
        from database import Promotion, TransactionItem, CartItem, StockMovement
        existing_count = db.query(Product).count()
        if existing_count > 0:
            print(f"[DELETE] Clearing {existing_count} existing products...")
            # Delete related records first to avoid FK constraint errors
            db.query(StockMovement).delete()
            db.query(Promotion).delete()
            db.query(TransactionItem).delete()
            db.query(CartItem).delete()
            db.query(Product).delete()
            db.commit()
            print("[OK] All existing data cleared.")

        # ── Step 3: Seed products with tenant_id + initial stock ──
        print(f"[SEED] Seeding {len(master_products)} products into tenant_id=1...")
        for idx, item in enumerate(master_products, 1):
            product = Product(
                id=item["id"],
                category=item["category"],
                subcategory=item["subcategory"],
                item_name=item["item_name"],
                price=item["price"],
                tenant_id=1,  # IMPORTANT: attach to tenant_id=1
                stock=50 + (idx % 100),  # Varied initial stock for testing
                min_stock=10,
                is_consignment=False,
                consignment_supplier=None
            )
            db.add(product)

        db.commit()

        # ── Step 4: Verify seeding ──
        total = db.query(Product).filter(Product.tenant_id == 1).count()
        categories = db.query(Product.category).filter(Product.tenant_id == 1).distinct().count()
        print(f"\n[SUCCESS] Database seeding completed!")
        print(f"   Total products: {total}")
        print(f"   Categories: {categories}")

        # Show category breakdown
        categories_list = db.query(Product.category).filter(Product.tenant_id == 1).distinct().all()
        for cat_tuple in categories_list:
            cat = cat_tuple[0]
            count = db.query(Product).filter(Product.category == cat, Product.tenant_id == 1).count()
            print(f"   - {cat}: {count} produk")

    except Exception as e:
        print(f"[ERROR] Error during seeding: {e}")
        db.rollback()
        raise
    finally:
        db.close()

if __name__ == "__main__":
    seed_db()
