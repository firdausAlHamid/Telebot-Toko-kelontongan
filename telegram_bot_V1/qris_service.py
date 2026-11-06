"""
qris_service.py — Service Client untuk Integrasi Pembayaran KlikQRIS Sandbox
=============================================================================
Menangani:
1. Pembuatan transaksi QRIS (/qris/create)
2. Pengecekan status berkala/polling (/qris/status/{order_id})
3. Riwayat transaksi (/qris/history)
4. Validasi signature & idempotency webhook
"""

import os
import json
import logging
from datetime import datetime
import httpx

try:
    from config import KLIKQRIS_BASE_URL, KLIKQRIS_API_KEY, KLIKQRIS_ID_MERCHANT
except (ImportError, AttributeError):
    KLIKQRIS_BASE_URL = os.getenv("KLIKQRIS_BASE_URL", "https://klikqris.id/api")
    KLIKQRIS_API_KEY = os.getenv("KLIKQRIS_API_KEY", "")
    KLIKQRIS_ID_MERCHANT = os.getenv("KLIKQRIS_ID_MERCHANT", "")

logger = logging.getLogger(__name__)

# File log untuk webhook mentah (audit & analisis di Tugas Akhir)
WEBHOOK_LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "qris_webhook.log")


def _get_headers() -> dict:
    """Header wajib untuk setiap request ke KlikQRIS Sandbox."""
    return {
        "Content-Type": "application/json",
        "x-api-key": KLIKQRIS_API_KEY,
        "id_merchant": str(KLIKQRIS_ID_MERCHANT),
    }


async def create_qris_transaction(order_id: str, amount: int, keterangan: str = "Pesanan Toko Kelontong") -> dict:
    """
    Membuat transaksi QRIS baru via KlikQRIS Sandbox API.
    
    Response sukses mengembalikan data transaksi lengkap:
    - order_id
    - amount (nominal pokok)
    - amount_uniq (kode unik)
    - total_amount (nominal final yang WAJIB dibayar pembeli)
    - qris_image (Base64 string data:image/png;base64,...)
    - qris_url (URL gambar QRIS)
    - expired_at
    - signature
    """
    # Pastikan URL tidak menduplikasi kata 'sandbox'
    base_url = KLIKQRIS_BASE_URL.rstrip("/")
    endpoint = f"{base_url}/qris/create"

    payload = {
        "order_id": str(order_id),
        "amount": int(amount),
        "id_merchant": str(KLIKQRIS_ID_MERCHANT),
        "keterangan": str(keterangan),
    }

    logger.info(f"Creating KlikQRIS transaction: order_id={order_id}, amount={amount}")

    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            resp = await client.post(endpoint, headers=_get_headers(), json=payload)
            resp.raise_for_status()
            res_json = resp.json()

            if not res_json.get("status"):
                raise ValueError(res_json.get("message") or "Gagal membuat transaksi QRIS di KlikQRIS.")

            data = res_json.get("data", {})
            return {
                "success": True,
                "order_id": data.get("order_id"),
                "nama_toko": data.get("nama_toko"),
                "amount": float(data.get("amount") or amount),
                "amount_uniq": float(data.get("amount_uniq") or 0),
                "total_amount": float(data.get("total_amount") or amount),
                "status": data.get("status", "PENDING"),
                "qris_url": data.get("qris_url"),
                "qris_image": data.get("qris_image"),
                "expired_at": data.get("expired_at"),
                "signature": data.get("signature"),
                "raw": data
            }

        except httpx.HTTPStatusError as e:
            logger.error(f"KlikQRIS HTTP error: {e.response.status_code} - {e.response.text}")
            raise RuntimeError(f"KlikQRIS error: {e.response.text}")
        except Exception as e:
            logger.error(f"Failed to call KlikQRIS create API: {e}")
            raise


async def get_qris_status(order_id: str) -> dict:
    """
    Mengecek status pembayaran order_id ke KlikQRIS Sandbox.
    Status yang mungkin: PENDING, SUCCESS, EXPIRED.
    """
    base_url = KLIKQRIS_BASE_URL.rstrip("/")
    endpoint = f"{base_url}/qris/status/{order_id}"

    async with httpx.AsyncClient(timeout=12.0) as client:
        try:
            resp = await client.get(endpoint, headers=_get_headers())
            resp.raise_for_status()
            res_json = resp.json()

            if not res_json.get("status"):
                return {"success": False, "status": "UNKNOWN", "message": res_json.get("message")}

            data = res_json.get("data", {})
            status = data.get("status", "PENDING").upper()

            return {
                "success": True,
                "order_id": data.get("order_id"),
                "status": status,  # "PENDING", "SUCCESS", "EXPIRED"
                "is_paid": status in ["SUCCESS", "PAID"],
                "total_amount": float(data.get("total_amount") or 0),
                "paid_at": data.get("paid_at"),
                "signature": data.get("signature"),
                "raw": data
            }
        except Exception as e:
            logger.error(f"Error fetching status for {order_id}: {e}")
            return {"success": False, "status": "ERROR", "error": str(e)}


async def get_qris_history(page: int = 1) -> dict:
    """Mengambil riwayat transaksi paginasi dari KlikQRIS Sandbox."""
    base_url = KLIKQRIS_BASE_URL.rstrip("/")
    endpoint = f"{base_url}/qris/history?page={page}"

    async with httpx.AsyncClient(timeout=12.0) as client:
        try:
            resp = await client.get(endpoint, headers=_get_headers())
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"Error fetching history: {e}")
            return {"status": False, "error": str(e)}


def log_webhook_payload(payload: dict):
    """Mencatat payload mentah webhook ke file log untuk audit akademik / debugging."""
    try:
        timestamp = datetime.now().isoformat()
        entry = {
            "timestamp": timestamp,
            "payload": payload
        }
        with open(WEBHOOK_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as e:
        logger.error(f"Failed to log webhook: {e}")


def validate_webhook_signature(stored_signature: str | None, incoming_signature: str | None, payload: dict) -> bool:
    """
    Validasi signature dari webhook KlikQRIS.

    Dokumentasi sandbox tidak merinci rumus hash, jadi yang dicek adalah
    kecocokan signature yang disimpan saat create dengan signature webhook.
    Jika transaksi punya signature tersimpan, incoming wajib cocok.
    """
    if stored_signature:
        if not incoming_signature:
            return False
        return stored_signature.strip() == incoming_signature.strip()
    return True


def decode_qris_image(qris_image: str | None):
    """Decode data-URL / base64 QRIS image into a named BytesIO, or None."""
    import base64
    from io import BytesIO

    if not qris_image:
        return None
    raw = qris_image.split(",", 1)[1] if qris_image.startswith("data:") and "," in qris_image else qris_image
    try:
        bio = BytesIO(base64.b64decode(raw))
        bio.name = "qris.png"
        bio.seek(0)
        return bio
    except Exception:
        return None
