"""
SETUP.md — Setup Guide for Multi-Tenant Product System
======================================================

## Migration

Run the database migration to add tenant support to products:

```bash
python migrate_products.py
```

This will:
- Add tenant_id column to products table
- Create a demo tenant with id=1
- Assign all existing 220 products to the demo tenant

## Font Setup

Download fonts for receipt generation:

```bash
python download_fonts.py
```

Or manually place DejaVuSansMono.ttf and DejaVuSansMono-Bold.ttf in the fonts/ folder.

## Demo Account

Create a demo account for testing:

```bash
python seed_demo.py
```

Token for demo: POS-OWNER-DEMO0001

## Features Implemented

### Phase 1: Multi-Tenant Schema ✅
- Products now scoped to tenant_id
- Demo tenant created with sample products
- Migration script is idempotent

### Phase 2: Query Scoping ✅
- Cache updated to be per-tenant
- All product queries filter by tenant_id
- Voice AI prompt dynamically fetches tenant categories
- Stock management updated for tenant isolation

### Phase 3: Product Management UI ✅
- /produk command with inline buttons:
  - ➕ Tambah Produk - Add new product with category selection
  - ✏️ Edit Harga - Edit existing product prices
  - 🗑 Hapus Produk - Delete products
  - 📋 Lihat Produk - View products by category

### Phase 4: Receipt Improvements ✅
- Bundled DejaVu fonts for better rendering
- Store name from tenant shown on receipts
- Proper fallback chain if fonts unavailable

## Usage

1. Owner creates tenant and gets token via website
2. Owner activates token in bot
3. Owner uses /produk to manage products (instead of just voice)
4. Kasir can add/remove stock via /stock
5. Products and categories are isolated per tenant

## Notes

- demo tenant (id=1) gets all initial products
- New tenants start with empty catalog
- Voice AI only shows tenant's own products
- Inline buttons refresh instantly after product changes
