"""
Configuration constants for the Telegram POS Bot.
Centralized config — edit values here, not in individual modules.
"""

import os

# --- Bot Token ---
BOT_TOKEN = os.getenv("BOT_TOKEN", "8626634581:AAHVUmETYGPgNuM2m_vr5n263IbDWaP0xtE")

# --- Admin Access ---
# Telegram usernames (without @) allowed to manage promotions
ADMIN_USERNAMES = ["merkava1945"]

# --- WhatsApp QR on Receipt ---
# Format: country code + number, no + sign
WHATSAPP_NUMBER = "6281288252103"

# --- Promotion Settings ---
# Maximum number of promo recommendations printed on receipt
MAX_RECOMMENDATIONS = 2
