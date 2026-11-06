import unittest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from api_server import app
from database import SessionLocal, Product, Transaction, TransactionItem, StockMovement, Category, Tenant
from transaction_service import apply_sale_stock, restore_sale_stock, InsufficientStockError

client = TestClient(app)

class TestStockAndCategoryIntegrity(unittest.TestCase):
    def setUp(self):
        self.db = SessionLocal()
        t = self.db.query(Tenant).filter(Tenant.id == 1).first()
        if not t:
            self.db.add(Tenant(id=1, store_name="Toko Test", owner_id=123, is_active=True))
            self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_out_of_stock_rejected_at_pos(self):
        """Produk dengan stok 0 tidak boleh bisa ditransaksikan di POS."""
        prod = Product(
            category="Sembako", item_name="Beras Habis Test",
            price=15000, stock=0, tenant_id=1
        )
        self.db.add(prod)
        self.db.commit()
        self.db.refresh(prod)

        payload = {
            "tenant_id": 1,
            "items": [{"id": prod.id, "name": prod.item_name, "price": 15000, "quantity": 1}],
            "payment_method": "cash"
        }
        res = client.post("/api/pos/checkout", json=payload, headers={"X-Dev-Role": "kasir"})
        self.assertEqual(res.status_code, 400)
        self.assertIn("HABIS", res.json()["detail"])

        # Clean up
        self.db.delete(prod)
        self.db.commit()

    def test_atomic_stock_deduction(self):
        """Memastikan apply_sale_stock melempar InsufficientStockError jika melebihi stok."""
        prod = Product(
            category="Minuman", item_name="Teh Botol Test",
            price=4000, stock=2, tenant_id=1
        )
        self.db.add(prod)
        self.db.commit()
        self.db.refresh(prod)

        trx = Transaction(user_id=1, tenant_id=1, payment_method="TUNAI", grand_total=12000, status="completed")
        self.db.add(trx)
        self.db.commit()
        self.db.refresh(trx)

        # Minta 3 padahal stok cuma 2
        trx_item = TransactionItem(
            transaction_id=trx.id, product_id=prod.id, product_name=prod.item_name,
            unit_price=4000, quantity=3, subtotal=12000
        )
        self.db.add(trx_item)
        self.db.commit()

        with self.assertRaises(InsufficientStockError):
            apply_sale_stock(self.db, trx, strict=True)

        # Stok tidak boleh berubah (tetap 2)
        self.db.refresh(prod)
        self.assertEqual(prod.stock, 2)

        # Clean up
        self.db.rollback()
        self.db.query(TransactionItem).filter(TransactionItem.transaction_id == trx.id).delete()
        self.db.query(Transaction).filter(Transaction.id == trx.id).delete()
        self.db.query(Product).filter(Product.id == prod.id).delete()
        self.db.commit()

    def test_empty_category_persists_in_db_and_catalog(self):
        """Kategori baru tanpa produk tetap ada di DB dan muncul di catalog API."""
        cat_name = "Kategori Kosong Unik Test"
        # Hapus dulu jika sisa run sebelumnya
        self.db.query(Category).filter(Category.tenant_id == 1, Category.name == cat_name).delete()
        self.db.commit()

        res_create = client.post(
            "/api/mini/categories",
            json={"tenant_id": 1, "name": cat_name, "icon": "🎁"},
            headers={"X-Dev-Role": "owner"}
        )
        self.assertEqual(res_create.status_code, 200)
        cat_id = res_create.json()["category"]["id"]

        # Cek di database
        cat_in_db = self.db.query(Category).filter(Category.id == cat_id).first()
        self.assertIsNotNone(cat_in_db)
        self.assertEqual(cat_in_db.name, cat_name)

        # Cek di endpoint /api/mini/catalog
        res_cat = client.get("/api/mini/catalog?tenant_id=1")
        self.assertEqual(res_cat.status_code, 200)
        cats_list = res_cat.json().get("categories", [])
        self.assertIn(cat_name, cats_list)

        # Clean up
        self.db.delete(cat_in_db)
        self.db.commit()

if __name__ == "__main__":
    unittest.main()
