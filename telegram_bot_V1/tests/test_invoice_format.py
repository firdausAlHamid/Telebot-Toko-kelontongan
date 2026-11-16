import os
import re
import sys
import unittest
from datetime import datetime

from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api_server import app
from database import Product, SessionLocal, StockMovement, Tenant, Transaction, TransactionItem
from transaction_service import generate_invoice_no

client = TestClient(app)


class TestInvoiceFormat(unittest.TestCase):
    def setUp(self):
        self.db = SessionLocal()
        self.tenant = Tenant(
            store_name="Toko Invoice Test",
            owner_id=880011,
            is_active=True,
        )
        self.db.add(self.tenant)
        self.db.commit()
        self.db.refresh(self.tenant)
        self.tid = self.tenant.id
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        try:
            self.db.rollback()
            trx_ids = [
                r[0]
                for r in self.db.query(Transaction.id)
                .filter(Transaction.tenant_id == self.tid)
                .all()
            ]
            prod_ids = [
                r[0]
                for r in self.db.query(Product.id)
                .filter(Product.tenant_id == self.tid)
                .all()
            ]
            if prod_ids:
                self.db.query(StockMovement).filter(
                    StockMovement.product_id.in_(prod_ids)
                ).delete(synchronize_session=False)
            if trx_ids:
                self.db.query(TransactionItem).filter(
                    TransactionItem.transaction_id.in_(trx_ids)
                ).delete(synchronize_session=False)
            self.db.query(Transaction).filter(Transaction.tenant_id == self.tid).delete(
                synchronize_session=False
            )
            self.db.query(Product).filter(Product.tenant_id == self.tid).delete(
                synchronize_session=False
            )
            self.db.query(Tenant).filter(Tenant.id == self.tid).delete(
                synchronize_session=False
            )
            self.db.commit()
        finally:
            self.db.close()

    def test_generate_invoice_no_uses_trx_date_sequence(self):
        dt = datetime(2099, 1, 5, 10, 0, 0)
        first_no = generate_invoice_no(self.db, dt)
        self.assertEqual(first_no, "TRX-20990105-1001")

        self.db.add(
            Transaction(
                invoice_no=first_no,
                user_id=1,
                tenant_id=self.tid,
                payment_method="TUNAI",
                grand_total=10000,
                status="completed",
                created_at=dt,
            )
        )
        self.db.commit()

        second_no = generate_invoice_no(self.db, dt)
        self.assertEqual(second_no, "TRX-20990105-1002")

    def test_pos_regular_and_quick_sale_share_uniform_format(self):
        prod = Product(
            tenant_id=self.tid,
            category="Minuman",
            item_name="Air Mineral Invoice Test",
            price=4000,
            stock=10,
        )
        self.db.add(prod)
        self.db.commit()
        self.db.refresh(prod)

        today_tag = datetime.now().strftime("%Y%m%d")
        pattern = re.compile(rf"^TRX-{today_tag}-\d{{4,}}$")

        res_reg = client.post(
            "/api/pos/checkout",
            json={
                "tenant_id": self.tid,
                "items": [{"id": prod.id, "name": prod.item_name, "price": 4000, "quantity": 1}],
                "payment_method": "cash",
                "amount_paid": 4000,
                "is_itemized": True,
            },
            headers={"X-Dev-Role": "kasir"},
        )
        self.assertEqual(res_reg.status_code, 200)
        inv_reg = res_reg.json()["invoice_no"]
        self.assertRegex(inv_reg, pattern)

        res_quick = client.post(
            "/api/pos/checkout",
            json={
                "tenant_id": self.tid,
                "items": [],
                "payment_method": "cash",
                "quick_amount": 15000,
                "amount_paid": 15000,
                "is_itemized": False,
            },
            headers={"X-Dev-Role": "kasir"},
        )
        self.assertEqual(res_quick.status_code, 200)
        inv_quick = res_quick.json()["invoice_no"]
        self.assertRegex(inv_quick, pattern)
        self.assertNotEqual(inv_reg, inv_quick)


if __name__ == "__main__":
    unittest.main()

