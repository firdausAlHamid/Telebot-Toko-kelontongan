import csv
import io
import os
import sys
import unittest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import openpyxl
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api_server import AuthUser, app, get_current_user
from database import Product, SessionLocal, Tenant, Transaction, TransactionItem

client = TestClient(app)


class TestReportExport(unittest.TestCase):
    def setUp(self):
        self.db = SessionLocal()
        self.tenant = Tenant(
            store_name="Toko Laporan Test",
            owner_id=990011,
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

    def _seed_sample_data(self):
        now = datetime.now()
        prod = Product(
            tenant_id=self.tid,
            category="Sembako",
            item_name="Minyak Goreng 1L Test",
            price=18000,
            stock=25,
        )
        self.db.add(prod)
        self.db.commit()
        self.db.refresh(prod)

        trx_reg = Transaction(
            invoice_no=f"INV-REG-{self.tid}-1",
            user_id=1,
            tenant_id=self.tid,
            payment_method="TUNAI",
            is_itemized=True,
            subtotal=36000,
            total_discount=0,
            total_amount=36000,
            grand_total=36000,
            status="completed",
            created_at=now,
        )
        trx_quick = Transaction(
            invoice_no=f"INV-QCK-{self.tid}-2",
            user_id=1,
            tenant_id=self.tid,
            payment_method="QRIS",
            is_itemized=False,
            subtotal=25000,
            total_discount=0,
            total_amount=25000,
            grand_total=None,
            status="completed",
            created_at=now,
        )
        trx_old = Transaction(
            invoice_no=f"INV-OLD-{self.tid}-3",
            user_id=1,
            tenant_id=self.tid,
            payment_method="TUNAI",
            is_itemized=False,
            subtotal=50000,
            total_discount=0,
            total_amount=50000,
            grand_total=50000,
            status="completed",
            created_at=now - timedelta(days=45),
        )
        self.db.add_all([trx_reg, trx_quick, trx_old])
        self.db.commit()
        self.db.refresh(trx_reg)

        item = TransactionItem(
            transaction_id=trx_reg.id,
            product_id=prod.id,
            product_name=prod.item_name,
            unit_price=18000,
            quantity=2,
            subtotal=36000,
        )
        self.db.add(item)
        self.db.commit()
        return prod, trx_reg, trx_quick, trx_old

    def test_export_rbac_and_validation(self):
        unauth = client.get(f"/api/mini/report/export?tenant_id={self.tid}")
        self.assertEqual(unauth.status_code, 401)

        cust_dev = client.get(
            f"/api/mini/report/export?tenant_id={self.tid}",
            headers={"X-Dev-Role": "customer"},
        )
        self.assertEqual(cust_dev.status_code, 401)

        app.dependency_overrides[get_current_user] = lambda: AuthUser(
            telegram_id=1, role="customer", tenant_id=self.tid, full_name="Customer"
        )
        try:
            cust_auth = client.get(f"/api/mini/report/export?tenant_id={self.tid}")
            self.assertEqual(cust_auth.status_code, 403)
        finally:
            app.dependency_overrides.pop(get_current_user, None)

        bad_fmt = client.get(
            f"/api/mini/report/export?format=pdf&tenant_id={self.tid}",
            headers={"X-Dev-Role": "owner"},
        )
        self.assertEqual(bad_fmt.status_code, 400)

        bad_period = client.get(
            f"/api/mini/report/export?format=csv&period=decade&tenant_id={self.tid}",
            headers={"X-Dev-Role": "owner"},
        )
        self.assertEqual(bad_period.status_code, 400)

        for role in ("kasir", "owner"):
            ok = client.get(
                f"/api/mini/report/export?format=csv&period=today&tenant_id={self.tid}",
                headers={"X-Dev-Role": role},
            )
            self.assertEqual(ok.status_code, 200)

    def test_export_xlsx_multi_sheet_and_contents(self):
        prod, trx_reg, trx_quick, _ = self._seed_sample_data()

        res = client.get(
            f"/api/mini/report/export?format=xlsx&period=30d&tenant_id={self.tid}",
            headers={"X-Dev-Role": "owner", "Origin": "https://example.com"},
        )
        self.assertEqual(res.status_code, 200)
        self.assertIn(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            res.headers.get("content-type", ""),
        )
        self.assertIn(".xlsx", res.headers.get("content-disposition", ""))
        self.assertIn(
            "Content-Disposition",
            res.headers.get("access-control-expose-headers", ""),
        )

        wb = openpyxl.load_workbook(io.BytesIO(res.content))
        self.assertEqual(
            wb.sheetnames,
            [
                "Ringkasan Keuangan",
                "Matriks SKU & Stok",
                "Riwayat Transaksi",
                "Analisis Jam Sibuk",
            ],
        )

        ws_fin = wb["Ringkasan Keuangan"]
        self.assertIn("Toko Laporan Test", str(ws_fin["A1"].value))
        today_row = None
        for row in ws_fin.iter_rows(min_row=7, values_only=True):
            if row and row[0] == "Hari Ini":
                today_row = row
                break
        self.assertIsNotNone(today_row)
        self.assertEqual(today_row[1], 2)
        self.assertEqual(today_row[4], 61000)

        ws_sku = wb["Matriks SKU & Stok"]
        sku_rows = list(ws_sku.iter_rows(min_row=2, values_only=True))
        self.assertTrue(any(r[1] == prod.item_name and r[5] == 2 for r in sku_rows))

        ws_trx = wb["Riwayat Transaksi"]
        trx_map = {r[0]: r for r in ws_trx.iter_rows(min_row=2, values_only=True) if r and r[0]}
        self.assertIn(trx_reg.invoice_no, trx_map)
        self.assertIn(trx_quick.invoice_no, trx_map)
        self.assertEqual(trx_map[trx_reg.invoice_no][2], "Reguler")
        self.assertEqual(trx_map[trx_quick.invoice_no][2], "Penjualan Cepat")
        self.assertEqual(trx_map[trx_quick.invoice_no][5], "- (Penjualan Cepat)")
        self.assertEqual(trx_map[trx_quick.invoice_no][8], 25000)

        ws_peak = wb["Analisis Jam Sibuk"]
        peak_rows = [r for r in ws_peak.iter_rows(min_row=5, values_only=True) if r and r[0]]
        self.assertEqual(len(peak_rows), 24)

    def test_export_csv_utf8_bom_and_period_filter(self):
        _, trx_reg, trx_quick, trx_old = self._seed_sample_data()

        res_today = client.get(
            f"/api/mini/report/export?format=csv&period=today&tenant_id={self.tid}",
            headers={"X-Dev-Role": "kasir"},
        )
        self.assertEqual(res_today.status_code, 200)
        self.assertTrue(res_today.content.startswith(b"\xef\xbb\xbf"))
        self.assertIn("text/csv", res_today.headers.get("content-type", ""))
        self.assertIn(".csv", res_today.headers.get("content-disposition", ""))

        text_today = res_today.content.decode("utf-8-sig")
        rows_today = list(csv.reader(io.StringIO(text_today)))
        flat_today = "\n".join(",".join(r) for r in rows_today)
        self.assertIn(trx_reg.invoice_no, flat_today)
        self.assertIn(trx_quick.invoice_no, flat_today)
        self.assertNotIn(trx_old.invoice_no, flat_today)

        res_all = client.get(
            f"/api/mini/report/export?format=csv&period=all&tenant_id={self.tid}",
            headers={"X-Dev-Role": "owner"},
        )
        self.assertEqual(res_all.status_code, 200)
        text_all = res_all.content.decode("utf-8-sig")
        self.assertIn(trx_old.invoice_no, text_all)
        self.assertIn("Semua Periode", text_all)

    def test_send_report_to_telegram(self):
        self._seed_sample_data()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"ok": True}

        mock_http = AsyncMock()
        mock_http.post.return_value = mock_resp
        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value = mock_http
        mock_cm.__aexit__.return_value = False

        app.dependency_overrides[get_current_user] = lambda: AuthUser(
            telegram_id=555777, role="owner", tenant_id=self.tid, full_name="Owner Test"
        )
        try:
            with patch("api_server.BOT_TOKEN", "dummy-token"), patch(
                "api_server.httpx.AsyncClient", return_value=mock_cm
            ):
                res = client.post(f"/api/mini/report/send-telegram?period=30d&tenant_id={self.tid}")
        finally:
            app.dependency_overrides.pop(get_current_user, None)

        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertTrue(body["ok"])
        self.assertTrue(body["sent_to_telegram"])
        self.assertTrue(body["filename"].endswith(".xlsx"))
        mock_http.post.assert_awaited_once()
        call_kwargs = mock_http.post.call_args.kwargs
        self.assertEqual(call_kwargs["data"]["chat_id"], "555777")
        doc_tuple = call_kwargs["files"]["document"]
        self.assertTrue(doc_tuple[0].endswith(".xlsx"))
        wb = openpyxl.load_workbook(io.BytesIO(doc_tuple[1]))
        self.assertIn("Ringkasan Keuangan", wb.sheetnames)


if __name__ == "__main__":
    unittest.main()
