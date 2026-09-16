"""
config.py — Configuration for the POS Telegram Bot V2
=======================================================
HOW TO USE:
1. Copy this file: cp config.example.py config.py
2. Fill in your actual values in config.py
3. NEVER commit config.py to git!
"""

import os

# --- Bot Token ---
# Get from @BotFather on Telegram
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")

# --- API Secret Key ---
# Random secret for signing registration tokens and validating Mini App requests.
# Generate with: python -c "import secrets; print(secrets.token_hex(32))"
API_SECRET_KEY = os.getenv("API_SECRET_KEY", "YOUR_SECRET_KEY_HERE")

# --- API Server URL ---
# The URL where the FastAPI server is accessible (must be HTTPS for Mini App).
# For local dev: use ngrok and paste the https URL here.
# For production: your domain, e.g. "https://pos.yourdomain.com"
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")

# --- Owner Telegram ID ---
# Your own Telegram ID. Used as the super-admin.
# This ID can always use /panel even without registering via the website.
# Get your Telegram ID from @userinfobot on Telegram.
OWNER_TELEGRAM_ID = int(os.getenv("OWNER_TELEGRAM_ID", "0"))

# --- WhatsApp QR on Receipt ---
# Format: country code + number, no + sign
WHATSAPP_NUMBER = os.getenv("WHATSAPP_NUMBER", "628123456789")

# --- Promotion Settings ---
# Maximum number of promo recommendations printed on receipt
MAX_RECOMMENDATIONS = 2

# --- Database ---
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "mysql+pymysql://root@localhost/toko_kelontong?charset=utf8mb4"
)

# --- OpenRouter API Key (for AI voice commands) ---
# Get from https://openrouter.ai/keys
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")

# --- Groq API Key (for voice transcription) ---
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

# --- Model Selection ---
GROQ_TRANSCRIPTION_MODEL = "whisper-large-v3-turbo"
OPENROUTER_CHAT_MODEL = "google/gemini-2.5-flash:free"
