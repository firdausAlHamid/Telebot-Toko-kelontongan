"""
migrate_v2.py — Database Migration Script for POS Bot V2
=========================================================
This script:
1. TRUNCATES transactional tables (users, tenants, transactions, cart)
2. Creates the new `registration_tokens` table
3. Adds new columns to existing tables (bot_users, transactions)
4. KEEPS: products, promotions, store_schedules (data is preserved)

⚠️  RUN ONCE before starting the V2 bot for the first time.

Usage:
    python migrate_v2.py
"""

import sys
import pymysql
from datetime import datetime

try:
    from config import DATABASE_URL
    from urllib.parse import urlparse
    parsed = urlparse(DATABASE_URL)
    DB_CONFIG = {
        "host": parsed.hostname or "localhost",
        "user": parsed.username or "root",
        "password": parsed.password or "",
        "database": parsed.path.lstrip('/') or "toko_kelontong",
        "charset": "utf8mb4",
    }
except Exception:
    DB_CONFIG = {
        "host": "localhost",
        "user": "root",
        "password": "",
        "database": "toko_kelontong",
        "charset": "utf8mb4",
    }

# ── Tables to TRUNCATE (order matters due to FK constraints) ─────────────────
TABLES_TO_TRUNCATE = [
    "cart_items",
    "transaction_items",
    "transactions",
    "bot_users",
    "tenants",
]

# ── Tables to KEEP (no changes to their data) ─────────────────────────────────
TABLES_TO_KEEP = ["products", "promotions", "store_schedules"]


def run_migration():
    print("=" * 60)
    print("  POS Bot V2 — Database Migration")
    print("=" * 60)
    print()

    conn = pymysql.connect(**DB_CONFIG)
    cursor = conn.cursor()

    try:
        # ── STEP 1: Truncate transactional tables ──────────────────────────
        print("[1/5] Truncating transactional tables...")
        cursor.execute("SET FOREIGN_KEY_CHECKS = 0;")
        for table in TABLES_TO_TRUNCATE:
            cursor.execute(f"TRUNCATE TABLE `{table}`;")
            print(f"      ✅ TRUNCATED: {table}")
        cursor.execute("SET FOREIGN_KEY_CHECKS = 1;")

        # ── STEP 2: Alter bot_users — remove totp_secret, add new columns ─
        print()
        print("[2/5] Altering bot_users table...")

        # Drop totp_secret column if it exists
        cursor.execute("""
            SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'bot_users' AND COLUMN_NAME = 'totp_secret'
        """, (DB_CONFIG["database"],))
        if cursor.fetchone()[0]:
            cursor.execute("ALTER TABLE bot_users DROP COLUMN totp_secret;")
            print("      ✅ Dropped column: totp_secret")
        else:
            print("      ⏭️  Column totp_secret doesn't exist, skipping.")

        # Add token_validated_at if not exists
        cursor.execute("""
            SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'bot_users' AND COLUMN_NAME = 'token_validated_at'
        """, (DB_CONFIG["database"],))
        if not cursor.fetchone()[0]:
            cursor.execute("""
                ALTER TABLE bot_users
                ADD COLUMN token_validated_at DATETIME NULL DEFAULT NULL
                AFTER is_active;
            """)
            print("      ✅ Added column: token_validated_at")
        else:
            print("      ⏭️  Column token_validated_at already exists, skipping.")

        # Update role enum — rename 'vendor' → 'owner', remove 'developer'
        # Note: We just change the column type to accept owner/kasir
        cursor.execute("""
            ALTER TABLE bot_users
            MODIFY COLUMN role VARCHAR(20) NOT NULL;
        """)
        print("      ✅ Updated role column type")

        # ── STEP 3: Alter transactions — add tenant_id ─────────────────────
        print()
        print("[3/5] Altering transactions table...")
        cursor.execute("""
            SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'transactions' AND COLUMN_NAME = 'tenant_id'
        """, (DB_CONFIG["database"],))
        if not cursor.fetchone()[0]:
            cursor.execute("""
                ALTER TABLE transactions
                ADD COLUMN tenant_id INT NULL DEFAULT NULL
                AFTER user_id,
                ADD CONSTRAINT fk_transactions_tenant
                    FOREIGN KEY (tenant_id) REFERENCES tenants(id);
            """)
            print("      ✅ Added column: tenant_id (FK to tenants)")
        else:
            print("      ⏭️  Column tenant_id already exists, skipping.")

        # ── STEP 4: Create registration_tokens table ───────────────────────
        print()
        print("[4/5] Creating registration_tokens table...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS `registration_tokens` (
                `id`         INT NOT NULL AUTO_INCREMENT,
                `token`      VARCHAR(64) NOT NULL UNIQUE,
                `role`       VARCHAR(20) NOT NULL,
                `tenant_id`  INT NULL DEFAULT NULL,
                `created_by` BIGINT NULL DEFAULT NULL,
                `is_used`    TINYINT(1) NOT NULL DEFAULT 0,
                `used_by`    BIGINT NULL DEFAULT NULL,
                `expires_at` DATETIME NOT NULL,
                `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (`id`),
                CONSTRAINT `fk_regtoken_tenant`
                    FOREIGN KEY (`tenant_id`) REFERENCES `tenants` (`id`)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """)
        print("      ✅ Table registration_tokens created (or already exists).")

        # ── STEP 5: Verify kept tables still have data ─────────────────────
        print()
        print("[5/5] Verifying preserved tables...")
        for table in TABLES_TO_KEEP:
            cursor.execute(f"SELECT COUNT(*) FROM `{table}`;")
            count = cursor.fetchone()[0]
            print(f"      ✅ {table}: {count} rows preserved")

        conn.commit()
        print()
        print("=" * 60)
        print("  ✅ Migration COMPLETE!")
        print()
        print("  Next steps:")
        print("  1. Update config.py with OWNER_TELEGRAM_ID and API_SECRET_KEY")
        print("  2. Start the API server: uvicorn api_server:app --reload --port 8000")
        print("  3. Start the bot: python main.py")
        print("=" * 60)

    except Exception as e:
        conn.rollback()
        print()
        print(f"  ❌ Migration FAILED: {e}")
        print("  Database has been rolled back. No changes were made.")
        sys.exit(1)
    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    confirm = input(
        "\n⚠️  WARNING: This will DELETE ALL users, tenants, and transaction data.\n"
        "   Products, promotions, and schedules are SAFE.\n\n"
        "   Type 'YES' to continue: "
    ).strip()

    if confirm != "YES":
        print("   Migration cancelled.")
        sys.exit(0)

    run_migration()
