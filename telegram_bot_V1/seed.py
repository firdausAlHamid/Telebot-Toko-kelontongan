from database import SessionLocal, Product, Tenant
from products import master_products


def seed_db():
    db = SessionLocal()

    # Find or create demo tenant
    demo_tenant = db.query(Tenant).filter(Tenant.store_name == "Toko Demo (Sample)").first()
    if not demo_tenant:
        from datetime import datetime
        demo_tenant = Tenant(
            store_name="Toko Demo (Sample)",
            owner_id=0,
            is_active=True
        )
        db.add(demo_tenant)
        db.commit()
        db.refresh(demo_tenant)

    print(f"Seeding {len(master_products)} products into demo tenant (id={demo_tenant.id})...")
    
    # Clear existing products for this tenant
    db.query(Product).filter(Product.tenant_id == demo_tenant.id).delete()
    
    # Add new products
    for item in master_products:
        product = Product(
            id=item["id"],
            category=item["category"],
            subcategory=item["subcategory"],
            item_name=item["item_name"],
            price=item["price"],
            stock=100,  # Set default stock
            tenant_id=demo_tenant.id  # Scope to demo tenant
        )
        db.add(product)
    
    db.commit()
    db.close()
    print("Database seeding completed successfully.")


if __name__ == "__main__":
    seed_db()
