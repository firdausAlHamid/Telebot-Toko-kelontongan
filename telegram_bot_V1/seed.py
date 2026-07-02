from database import SessionLocal, Product
from products import master_products

def seed_db():
    db = SessionLocal()
    
    # Check if we already have products
    existing_count = db.query(Product).count()
    if existing_count > 0:
        print(f"Database already has {existing_count} products. Clearing them...")
        db.query(Product).delete()
        db.commit()

    print(f"Seeding {len(master_products)} products into the database...")
    for item in master_products:
        product = Product(
            id=item["id"],
            category=item["category"],
            subcategory=item["subcategory"],
            item_name=item["item_name"],
            price=item["price"]
        )
        db.add(product)
    
    db.commit()
    db.close()
    print("Database seeding completed successfully.")

if __name__ == "__main__":
    seed_db()
