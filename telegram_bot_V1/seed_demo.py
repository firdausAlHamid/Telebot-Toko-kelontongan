"""
seed_demo.py -- Create demo tenant with sample products
======================================================
Run this to create a demo account for testing.
"""

from datetime import datetime, timedelta
from sqlalchemy import func
from database import SessionLocal, Tenant, BotUser, Product, RegistrationToken
from products import master_products
from sku_service import generate_unique_sku


def seed_demo():
    db = SessionLocal()
    
    # Create demo tenant
    demo_tenant = db.query(Tenant).filter(
        Tenant.store_name == "Toko Demo (Sample)"
    ).first()
    
    if not demo_tenant:
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
    
    # Ensure demo registration token exists and is usable
    demo_token_str = f"POS-OWNER-DEMO{demo_tenant.id:04d}"
    demo_tok = db.query(RegistrationToken).filter(
        RegistrationToken.token == demo_token_str
    ).first()
    if not demo_tok:
        demo_tok = RegistrationToken(
            token=demo_token_str,
            role="owner",
            tenant_id=demo_tenant.id,
            expires_at=datetime.now() + timedelta(days=30),
            is_used=False,
        )
        db.add(demo_tok)
        db.commit()
        print(f"[OK] Created demo token: {demo_token_str}")

    # Check existing products for demo tenant
    existing_count = db.query(Product).filter(Product.tenant_id == demo_tenant.id).count()
    if existing_count > 0:
        print(f"[INFO] Demo tenant already has {existing_count} products, skipping seed")
        db.close()
        print(f"\n[OK] Demo account ready!")
        print(f"   Tenant: {demo_tenant.store_name}")
        print(f"   Products: {existing_count}")
        print(f"   Token: {demo_token_str}")
        return

    # Add sample products without colliding with existing primary keys
    next_id = (db.query(func.max(Product.id)).scalar() or 0) + 1
    for item in master_products:
        sku_val = generate_unique_sku(db, item["item_name"], item["category"], demo_tenant.id)
        product = Product(
            id=next_id,
            sku=sku_val,
            category=item["category"],
            subcategory=item["subcategory"],
            item_name=item["item_name"],
            price=item["price"],
            stock=100,
            tenant_id=demo_tenant.id
        )
        db.add(product)
        next_id += 1
    
    store_name = demo_tenant.store_name
    db.commit()
    db.close()
    
    print(f"\n[OK] Demo account ready!")
    print(f"   Tenant: {store_name}")
    print(f"   Products: {len(master_products)}")
    print(f"   Token: {demo_token_str}")


if __name__ == "__main__":
    seed_demo()
