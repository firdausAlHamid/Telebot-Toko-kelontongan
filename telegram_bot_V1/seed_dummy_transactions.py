"""
seed_dummy_transactions.py
Generate realistic dummy transactions and varied stock for Tenant 2 (Toko Ciamis)
so that the product analytics dashboard has rich, realistic data across 6 months.
"""

import random
from datetime import datetime, timedelta
from database import SessionLocal, Tenant, Product, Transaction, TransactionItem, StockMovement

def seed_rich_analytics_data(tenant_id=2):
    db = SessionLocal()
    try:
        tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
        if not tenant:
            print(f"[ERROR] Tenant {tenant_id} not found!")
            return

        products = db.query(Product).filter(Product.tenant_id == tenant_id).all()
        if not products:
            print(f"[ERROR] No products found for tenant {tenant_id}!")
            return

        print(f"[*] Found {len(products)} products in '{tenant.store_name}'")

        # Let's categorize products into tiers:
        # Tier A: Top Sellers (15 products) -> frequent sales, high qty
        # Tier B: Moderate (35 products) -> regular sales
        # Tier C: Slow (40 products) -> few sales
        # Tier D: Inactive (rest) -> 0 sales in last 30d
        random.seed(42)
        shuffled = list(products)
        random.shuffle(shuffled)

        tier_a = shuffled[:15]
        tier_b = shuffled[15:50]
        tier_c = shuffled[50:90]
        tier_d = shuffled[90:]

        # Adjust stocks of some products to showcase different stock health statuses:
        # Some Habis (0)
        for p in tier_a[:2]:
            p.stock = 0
            p.min_stock = 10
        # Some Kritis (1-4)
        for p in tier_a[2:5]:
            p.stock = random.randint(1, 4)
            p.min_stock = 10
        # Some Menipis (5-12)
        for p in tier_b[:5]:
            p.stock = random.randint(5, 12)
            p.min_stock = 8
        # Some Aman (20-40)
        for p in tier_b[5:20]:
            p.stock = random.randint(25, 45)
            p.min_stock = 5
        # Some Berlebih (80-150)
        for p in tier_c[:15]:
            p.stock = random.randint(80, 150)
            p.min_stock = 5

        db.commit()
        print("[*] Varied product stock levels updated.")

        # Create transactions spanning the last 180 days (6 months)
        now = datetime.now()
        start_date = now - timedelta(days=180)

        # Generate ~220 transactions
        transactions_to_add = []
        payment_methods = ["cash", "cash", "cash", "qris", "qris"] # 60% cash, 40% qris
        
        trx_counter = 1000

        # Create realistic time slots (8:00 to 22:00)
        # Weekdays: higher probability in afternoon/evening
        days_total = 180
        total_transactions = 240

        for i in range(total_transactions):
            trx_counter += 1
            # Random day in past 180 days, with higher density in last 30 days
            if random.random() < 0.65:
                # last 30 days
                day_offset = random.randint(0, 30)
            else:
                # 31 to 180 days ago
                day_offset = random.randint(31, 180)

            trx_date = now - timedelta(
                days=day_offset,
                hours=random.randint(1, 23),
                minutes=random.randint(0, 59)
            )

            # Choose items for this transaction: 1 to 4 items
            num_items = random.choices([1, 2, 3, 4], weights=[40, 35, 15, 10])[0]
            items_pool = []
            
            # Select products based on tiers
            for _ in range(num_items):
                roll = random.random()
                if roll < 0.60:
                    chosen = random.choice(tier_a)
                elif roll < 0.88:
                    chosen = random.choice(tier_b)
                elif roll < 0.98:
                    chosen = random.choice(tier_c)
                else:
                    chosen = random.choice(tier_d[:10])
                
                # Qty: mostly 1-3
                qty = random.choices([1, 2, 3, 5], weights=[60, 25, 10, 5])[0]
                items_pool.append((chosen, qty))

            pm = random.choice(payment_methods)
            inv_no = f"INV-26{trx_date.strftime('%m%d')}-{trx_counter}"

            subtotal = sum(p.price * q for p, q in items_pool)
            discount = 0
            if subtotal >= 50000 and random.random() < 0.25:
                discount = random.choice([2000, 5000, 10000])
            grand_total = max(0, subtotal - discount)

            trx = Transaction(
                invoice_no=inv_no,
                user_id=6057914936,
                tenant_id=tenant_id,
                payment_method=pm,
                total_amount=grand_total,
                subtotal=subtotal,
                total_discount=discount,
                grand_total=grand_total,
                cash_received=grand_total if pm == "cash" else None,
                cash_change=0 if pm == "cash" else None,
                status="completed",
                created_at=trx_date
            )
            db.add(trx)
            db.flush()

            for prod, qty in items_pool:
                item_subtotal = prod.price * qty
                t_item = TransactionItem(
                    transaction_id=trx.id,
                    product_id=prod.id,
                    product_name=prod.item_name,
                    unit_price=prod.price,
                    quantity=qty,
                    discount_type=None,
                    discount_value=0,
                    discount_amount=0,
                    subtotal=item_subtotal
                )
                db.add(t_item)

        db.commit()
        print(f"[SUCCESS] Added {total_transactions} realistic dummy transactions across 6 months for Tenant {tenant_id}!")

    except Exception as e:
        db.rollback()
        print(f"[ERROR] Seeding failed: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    seed_rich_analytics_data(tenant_id=2)
