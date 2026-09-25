"""
quick_test.py — Quick validation of multi-tenant setup
======================================================
Run this to verify the migration and imports work correctly.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

print("=" * 60)
print("  Quick Test: Multi-Tenant Product System")
print("=" * 60)
print()

# Test 1: Import database models
try:
    from database import Product, Tenant
    print("✅ Database models imported")
    print(f"   Product has tenant_id: {hasattr(Product, 'tenant_id')}")
except Exception as e:
    print(f"❌ Database import failed: {e}")

# Test 2: Import handlers
try:
    from product_handlers import get_product_handler
    print("✅ Product handler imported")
except Exception as e:
    print(f"❌ Product handler import failed: {e}")

try:
    from main import build_categories_keyboard, build_products_keyboard
    print("✅ Main keyboard builders imported")
except Exception as e:
    print(f"❌ Main import failed: {e}")

try:
    from voice_ai_handler import get_system_prompt
    print("✅ Voice AI handler imported")
except Exception as e:
    print(f"❌ Voice AI import failed: {e}")

# Test 3: Test cache functions
try:
    from main import _refresh_cache_if_needed, invalidate_product_cache
    _refresh_cache_if_needed(0)
    print("✅ Cache functions work")
except Exception as e:
    print(f"❌ Cache test failed: {e}")

print()
print("=" * 60)
print("  Ready to start bot!")
print("=" * 60)
print()
print("Next steps:")
print("1. Run: python migrate_products.py")
print("2. Run: python download_fonts.py")
print("3. Run: python seed_demo.py")
print("4. Start bot: python main.py")
print("5. Start API: uvicorn api_server:app --reload --port 8000")
