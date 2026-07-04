"""
Configuration constants for the Telegram POS Bot.
Centralized config — edit values here, not in individual modules.

HOW TO USE:
1. Copy this file: cp config.example.py config.py
2. Fill in your actual values in config.py
3. NEVER commit config.py to git!
"""

import os

# --- Bot Token ---
# Get from @BotFather on Telegram
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")

# --- Gemini AI API Key ---
# Get from https://aistudio.google.com/apikey
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "YOUR_GEMINI_API_KEY_HERE")

# --- Admin Access ---
# Telegram usernames (without @) allowed to manage promotions
ADMIN_USERNAMES = ["your_username"]

# --- WhatsApp QR on Receipt ---
# Format: country code + number, no + sign
WHATSAPP_NUMBER = "628123456789"

# --- Promotion Settings ---
# Maximum number of promo recommendations printed on receipt
MAX_RECOMMENDATIONS = 2
