"""
migrate_products.py -- Database Migration Script for Multi-Tenant Products
=========================================================================
This script:
1. Adds tenant_id column to products table (nullable, with FK to tenants)
2. Creates a demo tenant if it doesn't exist
3. Assigns all existing products (220) to the demo tenant
4. Adds index for tenant_id filtering

RUN ONCE before deploying multi-tenant features.

Usage:
    python migrate_products.py
"""

import sys
import pymysql
from datetime import datetime

DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "",
    "database": "toko_kelontong",
    "charset": "utf8mb4",
}


def run_migration():
    print("=" * 60)
    print("  POS Bot -- Multi-Tenant Products Migration")
    print("=" * 60)
    print()

    conn = pymysql.connect(**DB_CONFIG)
    cursor = conn.cursor()

    try:
        print("[1/4] Adding tenant_id column to products table...")
        cursor.execute("""
            SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'products' AND COLUMN_NAME = 'tenant_id'
        """, (DB_CONFIG["database"],))
        if not cursor.fetchone()[0]:
            cursor.execute("""
                ALTER TABLE products
                ADD COLUMN tenant_id INT NULL DEFAULT NULL
                AFTER item_name,
                ADD CONSTRAINT fk_products_tenant
                    FOREIGN KEY (tenant_id) REFERENCES tenants(id)
            """)
            print("      [OK] Added column: tenant_id (FK to tenants)")
        else:
            print("      [SKIP] Column tenant_id already exists, skipping.")

        print()
        print("[2/4] Adding index on tenant_id...")
        cursor.execute("""
            SELECT COUNT(*) FROM INFORMATION_SCHEMA.STATISTICS
            WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'products' AND INDEX_NAME = 'idx_products_tenant'
        """, (DB_CONFIG["database"],))
        if not cursor.fetchone()[0]:
            cursor.execute("""
                CREATE INDEX idx_products_tenant ON products(tenant_id)
            """)
            print("      [OK] Created index: idx_products_tenant")
        else:
            print("      [SKIP] Index idx_products_tenant already exists, skipping.")

        print()
        print("[3/4] Creating demo tenant...")
        cursor.execute("""
            SELECT id FROM tenants WHERE store_name = 'Toko Demo (Sample)'
        """)
        demo_tenant = cursor.fetchone()
        if not demo_tenant:
            cursor.execute("""
                INSERT INTO tenants (store_name, owner_id, is_active, created_at, updated_at)
                VALUES ('Toko Demo (Sample)', 0, 1, %s, %s)
            """, (datetime.now(), datetime.now()))
            demo_id = cursor.lastrowid
            print(f"      [OK] Created demo tenant with id={demo_id}")
        else:
            demo_id = demo_tenant[0]
            print(f"      [SKIP] Demo tenant already exists with id={demo_id}")

        print()
        print("[4/4] Assigning existing products to demo tenant...")
        cursor.execute("SELECT COUNT(*) FROM products WHERE tenant_id IS NULL;")
        null_count = cursor.fetchone()[0]
        if null_count > 0:
            cursor.execute(f"UPDATE products SET tenant_id = {demo_id} WHERE tenant_id IS NULL;")
            print(f"      [OK] Assigned {null_count} products to demo tenant")
        else:
            cursor.execute("SELECT COUNT(*) FROM products;")
            total = cursor.fetchone()[0]
            print(f"      [SKIP] All {total} products already assigned to a tenant")

        print()
        print("  -- Verification --")
        cursor.execute("SELECT COUNT(*) FROM products WHERE tenant_id = %s;", (demo_id,))
        demo_count = cursor.fetchone()[0]
        print(f"      [DATA] Demo tenant products: {demo_count}")
        cursor.execute("SELECT COUNT(*) FROM products WHERE tenant_id IS NOT NULL AND tenant_id != %s;", (demo_id,))
        other_count = cursor.fetchone()[0]
        print(f"      [DATA] Tenant-specific products: {other_count}")
        cursor.execute("SELECT COUNT(*) FROM products WHERE tenant_id IS NULL;")
        null_count = cursor.fetchone()[0]
        print(f"      [WARN] Unassigned products: {null_count}")

        conn.commit()
        print()
        print("=" * 60)
        print("  Migration COMPLETE!")
        print()
        print("  Next steps:")
        print("  1. Update codebase to use tenant_id in Product queries")
        print("  2. Update cache to be per-tenant")
        print("  3. Run seed_demo.py to create demo account")
        print("=" * 60)

    except Exception as e:
        conn.rollback()
        print()
        print(f"  Migration FAILED: {e}")
        print("  Database has been rolled back. No changes were made.")
        sys.exit(1)
    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    confirm = input(
        "\nWARNING: This will assign all existing products to a demo tenant.\n"
        "   Existing tenant-scoped products are unaffected.\n\n"
        "   Type 'YES' to continue: "
    ).strip()

    if confirm != "YES":
        print("   Migration cancelled.")
        sys.exit(0)

    run_migration()
