"""
seed_berkah.py -- Seed specific dummy products matching the user mockup
========================================================================
- Store: Toko Kelontong Berkah
- Categories: Sembako, Makanan, Minuman, Kebutuhan Rumah, Obat & Mandi
- Products: Beras Sentra Ramos 5kg, Minyak Goreng Filma 2L, Indomie Goreng (Pcs), Gula Pasir Gulaku 1kg, etc.
"""
from datetime import datetime, date
from database import SessionLocal, Tenant, BotUser, Product, StoreSchedule

SAMPLE_DATA = [
    # --- SEMBAKO ---
    {
        "category": "Sembako",
        "subcategory": "Beras",
        "item_name": "Beras Sentra Ramos 5kg",
        "price": 74500,
        "stock": 45,
        "image_url": "https://images.tokopedia.net/img/cache/700/VqbcmM/2021/7/8/e7f1bf56-82dc-46d5-aee0-1ea13e2f4f89.jpg"
    },
    {
        "category": "Sembako",
        "subcategory": "Minyak Goreng",
        "item_name": "Minyak Goreng Filma 2L",
        "price": 36800,
        "stock": 60,
        "image_url": "https://images.tokopedia.net/img/cache/700/VqbcmM/2022/10/11/4ffb9d62-ef50-4fc7-bcf9-c3d317fb6cf5.jpg"
    },
    {
        "category": "Sembako",
        "subcategory": "Gula Pasir",
        "item_name": "Gula Pasir Gulaku 1kg",
        "price": 17500,
        "stock": 50,
        "image_url": "https://images.tokopedia.net/img/cache/700/VqbcmM/2021/8/20/d244c05b-ec3b-4835-ab34-118ebfe28711.jpg"
    },
    {
        "category": "Sembako",
        "subcategory": "Tepung",
        "item_name": "Tepung Terigu Segitiga Biru 1kg",
        "price": 13500,
        "stock": 40,
        "image_url": ""
    },
    {
        "category": "Sembako",
        "subcategory": "Telur",
        "item_name": "Telur Ayam Negeri 1kg",
        "price": 28000,
        "stock": 35,
        "image_url": ""
    },

    # --- MAKANAN ---
    {
        "category": "Makanan",
        "subcategory": "Mie Instan",
        "item_name": "Indomie Goreng (Pcs)",
        "price": 3100,
        "stock": 120,
        "image_url": "https://images.tokopedia.net/img/cache/700/VqbcmM/2021/11/2/fa863925-5e60-449e-8ffc-157945d820c7.jpg"
    },
    {
        "category": "Makanan",
        "subcategory": "Mie Instan",
        "item_name": "Indomie Kuah Soto Mie 75g",
        "price": 3100,
        "stock": 90,
        "image_url": ""
    },
    {
        "category": "Makanan",
        "subcategory": "Mie Instan",
        "item_name": "Mie Sedaap Goreng 90g",
        "price": 3100,
        "stock": 85,
        "image_url": ""
    },
    {
        "category": "Makanan",
        "subcategory": "Camilan",
        "item_name": "Chitato Sapi Panggang 68g",
        "price": 11500,
        "stock": 30,
        "image_url": ""
    },
    {
        "category": "Makanan",
        "subcategory": "Biskuit",
        "item_name": "Roma Kelapa Biskuit 300g",
        "price": 10500,
        "stock": 25,
        "image_url": ""
    },

    # --- MINUMAN ---
    {
        "category": "Minuman",
        "subcategory": "Teh",
        "item_name": "Teh Pucuk Harum 350ml",
        "price": 3500,
        "stock": 100,
        "image_url": ""
    },
    {
        "category": "Minuman",
        "subcategory": "Air Mineral",
        "item_name": "Le Minerale Botol 600ml",
        "price": 3000,
        "stock": 150,
        "image_url": ""
    },
    {
        "category": "Minuman",
        "subcategory": "Air Mineral",
        "item_name": "Aqua Botol 600ml",
        "price": 3500,
        "stock": 120,
        "image_url": ""
    },
    {
        "category": "Minuman",
        "subcategory": "Kopi",
        "item_name": "Kopi Kapal Api Special Mix (Renceng)",
        "price": 14000,
        "stock": 40,
        "image_url": ""
    },
    {
        "category": "Minuman",
        "subcategory": "Susu",
        "item_name": "Ultra Milk Cokelat 250ml",
        "price": 6500,
        "stock": 60,
        "image_url": ""
    },

    # --- KEBUTUHAN RUMAH ---
    {
        "category": "Kebutuhan Rumah",
        "subcategory": "Deterjen",
        "item_name": "Rinso Molto Deterjen Bubuk 770g",
        "price": 22500,
        "stock": 30,
        "image_url": ""
    },
    {
        "category": "Kebutuhan Rumah",
        "subcategory": "Pencuci Piring",
        "item_name": "Sunlight Jeruk Nipis 750ml",
        "price": 14500,
        "stock": 50,
        "image_url": ""
    },
    {
        "category": "Kebutuhan Rumah",
        "subcategory": "Pewangi",
        "item_name": "Downy Floral Pink 650ml",
        "price": 24000,
        "stock": 25,
        "image_url": ""
    },
    {
        "category": "Kebutuhan Rumah",
        "subcategory": "Pembersih Lantai",
        "item_name": "Wipol Karbol Cemara 750ml",
        "price": 16000,
        "stock": 35,
        "image_url": ""
    },
    {
        "category": "Kebutuhan Rumah",
        "subcategory": "Anti Nyamuk",
        "item_name": "Baygon Aerosol Lavender 600ml",
        "price": 38500,
        "stock": 20,
        "image_url": ""
    },

    # --- OBAT & MANDI ---
    {
        "category": "Obat & Mandi",
        "subcategory": "Sabun Mandi",
        "item_name": "Lifebuoy Sabun Cair Total 10 450ml",
        "price": 21000,
        "stock": 40,
        "image_url": ""
    },
    {
        "category": "Obat & Mandi",
        "subcategory": "Shampoo",
        "item_name": "Clear Men Anti Dandruff 160ml",
        "price": 26500,
        "stock": 30,
        "image_url": ""
    },
    {
        "category": "Obat & Mandi",
        "subcategory": "Pasta Gigi",
        "item_name": "Pepsodent Pencegah Gigi Berlubang 190g",
        "price": 12500,
        "stock": 50,
        "image_url": ""
    },
    {
        "category": "Obat & Mandi",
        "subcategory": "Obat Bebas",
        "item_name": "Tolak Angin Cair Herbal (Box 5 sachet)",
        "price": 21500,
        "stock": 35,
        "image_url": ""
    },
    {
        "category": "Obat & Mandi",
        "subcategory": "Obat Sakit Kepala",
        "item_name": "Bodrex Strip (10 Tablet)",
        "price": 5500,
        "stock": 60,
        "image_url": ""
    },
    {
        "category": "Obat & Mandi",
        "subcategory": "Minyak Angin",
        "item_name": "Minyak Kayu Putih Cap Lang 60ml",
        "price": 24500,
        "stock": 45,
        "image_url": ""
    }
]

def run_seed():
    db = SessionLocal()
    
    # 1. Pastikan Tenant Toko Kelontong Berkah ada
    tenants = db.query(Tenant).all()
    for t in tenants:
        t.store_name = "Toko Kelontong Berkah"
    db.commit()

    target_tenant = db.query(Tenant).first()
    if not target_tenant:
        target_tenant = Tenant(store_name="Toko Kelontong Berkah", owner_id=0, is_active=True)
        db.add(target_tenant)
        db.commit()
        db.refresh(target_tenant)

    tid = target_tenant.id

    # 2. Update atau tambah StoreSchedule
    today = date.today()
    sched = db.query(StoreSchedule).filter(StoreSchedule.tenant_id == tid).first()
    if not sched:
        sched = StoreSchedule(
            tenant_id=tid,
            start_date=today,
            end_date=today.replace(year=today.year + 2),
            status="Buka",
            operating_hours="08:00 - 21:00",
            reason="Buka Setiap Hari",
            is_active=True
        )
        db.add(sched)
    else:
        sched.status = "Buka"
        sched.operating_hours = "08:00 - 21:00"
        sched.is_active = True
    db.commit()

    # 3. Masukkan / Sinkronkan produk dummy
    for item in SAMPLE_DATA:
        existing = db.query(Product).filter(
            Product.tenant_id == tid,
            Product.item_name == item["item_name"]
        ).first()

        if existing:
            existing.category = item["category"]
            existing.subcategory = item["subcategory"]
            existing.price = item["price"]
            existing.stock = item["stock"]
            existing.image_url = item["image_url"]
        else:
            max_id = db.query(Product.id).order_by(Product.id.desc()).first()
            new_id = (max_id[0] + 1) if max_id else 1
            prod = Product(
                id=new_id,
                category=item["category"],
                subcategory=item["subcategory"],
                item_name=item["item_name"],
                price=item["price"],
                stock=item["stock"],
                image_url=item["image_url"],
                tenant_id=tid
            )
            db.add(prod)
            db.commit()

    # Pastikan tenant 2 juga memiliki sinkronisasi yang sama jika ada
    t2 = db.query(Tenant).filter(Tenant.id == 2).first()
    if t2 and t2.id != tid:
        for item in SAMPLE_DATA:
            existing2 = db.query(Product).filter(
                Product.tenant_id == 2,
                Product.item_name == item["item_name"]
            ).first()
            if existing2:
                existing2.category = item["category"]
                existing2.subcategory = item["subcategory"]
                existing2.price = item["price"]
                existing2.stock = item["stock"]
                existing2.image_url = item["image_url"]
            else:
                max_id2 = db.query(Product.id).order_by(Product.id.desc()).first()
                new_id2 = (max_id2[0] + 1) if max_id2 else 1
                prod2 = Product(
                    id=new_id2,
                    category=item["category"],
                    subcategory=item["subcategory"],
                    item_name=item["item_name"],
                    price=item["price"],
                    stock=item["stock"],
                    image_url=item["image_url"],
                    tenant_id=2
                )
                db.add(prod2)
                db.commit()

    db.commit()
    db.close()
    print("[OK] Dummy data Toko Kelontong Berkah successfully seeded!")

if __name__ == "__main__":
    run_seed()
