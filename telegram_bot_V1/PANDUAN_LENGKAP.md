# 📖 Panduan Lengkap Bot POS Telegram V2 (Multi-Toko)

Sistem bot ini sudah diubah menjadi **Multi-Tenant** dengan **Role-Based Access Control (RBAC)**. Artinya, satu bot ini bisa menampung banyak toko yang berbeda tanpa datanya saling bercampur, dan fitur yang muncul di bot akan menyesuaikan dengan siapa yang sedang memakainya.

---

## 👥 1. Peran & Hak Akses (Siapa Bisa Apa?)

Setiap pengguna Telegram yang menggunakan bot ini akan dikelompokkan ke dalam 3 peran (role):

1. **👑 Pemilik Toko (Owner)**
   - **Bisa apa saja:** Menambah produk, atur harga (pakai suara/tombol), buka tutup jadwal toko, atur diskon/promo, lihat laporan penjualan semua kasir, batalkan (void) transaksi, dan bikin token untuk merekrut kasir baru.
   - *Hanya melihat data tokonya sendiri.*
2. **🧾 Kasir**
   - **Fokus jualan:** Memasukkan barang ke keranjang, cetak struk (bayar), tambah/kurangi stok barang, dan lihat laporan shift miliknya sendiri.
   - *Tidak bisa* hapus produk, atur harga, atau ngintip panel owner.
3. **🙋 Pelanggan (Customer)**
   - **Cuma bisa lihat:** Buka katalog barang, lihat harga, cek promo yang lagi aktif, dan cek jadwal buka/tutup toko.
   - *Tidak bisa* melihat menu transaksi kasir atau pengaturan toko.

---

## 🚀 2. Cara Menjalankan Sistem (Untuk Developer)

Karena sekarang bot ini butuh sinkronisasi dengan *Mini App* (Dashboard) dan Web Pendaftaran, cara jalaninnya nggak bisa cuma `python main.py` aja.

**Syarat utama:** MySQL harus sudah nyala (dari XAMPP / Laragon).

**Langkah:**
1. Buka PowerShell, masuk ke folder `telegram_bot_V1`.
2. Jalankan perintah ini:
   ```powershell
   powershell -ExecutionPolicy Bypass -File .\start.ps1
   ```
3. **Selesai.** Biarkan terminal itu terbuka. Script tersebut akan otomatis:
   - Menyalakan API Server (FastAPI).
   - Menyalakan `ngrok` (supaya API Server & Mini App bisa diakses Telegram lewat HTTPS).
   - Menulis URL ngrok ke file `.env`.
   - Menjalankan bot Telegram.

*(Jika kamu menutup terminal ini, matikan juga jendela kecil ngrok yang terbuka, supaya saat jalanin lagi nggak error bentrok).*

---

## 🌍 3. Alur Penggunaan Asli (Di Dunia Nyata)

Bagaimana cara orang awam memakai sistem ini? Begini alur normalnya:

### A. Alur Owner (Mendaftar Toko Baru)
1. Orang membuka website pendaftaran kita: `https://<url-ngrok>/website/`
2. Dia isi nama toko dan username Telegram-nya, lalu klik Daftar.
3. Website akan kasih dia kode rahasia, misalnya: `POS-OWNER-A1B2C3D4`
4. Dia buka Telegram, cari `@yabos_bot`, ketik `/start`.
5. Bot menyuruh masukkan token. Dia paste token `POS-OWNER...` tadi.
6. **Boom!** Dia langsung diangkat jadi Owner toko tersebut dan menu Owner muncul.

### B. Alur Kasir (Direkrut oleh Owner)
1. Owner buka bot Telegram, klik menu **⚙️ Panel Owner**.
2. Owner klik **🔑 Generate Token Kasir**. Bot ngasih token: `POS-KASIR-99887766`.
3. Owner ngasih token itu ke karyawannya (Kasir) lewat chat biasa.
4. Karyawan buka `@yabos_bot`, ketik `/start`, lalu paste token tersebut.
5. **Boom!** Karyawan resmi jadi Kasir di toko si Owner.

### C. Alur Customer
1. Setelah pelanggan selesai belanja di kasir, di struk belanjanya akan ada *QR Code* atau link: `t.me/yabos_bot?start=toko_1` (angka 1 adalah ID toko).
2. Pelanggan klik link itu, otomatis buka Telegram.
3. Bot langsung mencatat dia sebagai Customer di Toko 1.
4. Pelanggan bisa klik tombol **🛒 Katalog Produk** untuk lihat-lihat barang.

---

## 🛠 4. Cara Testing Cepat (Khusus Developer)

Sebagai developer (kamu), ngikutin alur pendaftaran asli di atas pasti capek banget kalau cuma mau ngetes fitur. Makanya gua buatin 2 alat khusus buat kamu (Gated by ID Telegram kamu `1170387402` di `config.py`):

### Alat 1: Command `/devrole` di Telegram
Gunakan ini untuk berganti-ganti wujud di dalam bot tanpa bikin akun Telegram banyak-banyak.
- Di chat bot, ketik: `/devrole`
- Muncul pilihan: `Owner`, `Kasir`, `Customer`, atau `Reset`.
- Misalnya kamu pilih `Kasir`, lalu pilih `Toko Demo`. Detik itu juga kamu berubah jadi kasir. Kamu bisa langsung tes alur kasir.
- Kalau mau ngetes masukin Token, pilih **🚪 Reset** dulu biar akunmu dihapus sementara dari sistem, jadi sistem ngira kamu user baru.

### Alat 2: Script `buat_token.py` di Terminal
Gunakan ini kalau kamu butuh token instan buat ngetes alur login tanpa harus buka website atau pencet panel owner.
- Buka terminal baru (jangan tutup terminal bot yang lagi jalan).
- Lihat daftar toko:
  ```bash
  python buat_token.py
  ```
- Bikin token Kasir untuk Toko ID 5:
  ```bash
  python buat_token.py kasir 5
  ```
- Bikin Toko Baru sekalian ambil token Owner-nya:
  ```bash
  python buat_token.py owner "Toko Percobaan"
  ```

---

## ❓ 5. Tanya Jawab (FAQ) Developer

**T: Kok tombol 📊 Dashboard di Mini App bot saya hilang/nggak mau dipencet?**
J: Pastikan kamu menjalankan bot lewat `.\start.ps1`. Telegram mewajibkan Mini App pakai link `https`. Kalau kamu jalanin cuma pakai `python main.py`, bot akan pakai `http://localhost` dan Telegram akan otomatis menyembunyikan tombolnya.

**T: Kalau ngrok-nya expired (tiap 2 jam mati sendiri karena gratis), gimana?**
J: Stop bot di terminal (tekan `Ctrl+C`), tutup jendela hitam ngrok, lalu jalankan `powershell -ExecutionPolicy Bypass -File .\start.ps1` lagi. Dia bakal ambil link HTTPS baru dan bot siap jalan lagi.

**T: Gimana caranya nyuruh bot ngerekam suara (Voice Note)?**
J: Menu Voice Note cuma buat Owner. Masuk ke mode Owner (bisa pakai `/devrole`), lalu cukup tekan tombol mikrofon di Telegram dan tahan. Ngomong *"Ubah harga semen jadi 50 ribu"*, lalu kirim. AI bakal nangkep maksudnya dan ngerubah databasenya otomatis.

**T: Data antar toko beneran aman nggak bocor?**
J: Aman bro. Setiap perintah ke database (di `product_handlers.py`, `transaction_service.py`, dll) sekarang disaring pakai filter `tenant_id`. Jadi Toko A nggak akan pernah bisa narik produk atau laporan penjualan dari Toko B.
