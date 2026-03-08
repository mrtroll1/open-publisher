"""Bot-specific configuration."""

import os
from pathlib import Path

from dotenv import load_dotenv

_CONFIG = Path(os.getenv("CONFIG_DIR", Path(__file__).resolve().parent.parent.parent.parent / "config"))

load_dotenv(_CONFIG / "bot.env", override=False)

# --- Telegram ---
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
ADMIN_TELEGRAM_TAG = os.environ["ADMIN_TELEGRAM_TAG"]
BOT_USERNAME = os.getenv("BOT_USERNAME", "")
PRODUCT_NAME = os.getenv("PRODUCT_NAME", "")

# --- Telethon (for chat history) ---
TELEGRAM_API_ID = int(os.getenv("TELEGRAM_API_ID", "0"))
TELEGRAM_API_HASH = os.getenv("TELEGRAM_API_HASH", "")

# --- Backend API ---
BACKEND_URL = os.getenv("BACKEND_URL", "http://api:8100")
