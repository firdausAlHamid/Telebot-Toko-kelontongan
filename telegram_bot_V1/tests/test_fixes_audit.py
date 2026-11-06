import unittest
import sys
import os
from datetime import datetime

# Add parent dir to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from api_server import app
from database import SessionLocal, Product, Transaction, TransactionItem, StockMovement, CartItem, Tenant
from main import sync_memory_cart_to_db, load_db_cart_to_memory, get_cart_summary

client = TestClient(app)


class TestSecurityAndBugFixes(unittest.TestCase):
    """
    Test suite verifying the resolution of the 3 critical audit issues:
    1. API RBAC Security Flaws (FastAPI Depends() injection)
    2. Online Order Cancellation Stock Return (restore_sale_stock)
    3. Multi-Tenant Cart Isolation (CartItem tenant_id)
    """

    def setUp(self):
        self.db = SessionLocal()
        # Ensure test tenants exist
        t1 = self.db.query(Tenant).filter(Tenant.id == 1).first()
        if not t1:
            self.db.add(Tenant(id=1, store_name="Toko Test 1", owner_id=1001, is_active=True))
        t2 = self.db.query(Tenant).filter(Tenant.id == 2).first()
        if not t2:
            self.db.add(Tenant(id=2, store_name="Toko Test 2", owner_id=1002, is_active=True))
        self.db.commit()

    def tearDown(self):
        self.db.close()

    # =========================================================================
    # ISSUE 1: API RBAC SECURITY FLAW VERIFICATION
    # =========================================================================

    def test_void_endpoint_requires_auth(self):
        """Unauthenticated requests to void endpoint must return 401 Unauthorized."""
        res = client.post("/api/pos/transactions/INV-NONEXISTENT/void")
        self.assertEqual(res.status_code, 401)
        self.assertIn("Autentikasi gagal", res.json()["detail"])

    def test_void_endpoint_rejects_kasir(self):
        """Kasir role must be rejected from void endpoint with 403 Forbidden."""
        headers = {"X-Dev-Role": "kasir"}
        res = client.post("/api/pos/transactions/INV-NONEXISTENT/void", headers=headers)
        self.assertEqual(res.status_code, 403)
        self.assertIn("Akses ditolak", res.json()["detail"])

    def test_void_endpoint_allows_owner(self):
        """Owner role must pass RBAC check on void endpoint."""
        headers = {"X-Dev-Role": "owner"}
        res = client.post("/api/pos/transactions/INV-NONEXISTENT/void", headers=headers)
        # Should NOT be 401 or 403 (returns 404 because invoice doesn't exist)
        self.assertEqual(res.status_code, 404)

    def test_delete_product_requires_owner(self):
        """Product deletion must strictly require owner role."""
        # 1. Unauthenticated -> 401
        res1 = client.delete("/api/mini/product/999999")
        self.assertEqual(res1.status_code, 401)

        # 2. Kasir -> 403
        res2 = client.delete("/api/mini/product/999999", headers={"X-Dev-Role": "kasir"})
        self.assertEqual(res2.status_code, 403)

        # 3. Owner -> passes RBAC (returns 404 because product doesn't exist)
        res3 = client.delete("/api/mini/product/999999", headers={"X-Dev-Role": "owner"})
        self.assertEqual(res3.status_code, 404)

    def test_add_product_requires_staff(self):
        """Adding product must require staff (owner or kasir), rejecting unauthenticated."""
        # Unauthenticated -> 401
        res1 = client.post("/api/mini/product", json={"item_name": "Test Prod", "price": 1000, "stock": 5})
        self.assertEqual(res1.status_code, 401)

        # Kasir -> 200 (allowed)
        res2 = client.post(
            "/api/mini/product",
            json={"item_name": "Test Prod Kasir", "category": "Makanan", "price": 5000, "stock": 10, "tenant_id": 1},
            headers={"X-Dev-Role": "kasir"}
        )
        self.assertEqual(res2.status_code, 200)
        prod_id = res2.json()["product"]["id"]

        # Clean up
        self.db.query(Product).filter(Product.id == prod_id).delete()
        self.db.commit()

    # =========================================================================
    # ISSUE 2: ONLINE ORDER CANCELLATION STOCK RETURN VERIFICATION
    # =========================================================================

    def test_online_order_cancellation_restores_stock(self):
        """When staff cancels an online order, stock must be restored to products."""
        # 1. Create a test product with initial stock = 25
        prod = Product(
            category="Sembako",
            subcategory="Sembako",
            item_name="Beras Test Restorasi 5kg",
            price=60000,
            stock=25,
            tenant_id=1
        )
        self.db.add(prod)
        self.db.commit()
        self.db.refresh(prod)
        prod_id = prod.id

        # 2. Place an order for 5 pcs (Cash / Pick-up at store)
        order_payload = {
            "tenant_id": 1,
            "delivery_type": "pickup",
            "payment_method": "cash",
            "customer_name": "Budi Test",
            "customer_phone": "08123456789",
            "items": [{"id": prod_id, "name": prod.item_name, "price": 60000, "quantity": 5}],
            "telegram_user": {"id": 112233, "first_name": "Budi"}
        }
        res_order = client.post("/api/mini/order", json=order_payload)
        self.assertEqual(res_order.status_code, 200)
        invoice_no = res_order.json()["invoice_no"]
        self.db.commit()
        trx = self.db.query(Transaction).filter(Transaction.invoice_no == invoice_no).first()
        self.assertIsNotNone(trx)
        trx_id = trx.id

        # Refresh product stock -> should be 25 - 5 = 20
        self.db.refresh(prod)
        self.assertEqual(prod.stock, 20)

        # 3. Staff cancels the order via PUT /api/pos/orders/{trx_id}/status
        cancel_res = client.put(
            f"/api/pos/orders/{trx_id}/status",
            json={"status": "cancelled"},
            headers={"X-Dev-Role": "kasir"}
        )
        self.assertEqual(cancel_res.status_code, 200)

        # Refresh product stock -> MUST BE RESTORED TO 25!
        self.db.commit()
        self.db.refresh(prod)
        self.assertEqual(prod.stock, 25, "Product stock should be restored to 25 after cancellation!")

        # Verify StockMovement records
        movements = self.db.query(StockMovement).filter(
            StockMovement.product_id == prod_id,
            StockMovement.movement_type == "in"
        ).all()
        self.assertTrue(len(movements) >= 1)
        self.assertTrue(any("Pembatalan Pesanan Online" in (m.notes or "") for m in movements))

        # 4. If order is reactivated (e.g. customer actually arrived) -> stock re-deducted to 20
        reactivate_res = client.put(
            f"/api/pos/orders/{trx_id}/status",
            json={"status": "diproses"},
            headers={"X-Dev-Role": "kasir"}
        )
        self.assertEqual(reactivate_res.status_code, 200)
        self.db.commit()
        self.db.refresh(prod)
        self.assertEqual(prod.stock, 20, "Product stock should be re-deducted to 20 on reactivation!")

        # Clean up
        self.db.query(StockMovement).filter(StockMovement.product_id == prod_id).delete()
        self.db.query(TransactionItem).filter(TransactionItem.transaction_id == trx_id).delete()
        self.db.query(Transaction).filter(Transaction.id == trx_id).delete()
        self.db.query(Product).filter(Product.id == prod_id).delete()
        self.db.commit()

    # =========================================================================
    # ISSUE 3: MULTI-TENANT CART ISOLATION VERIFICATION
    # =========================================================================

    def test_cart_multi_tenant_isolation(self):
        """Cart items for a user must be isolated per tenant_id and not overwrite other stores."""
        user_id = 998877

        # Clean previous test artifacts
        self.db.query(CartItem).filter(CartItem.user_id == user_id).delete()
        self.db.commit()

        # Create 2 distinct products across 2 tenants
        p1 = Product(category="Makanan", item_name="Toko 1 Snack", price=5000, stock=50, tenant_id=1)
        p2 = Product(category="Makanan", item_name="Toko 2 Drink", price=8000, stock=50, tenant_id=2)
        self.db.add_all([p1, p2])
        self.db.commit()
        self.db.refresh(p1)
        self.db.refresh(p2)

        class DummyContext:
            def __init__(self):
                self.user_data = {}

        # 1. User shops at Tenant 1: adds 3x p1
        ctx1 = DummyContext()
        ctx1.user_data["mem_cart"] = {p1.id: 3}
        sync_memory_cart_to_db(user_id, ctx1, tenant_id=1)

        # 2. User shops at Tenant 2: adds 2x p2
        ctx2 = DummyContext()
        ctx2.user_data["mem_cart"] = {p2.id: 2}
        sync_memory_cart_to_db(user_id, ctx2, tenant_id=2)

        # Refresh session to see commits from helper functions
        self.db.commit()

        # 3. Verify database holds separate records with distinct tenant_ids
        t1_items = self.db.query(CartItem).filter(CartItem.user_id == user_id, CartItem.tenant_id == 1).all()
        t2_items = self.db.query(CartItem).filter(CartItem.user_id == user_id, CartItem.tenant_id == 2).all()
        self.assertEqual(len(t1_items), 3)
        self.assertEqual(len(t2_items), 2)

        # 4. Verify get_cart_summary correctly filters by tenant_id
        sum1 = get_cart_summary(user_id, tenant_id=1)
        self.assertEqual(len(sum1), 1)
        self.assertEqual(sum1[0].item_name, "Toko 1 Snack")
        self.assertEqual(sum1[0].qty, 3)

        sum2 = get_cart_summary(user_id, tenant_id=2)
        self.assertEqual(len(sum2), 1)
        self.assertEqual(sum2[0].item_name, "Toko 2 Drink")
        self.assertEqual(sum2[0].qty, 2)

        # 5. User checks out / clears cart at Tenant 1
        # Tenant 2 items must NOT be affected!
        q_del = self.db.query(CartItem).filter(CartItem.user_id == user_id, CartItem.tenant_id == 1)
        q_del.delete(synchronize_session=False)
        self.db.commit()

        # Tenant 1 cart is now empty
        t1_rem = self.db.query(CartItem).filter(CartItem.user_id == user_id, CartItem.tenant_id == 1).all()
        self.assertEqual(len(t1_rem), 0)

        # Tenant 2 cart items are completely preserved!
        t2_rem = self.db.query(CartItem).filter(CartItem.user_id == user_id, CartItem.tenant_id == 2).all()
        self.assertEqual(len(t2_rem), 2)

        # Clean up
        self.db.query(CartItem).filter(CartItem.user_id == user_id).delete()
        self.db.query(Product).filter(Product.id.in_([p1.id, p2.id])).delete()
        self.db.commit()


if __name__ == '__main__':
    unittest.main()
