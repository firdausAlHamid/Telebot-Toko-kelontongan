"""
seed_demo.py -- Create demo tenant with sample products
======================================================
Run this to create a demo account for testing.
"""

from database import SessionLocal, Tenant, BotUser, Product
from products import master_products


def seed_demo():
    db = SessionLocal()
    
    # Create demo tenant
    demo_tenant = db.query(Tenant).filter(
        Tenant.store_name == "Toko Demo (Sample)"
    ).first()
    
    if not demo_tenant:
        from datetime import datetime
        demo_tenant = Tenant(
            store_name="Toko Demo (Sample)",
            owner_id=0,
            is_active=True,
            created_at=datetime.now(),
            updated_at=datetime.now()
        )
        db.add(demo_tenant)
        db.commit()
        db.refresh(demo_tenant)
        print(f"[OK] Created demo tenant: {demo_tenant.store_name} (id={demo_tenant.id})")
    else:
        print(f"[INFO] Demo tenant already exists: {demo_tenant.store_name} (id={demo_tenant.id})")
    
    # Create demo owner user
    demo_user = db.query(BotUser).filter(
        BotUser.telegram_id == 0
    ).first()
    
    if not demo_user:
        demo_user = BotUser(
            telegram_id=0,
            telegram_username="demo_user",
            full_name="Demo User",
            role="owner",
            tenant_id=demo_tenant.id,
            is_active=True
        )
        db.add(demo_user)
        db.commit()
        print(f"[OK] Created demo user (telegram_id=0)")
    else:
        print(f"[INFO] Demo user already exists")
    
    # Check existing products for demo tenant
    existing_count = db.query(Product).filter(Product.tenant_id == demo_tenant.id).count()
    if existing_count > 0:
        print(f"[INFO] Demo tenant already has {existing_count} products, skipping seed")
        db.close()
        print(f"\n[OK] Demo account ready!")
        print(f"   Tenant: {demo_tenant.store_name}")
        print(f"   Products: {existing_count}")
        print(f"   Token: POS-OWNER-DEMO{demo_tenant.id:04d}")
        return

    # Add sample products
    for item in master_products:
        product = Product(
            id=item["id"],
            category=item["category"],
            subcategory=item["subcategory"],
            item_name=item["item_name"],
            price=item["price"],
            stock=100,
            tenant_id=demo_tenant.id
        )
        db.add(product)
    
    db.commit()
    db.close()
    
    print(f"\n[OK] Demo account ready!")
    print(f"   Tenant: {demo_tenant.store_name}")
    print(f"   Products: {len(master_products)}")
    print(f"   Token: POS-OWNER-DEMO{demo_tenant.id:04d}")


if __name__ == "__main__":
    seed_demo()
