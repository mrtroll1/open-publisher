"""Configuration: env vars, Google auth, business config."""

import json
import os
from pathlib import Path

from dotenv import load_dotenv
from google.oauth2.service_account import Credentials

load_dotenv()

# --- Telegram ---
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
ADMIN_TELEGRAM_IDS = [
    int(x.strip()) for x in os.getenv("ADMIN_TELEGRAM_IDS", "").split(",") if x.strip()
]
ADMIN_TELEGRAM_TAG = os.environ["ADMIN_TELEGRAM_TAG"]

# --- Google ---
GOOGLE_SERVICE_ACCOUNT_FILE = os.getenv(
    "GOOGLE_SERVICE_ACCOUNT_FILE", "service_account.json"
)
GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/drive",
]


def get_google_creds() -> Credentials:
    return Credentials.from_service_account_file(
        GOOGLE_SERVICE_ACCOUNT_FILE, scopes=GOOGLE_SCOPES
    )


# --- Google Sheet IDs ---
CONTRACTORS_SHEET_ID = os.environ["CONTRACTORS_SHEET_ID"]

# --- Google Docs template IDs ---
TEMPLATE_SAMOZANYATY_ID = os.getenv(
    "TEMPLATE_SAMOZANYATY_ID"
)
TEMPLATE_IP_ID = os.getenv(
    "TEMPLATE_IP_ID" 
)
TEMPLATE_GLOBAL_ID = os.getenv(
    "TEMPLATE_GLOBAL_ID"
)

# --- Google Docs template IDs (photographer variants) ---
TEMPLATE_IP_PHOTO_ID = os.getenv("TEMPLATE_IP_PHOTO_ID")
TEMPLATE_SAMOZANYATY_PHOTO_ID = os.getenv("TEMPLATE_SAMOZANYATY_PHOTO_ID")
TEMPLATE_GLOBAL_PHOTO_ID = os.getenv("TEMPLATE_GLOBAL_PHOTO_ID")

# --- Google Drive folder IDs ---
DRIVE_FOLDER_RU = os.environ.get("DRIVE_FOLDER_RU", "")
DRIVE_FOLDER_GLOBAL = os.environ.get("DRIVE_FOLDER_GLOBAL", "")

# --- Budget Sheets ---
BUDGET_SHEETS_FOLDER_ID = os.getenv(
    "BUDGET_SHEETS_FOLDER_ID"
)
BUDGET_TEMPLATE_SHEET_ID = os.getenv(
    "BUDGET_TEMPLATE_SHEET_ID"
)

# --- Airtable ---
AIRTABLE_TOKEN = os.getenv("AIRTABLE_TOKEN", "")
AIRTABLE_BASE_ID = os.getenv("AIRTABLE_BASE_ID", "")
AIRTABLE_TABLE_NAME = os.getenv("AIRTABLE_TABLE_NAME", "expenses")

# --- Special Rules Sheet ---
SPECIAL_RULES_SHEET_ID = os.getenv("SPECIAL_RULES_SHEET_ID")

# --- Content API ---
CONTENT_API_URL = os.environ.get("CONTENT_API_URL", "")

# --- Gemini (for new-contractor parsing) ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# --- Product name (used in user-facing strings) ---
PRODUCT_NAME = os.getenv("PRODUCT_NAME", "")

# --- Entity constants (for invoice templates) ---
ENTITY_RU_NAME = os.getenv("ENTITY_RU_NAME", "")
ENTITY_RU_INN_KPP = os.getenv("ENTITY_RU_INN_KPP", "")
ENTITY_RU_OGRN = os.getenv("ENTITY_RU_OGRN", "")
ENTITY_RU_ADDRESS = os.getenv("ENTITY_RU_ADDRESS", "")
ENTITY_RU_EMAIL = os.getenv("ENTITY_RU_EMAIL", "")
ENTITY_UAE_NAME = os.getenv("ENTITY_UAE_NAME", "")
ENTITY_UAE_REG = os.getenv("ENTITY_UAE_REG", "")
ENTITY_UAE_ADDRESS = os.getenv("ENTITY_UAE_ADDRESS", "")

# --- Business config (loaded from business_config.json) ---
_BUSINESS_CONFIG_PATH = Path(__file__).resolve().parent.parent / "business_config.json"


def _load_business_config() -> dict:
    with open(_BUSINESS_CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


_biz = _load_business_config()

SERVICE_MAP: dict[str, dict] = _biz.get("service_map", {})
KNOWN_PEOPLE: dict[str, dict] = _biz.get("known_people", {})
OWNER_NAME: str = _biz.get("owner_name", "")
OWNER_KEYWORDS: list[str] = _biz.get("owner_keywords", [])
UNIT_PRIMARY: str = _biz.get("unit_primary", "")
UNIT_SECONDARY: str = _biz.get("unit_secondary", "")
DEFAULT_ENTITY: str = _biz.get("default_entity", "")
