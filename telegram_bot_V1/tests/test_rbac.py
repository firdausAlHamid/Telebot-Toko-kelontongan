import unittest
import sys
import os

# Add parent dir to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from auth import can, PERMISSIONS

class MockUser:
    def __init__(self, role):
        self.role = role

def get_role_mock(telegram_id):
    if telegram_id == 1:
        return "owner"
    elif telegram_id == 2:
        return "kasir"
    elif telegram_id == 3:
        return "customer"
    return "unknown"

class TestRBAC(unittest.TestCase):
    def setUp(self):
        # Patch the real get_role to use our mock
        import auth
        self.original_get_role = auth.get_role
        auth.get_role = get_role_mock

    def tearDown(self):
        import auth
        auth.get_role = self.original_get_role

    def test_owner_permissions(self):
        # Owner should have everything in PERMISSIONS that includes "owner"
        self.assertTrue(can(1, "trx:create"))
        self.assertTrue(can(1, "product:manage"))
        self.assertTrue(can(1, "promo:manage"))
        self.assertTrue(can(1, "report:view_tenant"))

    def test_kasir_permissions(self):
        self.assertTrue(can(2, "trx:create"))
        self.assertFalse(can(2, "product:manage"))
        self.assertFalse(can(2, "promo:manage"))
        self.assertTrue(can(2, "promo:view"))

    def test_customer_permissions(self):
        self.assertFalse(can(3, "trx:create"))
        self.assertFalse(can(3, "product:manage"))
        self.assertFalse(can(3, "promo:manage"))
        self.assertTrue(can(3, "promo:view"))
        self.assertTrue(can(3, "product:view"))

    def test_unknown_user(self):
        self.assertFalse(can(999, "trx:create"))
        self.assertFalse(can(999, "promo:view"))

if __name__ == '__main__':
    unittest.main()
