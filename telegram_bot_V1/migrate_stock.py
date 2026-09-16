"""
migrate_stock.py — Add stock management columns to existing database.
Run once: python migrate_stock.py
"""
import pymysql

def migrate():
    conn = pymysql.connect(host='localhost', user='root', database='toko_kelontong')
    cursor = conn.cursor()

    # --- Product table: add stock columns ---
    alterations = [
        ("products", "stock", "INT DEFAULT 0 AFTER price"),
        ("products", "min_stock", "INT DEFAULT 0 AFTER stock"),
        ("products", "is_consignment", "TINYINT(1) DEFAULT 0 AFTER min_stock"),
        ("products", "consignment_supplier", "VARCHAR(255) NULL AFTER is_consignment"),
    ]

    for table, col, col_def in alterations:
        try:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_def}")
            print(f"  OK: Added {table}.{col}")
        except pymysql.err.OperationalError as e:
            if "1060" in str(e):  # Duplicate column
                print(f"  SKIP: {table}.{col} already exists")
            else:
                print(f"  ERROR: {e}")

    # --- Create stock_movements table ---
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS stock_movements (
            id INT AUTO_INCREMENT PRIMARY KEY,
            product_id INT NOT NULL,
            tenant_id INT NULL,
            movement_type VARCHAR(20) NOT NULL,
            quantity INT NOT NULL,
            reference VARCHAR(100) NULL,
            notes VARCHAR(255) NULL,
            created_by BIGINT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (product_id) REFERENCES products(id),
            FOREIGN KEY (tenant_id) REFERENCES tenants(id)
        )
    """)
    print("  OK: stock_movements table ready")

    conn.commit()
    conn.close()
    print("\n=== Migration complete! ===")

if __name__ == "__main__":
    migrate()
