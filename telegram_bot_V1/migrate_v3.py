import os
from sqlalchemy import text
from database import engine

def migrate():
    print("Starting migration V3...")
    with engine.begin() as conn:
        try:
            # 1. Add tenant_id to promotions
            print("Altering table promotions...")
            conn.execute(text("ALTER TABLE promotions ADD COLUMN tenant_id INT REFERENCES tenants(id)"))
            conn.execute(text("UPDATE promotions SET tenant_id = 1"))
        except Exception as e:
            print(f"Skipping promotions alter (maybe already exists): {e}")

        try:
            # 2. Add tenant_id to store_schedules
            print("Altering table store_schedules...")
            conn.execute(text("ALTER TABLE store_schedules ADD COLUMN tenant_id INT REFERENCES tenants(id)"))
            conn.execute(text("UPDATE store_schedules SET tenant_id = 1"))
        except Exception as e:
            print(f"Skipping store_schedules alter (maybe already exists): {e}")

        # 3. Set owner of shop #1 to 1170387402
        print("Fixing owner for tenant #1...")
        res = conn.execute(text("UPDATE bot_users SET tenant_id = 1, role = 'owner', is_active = 1 WHERE telegram_id = '1170387402'"))
        if res.rowcount == 0:
            conn.execute(text('''INSERT INTO bot_users (telegram_id, telegram_username, full_name, role, is_active, tenant_id, created_at, updated_at) 
                                 VALUES ('1170387402', 'Diguz', 'Owner Diguz', 'owner', 1, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)'''))

        # Deactivate the eks-vendor
        conn.execute(text("UPDATE bot_users SET is_active = 0 WHERE telegram_id = '1122334455'"))

        # 4. Backfill transactions
        print("Backfilling transactions...")
        conn.execute(text("UPDATE transactions SET tenant_id = 1 WHERE tenant_id IS NULL OR tenant_id = 0"))

        # 5. Copy demo products to shop #1
        count_res = conn.execute(text("SELECT COUNT(*) FROM products WHERE tenant_id = 1")).scalar()
        if count_res == 0:
            print("Copying demo products to shop #1...")
            demo_products = conn.execute(text("SELECT name, description, price, stock, category, barcode, image_url, image_type, stock_type, status FROM products WHERE tenant_id IS NULL")).fetchall()
            if demo_products:
                insert_query = text('''INSERT INTO products (name, description, price, stock, category, barcode, image_url, image_type, stock_type, status, tenant_id, created_at, updated_at)
                                       VALUES (:name, :description, :price, :stock, :category, :barcode, :image_url, :image_type, :stock_type, :status, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)''')
                for p in demo_products:
                    conn.execute(insert_query, {
                        'name': p[0], 'description': p[1], 'price': p[2], 'stock': p[3], 'category': p[4],
                        'barcode': p[5], 'image_url': p[6], 'image_type': p[7], 'stock_type': p[8], 'status': p[9]
                    })
                print(f"Copied {len(demo_products)} products.")
        else:
            print(f"Shop #1 already has {count_res} products. Skipping copy.")

    print("Migration V3 completed successfully!")

if __name__ == '__main__':
    migrate()
