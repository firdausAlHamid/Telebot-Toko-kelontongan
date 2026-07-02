"""
Master Data Produk Toko Kelontong — 210 Produk
================================================
Struktur: List of Dictionaries, siap di-insert ke SQLAlchemy.
"""

master_products = [
    # =========================================================================
    # KATEGORI 1: SEMBAKO & BAHAN POKOK (30 produk)
    # =========================================================================
    # --- Beras ---
    {"id": 1, "category": "Sembako & Bahan Pokok", "subcategory": "Beras", "item_name": "Beras Rojolele Premium 5kg", "price": 72000},
    {"id": 2, "category": "Sembako & Bahan Pokok", "subcategory": "Beras", "item_name": "Beras Pandan Wangi Cap Topi Koki 5kg", "price": 68000},
    {"id": 3, "category": "Sembako & Bahan Pokok", "subcategory": "Beras", "item_name": "Beras Setra Ramos Bulog 5kg", "price": 62000},
    {"id": 4, "category": "Sembako & Bahan Pokok", "subcategory": "Beras", "item_name": "Beras IR 64 Medium 5kg", "price": 58000},
    {"id": 5, "category": "Sembako & Bahan Pokok", "subcategory": "Beras", "item_name": "Beras Pulen Anak Raja 2kg", "price": 28000},
    {"id": 6, "category": "Sembako & Bahan Pokok", "subcategory": "Beras", "item_name": "Beras Merah Organik 1kg", "price": 25000},
    {"id": 7, "category": "Sembako & Bahan Pokok", "subcategory": "Beras", "item_name": "Beras Slyp Super Cap Jago 10kg", "price": 85000},
    # --- Minyak Goreng ---
    {"id": 8, "category": "Sembako & Bahan Pokok", "subcategory": "Minyak Goreng", "item_name": "Minyak Goreng Bimoli Pouch 1L", "price": 19500},
    {"id": 9, "category": "Sembako & Bahan Pokok", "subcategory": "Minyak Goreng", "item_name": "Minyak Goreng Bimoli Pouch 2L", "price": 36000},
    {"id": 10, "category": "Sembako & Bahan Pokok", "subcategory": "Minyak Goreng", "item_name": "Minyak Goreng Tropical Pouch 1L", "price": 18500},
    {"id": 11, "category": "Sembako & Bahan Pokok", "subcategory": "Minyak Goreng", "item_name": "Minyak Goreng Tropical Pouch 2L", "price": 34000},
    {"id": 12, "category": "Sembako & Bahan Pokok", "subcategory": "Minyak Goreng", "item_name": "Minyak Goreng Sunco Pouch 1L", "price": 18000},
    {"id": 13, "category": "Sembako & Bahan Pokok", "subcategory": "Minyak Goreng", "item_name": "Minyak Goreng Sunco Pouch 2L", "price": 33000},
    {"id": 14, "category": "Sembako & Bahan Pokok", "subcategory": "Minyak Goreng", "item_name": "Minyak Goreng Filma Pouch 1L", "price": 19000},
    {"id": 15, "category": "Sembako & Bahan Pokok", "subcategory": "Minyak Goreng", "item_name": "Minyak Goreng Fortune Pouch 1L", "price": 17500},
    # --- Gula & Garam ---
    {"id": 16, "category": "Sembako & Bahan Pokok", "subcategory": "Gula & Garam", "item_name": "Gula Pasir Gulaku Premium 1kg", "price": 16500},
    {"id": 17, "category": "Sembako & Bahan Pokok", "subcategory": "Gula & Garam", "item_name": "Gula Pasir Rose Brand 1kg", "price": 15500},
    {"id": 18, "category": "Sembako & Bahan Pokok", "subcategory": "Gula & Garam", "item_name": "Gula Merah Jawa 250g", "price": 7500},
    {"id": 19, "category": "Sembako & Bahan Pokok", "subcategory": "Gula & Garam", "item_name": "Garam Refina Beryodium 500g", "price": 5500},
    {"id": 20, "category": "Sembako & Bahan Pokok", "subcategory": "Gula & Garam", "item_name": "Garam Cap Kapal 250g", "price": 3500},
    {"id": 21, "category": "Sembako & Bahan Pokok", "subcategory": "Gula & Garam", "item_name": "Gula Aren Bubuk Haan 100g", "price": 9000},
    # --- Tepung & Terigu ---
    {"id": 22, "category": "Sembako & Bahan Pokok", "subcategory": "Tepung & Terigu", "item_name": "Tepung Terigu Segitiga Biru 1kg", "price": 12500},
    {"id": 23, "category": "Sembako & Bahan Pokok", "subcategory": "Tepung & Terigu", "item_name": "Tepung Terigu Cakra Kembar 1kg", "price": 13500},
    {"id": 24, "category": "Sembako & Bahan Pokok", "subcategory": "Tepung & Terigu", "item_name": "Tepung Terigu Kunci Biru 1kg", "price": 11000},
    {"id": 25, "category": "Sembako & Bahan Pokok", "subcategory": "Tepung & Terigu", "item_name": "Tepung Beras Rose Brand 500g", "price": 8500},
    {"id": 26, "category": "Sembako & Bahan Pokok", "subcategory": "Tepung & Terigu", "item_name": "Tepung Tapioka Rose Brand 500g", "price": 7500},
    {"id": 27, "category": "Sembako & Bahan Pokok", "subcategory": "Tepung & Terigu", "item_name": "Tepung Maizena Maizenaku 150g", "price": 6500},
    {"id": 28, "category": "Sembako & Bahan Pokok", "subcategory": "Tepung & Terigu", "item_name": "Tepung Bumbu Sajiku Serbaguna 80g", "price": 4500},
    {"id": 29, "category": "Sembako & Bahan Pokok", "subcategory": "Tepung & Terigu", "item_name": "Tepung Panir Mama Suka 250g", "price": 9500},
    {"id": 30, "category": "Sembako & Bahan Pokok", "subcategory": "Tepung & Terigu", "item_name": "Tepung Hunkwe Cap Gunung 120g", "price": 4000},

    # =========================================================================
    # KATEGORI 2: MIE & MAKANAN INSTAN (28 produk)
    # =========================================================================
    # --- Mie Instan Kuah/Goreng ---
    {"id": 31, "category": "Mie & Makanan Instan", "subcategory": "Mie Instan", "item_name": "Indomie Goreng Spesial 85g", "price": 3500},
    {"id": 32, "category": "Mie & Makanan Instan", "subcategory": "Mie Instan", "item_name": "Indomie Kuah Soto Mie 75g", "price": 3500},
    {"id": 33, "category": "Mie & Makanan Instan", "subcategory": "Mie Instan", "item_name": "Indomie Kuah Ayam Bawang 75g", "price": 3500},
    {"id": 34, "category": "Mie & Makanan Instan", "subcategory": "Mie Instan", "item_name": "Indomie Kuah Kari Ayam 75g", "price": 3500},
    {"id": 35, "category": "Mie & Makanan Instan", "subcategory": "Mie Instan", "item_name": "Indomie Goreng Rendang 91g", "price": 3500},
    {"id": 36, "category": "Mie & Makanan Instan", "subcategory": "Mie Instan", "item_name": "Indomie Goreng Pedas 85g", "price": 3500},
    {"id": 37, "category": "Mie & Makanan Instan", "subcategory": "Mie Instan", "item_name": "Indomie Hype Abis Ayam Geprek 85g", "price": 4000},
    {"id": 38, "category": "Mie & Makanan Instan", "subcategory": "Mie Instan", "item_name": "Mie Sedaap Goreng 90g", "price": 3500},
    {"id": 39, "category": "Mie & Makanan Instan", "subcategory": "Mie Instan", "item_name": "Mie Sedaap Kuah Soto 77g", "price": 3500},
    {"id": 40, "category": "Mie & Makanan Instan", "subcategory": "Mie Instan", "item_name": "Mie Sedaap Korean Spicy Chicken 87g", "price": 4000},
    {"id": 41, "category": "Mie & Makanan Instan", "subcategory": "Mie Instan", "item_name": "Sarimi Goreng Rasa Ayam Kecap 80g", "price": 3000},
    {"id": 42, "category": "Mie & Makanan Instan", "subcategory": "Mie Instan", "item_name": "Supermi Goreng 85g", "price": 3000},
    {"id": 43, "category": "Mie & Makanan Instan", "subcategory": "Mie Instan", "item_name": "Pop Mie Kuah Ayam 75g", "price": 5500},
    {"id": 44, "category": "Mie & Makanan Instan", "subcategory": "Mie Instan", "item_name": "Pop Mie Kuah Baso 75g", "price": 5500},
    {"id": 45, "category": "Mie & Makanan Instan", "subcategory": "Mie Instan", "item_name": "Mie Gelas Rasa Soto 75g", "price": 3000},
    {"id": 46, "category": "Mie & Makanan Instan", "subcategory": "Mie Instan", "item_name": "Indomie Goreng Jumbo 129g", "price": 5500},
    # --- Bubur Instan ---
    {"id": 47, "category": "Mie & Makanan Instan", "subcategory": "Bubur Instan", "item_name": "Super Bubur Rasa Ayam 49g", "price": 4500},
    {"id": 48, "category": "Mie & Makanan Instan", "subcategory": "Bubur Instan", "item_name": "Super Bubur Abon Sapi 49g", "price": 4500},
    {"id": 49, "category": "Mie & Makanan Instan", "subcategory": "Bubur Instan", "item_name": "Energen Sereal Cokelat 30g", "price": 2500},
    {"id": 50, "category": "Mie & Makanan Instan", "subcategory": "Bubur Instan", "item_name": "Energen Sereal Kacang Hijau 30g", "price": 2500},
    # --- Sarden / Makanan Kaleng ---
    {"id": 51, "category": "Mie & Makanan Instan", "subcategory": "Sarden & Makanan Kaleng", "item_name": "Sarden ABC Saus Tomat 155g", "price": 11500},
    {"id": 52, "category": "Mie & Makanan Instan", "subcategory": "Sarden & Makanan Kaleng", "item_name": "Sarden ABC Saus Cabai 155g", "price": 11500},
    {"id": 53, "category": "Mie & Makanan Instan", "subcategory": "Sarden & Makanan Kaleng", "item_name": "Sarden Botan Makarel Tomat 155g", "price": 10500},
    {"id": 54, "category": "Mie & Makanan Instan", "subcategory": "Sarden & Makanan Kaleng", "item_name": "Kornet Pronas 198g", "price": 18000},
    {"id": 55, "category": "Mie & Makanan Instan", "subcategory": "Sarden & Makanan Kaleng", "item_name": "Kornet Pronas 50g", "price": 7500},
    {"id": 56, "category": "Mie & Makanan Instan", "subcategory": "Sarden & Makanan Kaleng", "item_name": "Sosis So Nice Ayam 60g (3pcs)", "price": 5000},
    {"id": 57, "category": "Mie & Makanan Instan", "subcategory": "Sarden & Makanan Kaleng", "item_name": "Fiesta Chicken Nugget 250g", "price": 17500},
    {"id": 58, "category": "Mie & Makanan Instan", "subcategory": "Sarden & Makanan Kaleng", "item_name": "Bernardi Sosis Sapi 250g", "price": 16000},

    # =========================================================================
    # KATEGORI 3: BUMBU & BAHAN DAPUR (28 produk)
    # =========================================================================
    # --- Penyedap Rasa ---
    {"id": 59, "category": "Bumbu & Bahan Dapur", "subcategory": "Penyedap Rasa", "item_name": "Royco Penyedap Rasa Ayam 100g", "price": 5500},
    {"id": 60, "category": "Bumbu & Bahan Dapur", "subcategory": "Penyedap Rasa", "item_name": "Royco Penyedap Rasa Sapi 100g", "price": 5500},
    {"id": 61, "category": "Bumbu & Bahan Dapur", "subcategory": "Penyedap Rasa", "item_name": "Masako Rasa Ayam 100g", "price": 5000},
    {"id": 62, "category": "Bumbu & Bahan Dapur", "subcategory": "Penyedap Rasa", "item_name": "Masako Rasa Sapi 100g", "price": 5000},
    {"id": 63, "category": "Bumbu & Bahan Dapur", "subcategory": "Penyedap Rasa", "item_name": "Ajinomoto MSG 100g", "price": 4500},
    {"id": 64, "category": "Bumbu & Bahan Dapur", "subcategory": "Penyedap Rasa", "item_name": "Sajiku Bumbu Nasi Goreng 20g", "price": 2000},
    {"id": 65, "category": "Bumbu & Bahan Dapur", "subcategory": "Penyedap Rasa", "item_name": "Indofood Bumbu Racik Sayur Asem 20g", "price": 2500},
    {"id": 66, "category": "Bumbu & Bahan Dapur", "subcategory": "Penyedap Rasa", "item_name": "Indofood Bumbu Racik Opor Ayam 45g", "price": 3500},
    {"id": 67, "category": "Bumbu & Bahan Dapur", "subcategory": "Penyedap Rasa", "item_name": "Sajiku Tepung Bumbu Golden Crispy 200g", "price": 8500},
    # --- Kecap & Saus ---
    {"id": 68, "category": "Bumbu & Bahan Dapur", "subcategory": "Kecap & Saus", "item_name": "Kecap Manis ABC 135ml", "price": 6500},
    {"id": 69, "category": "Bumbu & Bahan Dapur", "subcategory": "Kecap & Saus", "item_name": "Kecap Manis ABC 275ml", "price": 12000},
    {"id": 70, "category": "Bumbu & Bahan Dapur", "subcategory": "Kecap & Saus", "item_name": "Kecap Manis Bango 135ml", "price": 7500},
    {"id": 71, "category": "Bumbu & Bahan Dapur", "subcategory": "Kecap & Saus", "item_name": "Kecap Manis Bango 275ml", "price": 14000},
    {"id": 72, "category": "Bumbu & Bahan Dapur", "subcategory": "Kecap & Saus", "item_name": "Kecap Asin ABC 135ml", "price": 6000},
    {"id": 73, "category": "Bumbu & Bahan Dapur", "subcategory": "Kecap & Saus", "item_name": "Saos Sambal ABC 135ml", "price": 6500},
    {"id": 74, "category": "Bumbu & Bahan Dapur", "subcategory": "Kecap & Saus", "item_name": "Saos Sambal Indofood 135ml", "price": 5500},
    {"id": 75, "category": "Bumbu & Bahan Dapur", "subcategory": "Kecap & Saus", "item_name": "Saos Tomat ABC 135ml", "price": 6000},
    {"id": 76, "category": "Bumbu & Bahan Dapur", "subcategory": "Kecap & Saus", "item_name": "Saos Tiram Saori 135ml", "price": 7500},
    # --- Margarin & Mentega ---
    {"id": 77, "category": "Bumbu & Bahan Dapur", "subcategory": "Margarin & Mentega", "item_name": "Margarin Blue Band Serbaguna 200g", "price": 11000},
    {"id": 78, "category": "Bumbu & Bahan Dapur", "subcategory": "Margarin & Mentega", "item_name": "Margarin Filma 200g", "price": 8500},
    {"id": 79, "category": "Bumbu & Bahan Dapur", "subcategory": "Margarin & Mentega", "item_name": "Margarin Palmia 200g", "price": 7500},
    {"id": 80, "category": "Bumbu & Bahan Dapur", "subcategory": "Margarin & Mentega", "item_name": "Mentega Orchid 200g", "price": 10500},
    # --- Santan Instan ---
    {"id": 81, "category": "Bumbu & Bahan Dapur", "subcategory": "Santan Instan", "item_name": "Santan Kara 65ml", "price": 4500},
    {"id": 82, "category": "Bumbu & Bahan Dapur", "subcategory": "Santan Instan", "item_name": "Santan Kara 200ml", "price": 9500},
    {"id": 83, "category": "Bumbu & Bahan Dapur", "subcategory": "Santan Instan", "item_name": "Santan Sun Kara Bubuk 25g", "price": 3000},
    {"id": 84, "category": "Bumbu & Bahan Dapur", "subcategory": "Santan Instan", "item_name": "Cuka Makan Dixi 150ml", "price": 4000},
    {"id": 85, "category": "Bumbu & Bahan Dapur", "subcategory": "Santan Instan", "item_name": "Merica Bubuk Ladaku 25g", "price": 5500},
    {"id": 86, "category": "Bumbu & Bahan Dapur", "subcategory": "Santan Instan", "item_name": "Bawang Goreng Kupu-Kupu 100g", "price": 15000},

    # =========================================================================
    # KATEGORI 4: MINUMAN & SUSU (30 produk)
    # =========================================================================
    # --- Air Mineral ---
    {"id": 87, "category": "Minuman & Susu", "subcategory": "Air Mineral", "item_name": "Aqua Botol 600ml", "price": 3500},
    {"id": 88, "category": "Minuman & Susu", "subcategory": "Air Mineral", "item_name": "Aqua Botol 1500ml", "price": 6500},
    {"id": 89, "category": "Minuman & Susu", "subcategory": "Air Mineral", "item_name": "Aqua Galon 19L", "price": 22000},
    {"id": 90, "category": "Minuman & Susu", "subcategory": "Air Mineral", "item_name": "Le Minerale Botol 600ml", "price": 3500},
    {"id": 91, "category": "Minuman & Susu", "subcategory": "Air Mineral", "item_name": "Club Botol 600ml", "price": 3000},
    # --- Kopi & Teh Sachet ---
    {"id": 92, "category": "Minuman & Susu", "subcategory": "Kopi & Teh Sachet", "item_name": "Kopi Kapal Api Mix 25g", "price": 2500},
    {"id": 93, "category": "Minuman & Susu", "subcategory": "Kopi & Teh Sachet", "item_name": "Kopi Kapal Api Special 6.5g", "price": 1500},
    {"id": 94, "category": "Minuman & Susu", "subcategory": "Kopi & Teh Sachet", "item_name": "Good Day Cappuccino 25g", "price": 2500},
    {"id": 95, "category": "Minuman & Susu", "subcategory": "Kopi & Teh Sachet", "item_name": "Good Day Mocacinno 20g", "price": 2500},
    {"id": 96, "category": "Minuman & Susu", "subcategory": "Kopi & Teh Sachet", "item_name": "Torabika Creamy Latte 25g", "price": 2500},
    {"id": 97, "category": "Minuman & Susu", "subcategory": "Kopi & Teh Sachet", "item_name": "Nescafe Original 3in1 18g", "price": 2000},
    {"id": 98, "category": "Minuman & Susu", "subcategory": "Kopi & Teh Sachet", "item_name": "Kopi ABC Susu 31g", "price": 2500},
    {"id": 99, "category": "Minuman & Susu", "subcategory": "Kopi & Teh Sachet", "item_name": "Teh Sariwangi Celup 25 Bags", "price": 7500},
    {"id": 100, "category": "Minuman & Susu", "subcategory": "Kopi & Teh Sachet", "item_name": "Teh Pucuk Harum 350ml", "price": 4000},
    {"id": 101, "category": "Minuman & Susu", "subcategory": "Kopi & Teh Sachet", "item_name": "Tong Tji Teh Celup 25 Bags", "price": 6000},
    {"id": 102, "category": "Minuman & Susu", "subcategory": "Kopi & Teh Sachet", "item_name": "Teh Sosro Kotak 250ml", "price": 4000},
    # --- Susu UHT / Bubuk ---
    {"id": 103, "category": "Minuman & Susu", "subcategory": "Susu", "item_name": "Ultra Milk Full Cream 250ml", "price": 6000},
    {"id": 104, "category": "Minuman & Susu", "subcategory": "Susu", "item_name": "Ultra Milk Cokelat 250ml", "price": 6000},
    {"id": 105, "category": "Minuman & Susu", "subcategory": "Susu", "item_name": "Ultra Milk Full Cream 1L", "price": 18000},
    {"id": 106, "category": "Minuman & Susu", "subcategory": "Susu", "item_name": "Indomilk Susu Cair Cokelat 190ml", "price": 5000},
    {"id": 107, "category": "Minuman & Susu", "subcategory": "Susu", "item_name": "Frisian Flag Susu Kental Manis Putih 37g", "price": 2500},
    {"id": 108, "category": "Minuman & Susu", "subcategory": "Susu", "item_name": "Frisian Flag Susu Kental Manis Cokelat 37g", "price": 2500},
    {"id": 109, "category": "Minuman & Susu", "subcategory": "Susu", "item_name": "Susu Dancow FortiGro Cokelat 27g", "price": 3000},
    {"id": 110, "category": "Minuman & Susu", "subcategory": "Susu", "item_name": "Bear Brand Susu Steril 189ml", "price": 9500},
    # --- Minuman Ringan ---
    {"id": 111, "category": "Minuman & Susu", "subcategory": "Minuman Ringan", "item_name": "Coca-Cola Kaleng 250ml", "price": 6000},
    {"id": 112, "category": "Minuman & Susu", "subcategory": "Minuman Ringan", "item_name": "Coca-Cola Pet 390ml", "price": 7500},
    {"id": 113, "category": "Minuman & Susu", "subcategory": "Minuman Ringan", "item_name": "Sprite Pet 390ml", "price": 7500},
    {"id": 114, "category": "Minuman & Susu", "subcategory": "Minuman Ringan", "item_name": "Fanta Strawberry Pet 390ml", "price": 7500},
    {"id": 115, "category": "Minuman & Susu", "subcategory": "Minuman Ringan", "item_name": "Pocari Sweat Botol 350ml", "price": 7000},
    {"id": 116, "category": "Minuman & Susu", "subcategory": "Minuman Ringan", "item_name": "Mizone Lychee Lemon 500ml", "price": 5500},

    # =========================================================================
    # KATEGORI 5: CAMILAN & JAJANAN (30 produk)
    # =========================================================================
    # --- Keripik & Snack ---
    {"id": 117, "category": "Camilan & Jajanan", "subcategory": "Keripik & Snack", "item_name": "Chitato Sapi Panggang 68g", "price": 10500},
    {"id": 118, "category": "Camilan & Jajanan", "subcategory": "Keripik & Snack", "item_name": "Chitato Lite Ayam Bumbu 68g", "price": 10500},
    {"id": 119, "category": "Camilan & Jajanan", "subcategory": "Keripik & Snack", "item_name": "Lays Rumput Laut 68g", "price": 10500},
    {"id": 120, "category": "Camilan & Jajanan", "subcategory": "Keripik & Snack", "item_name": "Qtela Tempe Original 55g", "price": 7000},
    {"id": 121, "category": "Camilan & Jajanan", "subcategory": "Keripik & Snack", "item_name": "Taro Net BBQ 36g", "price": 4500},
    {"id": 122, "category": "Camilan & Jajanan", "subcategory": "Keripik & Snack", "item_name": "Cheetos Jagung Bakar 40g", "price": 5000},
    {"id": 123, "category": "Camilan & Jajanan", "subcategory": "Keripik & Snack", "item_name": "Potabee BBQ Beef 68g", "price": 10500},
    {"id": 124, "category": "Camilan & Jajanan", "subcategory": "Keripik & Snack", "item_name": "Pringles Original 107g", "price": 25000},
    {"id": 125, "category": "Camilan & Jajanan", "subcategory": "Keripik & Snack", "item_name": "JetZ Paprika 35g", "price": 3500},
    {"id": 126, "category": "Camilan & Jajanan", "subcategory": "Keripik & Snack", "item_name": "Twistko Jagung Bakar 30g", "price": 2500},
    {"id": 127, "category": "Camilan & Jajanan", "subcategory": "Keripik & Snack", "item_name": "Lays Salmon Teriyaki 42g", "price": 7000},
    # --- Biskuit & Wafer ---
    {"id": 128, "category": "Camilan & Jajanan", "subcategory": "Biskuit & Wafer", "item_name": "Roma Kelapa 300g", "price": 10000},
    {"id": 129, "category": "Camilan & Jajanan", "subcategory": "Biskuit & Wafer", "item_name": "Roma Malkist Crackers 135g", "price": 8500},
    {"id": 130, "category": "Camilan & Jajanan", "subcategory": "Biskuit & Wafer", "item_name": "Oreo Original 137g", "price": 9500},
    {"id": 131, "category": "Camilan & Jajanan", "subcategory": "Biskuit & Wafer", "item_name": "Oreo Golden Vanilla 137g", "price": 9500},
    {"id": 132, "category": "Camilan & Jajanan", "subcategory": "Biskuit & Wafer", "item_name": "Good Time Chocochips Cookies 72g", "price": 8000},
    {"id": 133, "category": "Camilan & Jajanan", "subcategory": "Biskuit & Wafer", "item_name": "Tango Wafer Cokelat 130g", "price": 8500},
    {"id": 134, "category": "Camilan & Jajanan", "subcategory": "Biskuit & Wafer", "item_name": "Tango Wafer Susu Vanila 130g", "price": 8500},
    {"id": 135, "category": "Camilan & Jajanan", "subcategory": "Biskuit & Wafer", "item_name": "Khong Guan Assorted 300g", "price": 12000},
    {"id": 136, "category": "Camilan & Jajanan", "subcategory": "Biskuit & Wafer", "item_name": "Regal Marie 250g", "price": 10000},
    {"id": 137, "category": "Camilan & Jajanan", "subcategory": "Biskuit & Wafer", "item_name": "Monde Butter Cookies 150g", "price": 11000},
    {"id": 138, "category": "Camilan & Jajanan", "subcategory": "Biskuit & Wafer", "item_name": "Wafer Nabati Keju 145g", "price": 7500},
    # --- Permen & Cokelat ---
    {"id": 139, "category": "Camilan & Jajanan", "subcategory": "Permen & Cokelat", "item_name": "SilverQueen Chunky Bar 33g", "price": 8500},
    {"id": 140, "category": "Camilan & Jajanan", "subcategory": "Permen & Cokelat", "item_name": "SilverQueen Cashew 58g", "price": 12000},
    {"id": 141, "category": "Camilan & Jajanan", "subcategory": "Permen & Cokelat", "item_name": "KitKat 2 Finger 17g", "price": 5000},
    {"id": 142, "category": "Camilan & Jajanan", "subcategory": "Permen & Cokelat", "item_name": "Cadbury Dairy Milk 65g", "price": 12000},
    {"id": 143, "category": "Camilan & Jajanan", "subcategory": "Permen & Cokelat", "item_name": "Mentos Mint Roll 29g", "price": 5000},
    {"id": 144, "category": "Camilan & Jajanan", "subcategory": "Permen & Cokelat", "item_name": "Kopiko Coffee Candy 150g", "price": 9500},
    {"id": 145, "category": "Camilan & Jajanan", "subcategory": "Permen & Cokelat", "item_name": "Yupi Gummy Bears 45g", "price": 4000},
    {"id": 146, "category": "Camilan & Jajanan", "subcategory": "Permen & Cokelat", "item_name": "Relaxa Barley Mint 50g", "price": 3000},

    # =========================================================================
    # KATEGORI 6: PERAWATAN TUBUH / PERSONAL CARE (28 produk)
    # =========================================================================
    # --- Sabun ---
    {"id": 147, "category": "Perawatan Tubuh", "subcategory": "Sabun", "item_name": "Sabun Lifebuoy Merah 85g", "price": 4000},
    {"id": 148, "category": "Perawatan Tubuh", "subcategory": "Sabun", "item_name": "Sabun Lifebuoy Cair Total 100ml", "price": 7500},
    {"id": 149, "category": "Perawatan Tubuh", "subcategory": "Sabun", "item_name": "Sabun Lux Velvet Touch 85g", "price": 4500},
    {"id": 150, "category": "Perawatan Tubuh", "subcategory": "Sabun", "item_name": "Sabun Dettol Original 100g", "price": 7000},
    {"id": 151, "category": "Perawatan Tubuh", "subcategory": "Sabun", "item_name": "Sabun GIV White Mulberry 76g", "price": 3500},
    {"id": 152, "category": "Perawatan Tubuh", "subcategory": "Sabun", "item_name": "Sabun Nuvo Family 80g", "price": 3000},
    {"id": 153, "category": "Perawatan Tubuh", "subcategory": "Sabun", "item_name": "Sabun Cair Biore Body Foam 250ml", "price": 18000},
    # --- Sampo ---
    {"id": 154, "category": "Perawatan Tubuh", "subcategory": "Sampo", "item_name": "Shampoo Pantene Anti Dandruff 130ml", "price": 16000},
    {"id": 155, "category": "Perawatan Tubuh", "subcategory": "Sampo", "item_name": "Shampoo Pantene Hair Fall Control 130ml", "price": 16000},
    {"id": 156, "category": "Perawatan Tubuh", "subcategory": "Sampo", "item_name": "Shampoo Sunsilk Hijau 170ml", "price": 17000},
    {"id": 157, "category": "Perawatan Tubuh", "subcategory": "Sampo", "item_name": "Shampoo Clear Men Cool Sport 160ml", "price": 21000},
    {"id": 158, "category": "Perawatan Tubuh", "subcategory": "Sampo", "item_name": "Shampoo Head & Shoulders Cool Menthol 160ml", "price": 22000},
    {"id": 159, "category": "Perawatan Tubuh", "subcategory": "Sampo", "item_name": "Shampoo Dove Total Damage 160ml", "price": 20000},
    {"id": 160, "category": "Perawatan Tubuh", "subcategory": "Sampo", "item_name": "Shampoo Lifebuoy Anti Ketombe Sachet 10ml", "price": 1000},
    {"id": 161, "category": "Perawatan Tubuh", "subcategory": "Sampo", "item_name": "Shampoo Pantene Sachet 10ml", "price": 1000},
    # --- Pasta & Sikat Gigi ---
    {"id": 162, "category": "Perawatan Tubuh", "subcategory": "Pasta & Sikat Gigi", "item_name": "Pasta Gigi Pepsodent Pencegah Gigi Berlubang 120g", "price": 8500},
    {"id": 163, "category": "Perawatan Tubuh", "subcategory": "Pasta & Sikat Gigi", "item_name": "Pasta Gigi Pepsodent Herbal 120g", "price": 9500},
    {"id": 164, "category": "Perawatan Tubuh", "subcategory": "Pasta & Sikat Gigi", "item_name": "Pasta Gigi Close Up Menthol Fresh 65g", "price": 7500},
    {"id": 165, "category": "Perawatan Tubuh", "subcategory": "Pasta & Sikat Gigi", "item_name": "Pasta Gigi Formula Strong 150g", "price": 10000},
    {"id": 166, "category": "Perawatan Tubuh", "subcategory": "Pasta & Sikat Gigi", "item_name": "Sikat Gigi Pepsodent Triple Clean 1pcs", "price": 7500},
    {"id": 167, "category": "Perawatan Tubuh", "subcategory": "Pasta & Sikat Gigi", "item_name": "Sikat Gigi Formula Proteksi 1pcs", "price": 8000},
    # --- Deodoran & Parfum Sachet ---
    {"id": 168, "category": "Perawatan Tubuh", "subcategory": "Deodoran & Parfum", "item_name": "Rexona Men Deo Roll On 45ml", "price": 18000},
    {"id": 169, "category": "Perawatan Tubuh", "subcategory": "Deodoran & Parfum", "item_name": "Rexona Women Deo Roll On 45ml", "price": 18000},
    {"id": 170, "category": "Perawatan Tubuh", "subcategory": "Deodoran & Parfum", "item_name": "Gatsby Splash Cologne Ocean 100ml", "price": 15000},
    {"id": 171, "category": "Perawatan Tubuh", "subcategory": "Deodoran & Parfum", "item_name": "Nivea Men Deo Spray 150ml", "price": 35000},
    {"id": 172, "category": "Perawatan Tubuh", "subcategory": "Deodoran & Parfum", "item_name": "Vaseline Lotion Healthy White 100ml", "price": 14000},
    {"id": 173, "category": "Perawatan Tubuh", "subcategory": "Deodoran & Parfum", "item_name": "Citra Lotion Natural Glowing 230ml", "price": 17000},
    {"id": 174, "category": "Perawatan Tubuh", "subcategory": "Deodoran & Parfum", "item_name": "Marina Hand & Body Lotion 200ml", "price": 12000},

    # =========================================================================
    # KATEGORI 7: KEBERSIHAN RUMAH TANGGA (24 produk)
    # =========================================================================
    # --- Deterjen & Pelembut Pakaian ---
    {"id": 175, "category": "Kebersihan Rumah Tangga", "subcategory": "Deterjen & Pelembut", "item_name": "Rinso Anti Noda 770g", "price": 18000},
    {"id": 176, "category": "Kebersihan Rumah Tangga", "subcategory": "Deterjen & Pelembut", "item_name": "Rinso Cair 750ml", "price": 21000},
    {"id": 177, "category": "Kebersihan Rumah Tangga", "subcategory": "Deterjen & Pelembut", "item_name": "Attack Easy Deterjen 800g", "price": 17500},
    {"id": 178, "category": "Kebersihan Rumah Tangga", "subcategory": "Deterjen & Pelembut", "item_name": "Daia Deterjen Bunga 850g", "price": 14000},
    {"id": 179, "category": "Kebersihan Rumah Tangga", "subcategory": "Deterjen & Pelembut", "item_name": "So Klin Softergent 770g", "price": 15000},
    {"id": 180, "category": "Kebersihan Rumah Tangga", "subcategory": "Deterjen & Pelembut", "item_name": "Molto Pewangi Pink Sachet 20ml", "price": 1500},
    {"id": 181, "category": "Kebersihan Rumah Tangga", "subcategory": "Deterjen & Pelembut", "item_name": "Molto Pewangi Biru 800ml", "price": 16500},
    {"id": 182, "category": "Kebersihan Rumah Tangga", "subcategory": "Deterjen & Pelembut", "item_name": "Downy Pelembut Pakaian Sachet 20ml", "price": 1500},
    {"id": 183, "category": "Kebersihan Rumah Tangga", "subcategory": "Deterjen & Pelembut", "item_name": "Pewangi SoKlin Twilight Sensation 900ml", "price": 18000},
    # --- Sabun Cuci Piring ---
    {"id": 184, "category": "Kebersihan Rumah Tangga", "subcategory": "Sabun Cuci Piring", "item_name": "Sunlight Jeruk Nipis 755ml", "price": 14500},
    {"id": 185, "category": "Kebersihan Rumah Tangga", "subcategory": "Sabun Cuci Piring", "item_name": "Sunlight Lime 250ml", "price": 6500},
    {"id": 186, "category": "Kebersihan Rumah Tangga", "subcategory": "Sabun Cuci Piring", "item_name": "Mama Lemon Total Clean 780ml", "price": 13500},
    {"id": 187, "category": "Kebersihan Rumah Tangga", "subcategory": "Sabun Cuci Piring", "item_name": "Mama Lemon Pouch Refill 400ml", "price": 8000},
    {"id": 188, "category": "Kebersihan Rumah Tangga", "subcategory": "Sabun Cuci Piring", "item_name": "SOS Sabun Cuci Piring Jeruk 500ml", "price": 9000},
    # --- Pembersih Lantai ---
    {"id": 189, "category": "Kebersihan Rumah Tangga", "subcategory": "Pembersih Lantai", "item_name": "SOS Pembersih Lantai Orange 750ml", "price": 12000},
    {"id": 190, "category": "Kebersihan Rumah Tangga", "subcategory": "Pembersih Lantai", "item_name": "Super Pell Pembersih Lantai Lavender 770ml", "price": 11000},
    {"id": 191, "category": "Kebersihan Rumah Tangga", "subcategory": "Pembersih Lantai", "item_name": "Mr. Muscle Axi Triguna Lavender 800ml", "price": 13000},
    {"id": 192, "category": "Kebersihan Rumah Tangga", "subcategory": "Pembersih Lantai", "item_name": "Wipol Pembersih Lantai Classic Pine 750ml", "price": 14000},
    {"id": 193, "category": "Kebersihan Rumah Tangga", "subcategory": "Pembersih Lantai", "item_name": "Bayclin Pemutih Regular 500ml", "price": 9000},
    {"id": 194, "category": "Kebersihan Rumah Tangga", "subcategory": "Pembersih Lantai", "item_name": "Vixal Pembersih Toilet 500ml", "price": 15000},
    {"id": 195, "category": "Kebersihan Rumah Tangga", "subcategory": "Pembersih Lantai", "item_name": "Hit Expert Semprot Lavender 600ml", "price": 22000},
    {"id": 196, "category": "Kebersihan Rumah Tangga", "subcategory": "Pembersih Lantai", "item_name": "Spons Cuci Piring Scotch Brite 1pcs", "price": 5500},
    {"id": 197, "category": "Kebersihan Rumah Tangga", "subcategory": "Pembersih Lantai", "item_name": "Kantong Sampah Kresek Hitam 50pcs", "price": 8000},
    {"id": 198, "category": "Kebersihan Rumah Tangga", "subcategory": "Pembersih Lantai", "item_name": "Plastik Wrap Cling Wrap 30m", "price": 12000},

    # =========================================================================
    # KATEGORI 8: KEBUTUHAN HARIAN LAINNYA (22 produk)
    # =========================================================================
    # --- Obat Nyamuk ---
    {"id": 199, "category": "Kebutuhan Harian Lainnya", "subcategory": "Obat Nyamuk", "item_name": "Baygon Aerosol Lavender 600ml", "price": 22000},
    {"id": 200, "category": "Kebutuhan Harian Lainnya", "subcategory": "Obat Nyamuk", "item_name": "HIT Aerosol Lily Blossom 600ml", "price": 20000},
    {"id": 201, "category": "Kebutuhan Harian Lainnya", "subcategory": "Obat Nyamuk", "item_name": "Baygon Bakar Lavender 10pcs", "price": 10000},
    {"id": 202, "category": "Kebutuhan Harian Lainnya", "subcategory": "Obat Nyamuk", "item_name": "Soffell Lotion Anti Nyamuk 80ml", "price": 12000},
    {"id": 203, "category": "Kebutuhan Harian Lainnya", "subcategory": "Obat Nyamuk", "item_name": "Autan Lotion Anti Nyamuk 50ml", "price": 10000},
    # --- Tisu ---
    {"id": 204, "category": "Kebutuhan Harian Lainnya", "subcategory": "Tisu", "item_name": "Tisu Tessa TP-01 Travel Pack 50s", "price": 3500},
    {"id": 205, "category": "Kebutuhan Harian Lainnya", "subcategory": "Tisu", "item_name": "Tisu Passeo Facial 250s", "price": 13000},
    {"id": 206, "category": "Kebutuhan Harian Lainnya", "subcategory": "Tisu", "item_name": "Tisu Basah Mitu Baby 50s", "price": 15000},
    {"id": 207, "category": "Kebutuhan Harian Lainnya", "subcategory": "Tisu", "item_name": "Tisu Nice Facial 200s", "price": 10000},
    {"id": 208, "category": "Kebutuhan Harian Lainnya", "subcategory": "Tisu", "item_name": "Tisu Toilet Paseo 6 Roll", "price": 18000},
    # --- Baterai ---
    {"id": 209, "category": "Kebutuhan Harian Lainnya", "subcategory": "Baterai", "item_name": "Baterai ABC Super Power AA 2pcs", "price": 5000},
    {"id": 210, "category": "Kebutuhan Harian Lainnya", "subcategory": "Baterai", "item_name": "Baterai ABC Alkaline AA 2pcs", "price": 12000},
    {"id": 211, "category": "Kebutuhan Harian Lainnya", "subcategory": "Baterai", "item_name": "Baterai ABC Super Power AAA 2pcs", "price": 5000},
    {"id": 212, "category": "Kebutuhan Harian Lainnya", "subcategory": "Baterai", "item_name": "Baterai Panasonic Alkaline AA 2pcs", "price": 14000},
    # --- Korek Gas & Perlengkapan ---
    {"id": 213, "category": "Kebutuhan Harian Lainnya", "subcategory": "Korek & Perlengkapan", "item_name": "Korek Api Gas Cricket 1pcs", "price": 8000},
    {"id": 214, "category": "Kebutuhan Harian Lainnya", "subcategory": "Korek & Perlengkapan", "item_name": "Korek Api Gas Tokai 1pcs", "price": 5000},
    {"id": 215, "category": "Kebutuhan Harian Lainnya", "subcategory": "Korek & Perlengkapan", "item_name": "Korek Api Kayu Cap Ayam 1pak", "price": 3000},
    {"id": 216, "category": "Kebutuhan Harian Lainnya", "subcategory": "Korek & Perlengkapan", "item_name": "Lilin Besar Putih 1pcs", "price": 4000},
    {"id": 217, "category": "Kebutuhan Harian Lainnya", "subcategory": "Korek & Perlengkapan", "item_name": "Lem Alteco Super Glue 3g", "price": 6000},
    {"id": 218, "category": "Kebutuhan Harian Lainnya", "subcategory": "Korek & Perlengkapan", "item_name": "Selotip Bening Joyko 12mm x 25m", "price": 4000},
    {"id": 219, "category": "Kebutuhan Harian Lainnya", "subcategory": "Korek & Perlengkapan", "item_name": "Tali Rafia Gulung 200m", "price": 7000},
    {"id": 220, "category": "Kebutuhan Harian Lainnya", "subcategory": "Korek & Perlengkapan", "item_name": "Sedotan Plastik 50pcs", "price": 2000},
]
