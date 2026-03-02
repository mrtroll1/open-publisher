"""Configuration: env vars, Google auth, business config."""

import json
import os
from pathlib import Path

from dotenv import load_dotenv
from google.oauth2.service_account import Credentials

_ROOT = Path(__file__).resolve().parent.parent
_CONFIG = _ROOT / "config"

load_dotenv(_CONFIG / ".env")

# --- Telegram ---
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
ADMIN_TELEGRAM_IDS = [
    int(x.strip()) for x in os.getenv("ADMIN_TELEGRAM_IDS", "").split(",") if x.strip()
]
ADMIN_TELEGRAM_TAG = os.environ["ADMIN_TELEGRAM_TAG"]

# --- Google ---
GOOGLE_SERVICE_ACCOUNT_FILE = os.environ["GOOGLE_SERVICE_ACCOUNT_FILE"]
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

# --- Database ---
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://agent:agent_dev_pass@db:5432/republic_agent")

# --- Email (support inbox via Gmail API) ---
EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS", "")
GMAIL_CLIENT_ID = os.getenv("GMAIL_CLIENT_ID", "")
GMAIL_CLIENT_SECRET = os.getenv("GMAIL_CLIENT_SECRET", "")
GMAIL_REFRESH_TOKEN = os.getenv("GMAIL_REFRESH_TOKEN", "")
CHIEF_EDITOR_EMAIL = os.getenv("CHIEF_EDITOR_EMAIL", "")


def get_gmail_creds():
    """Build Gmail OAuth2 credentials from refresh token."""
    from google.oauth2.credentials import Credentials as OAuthCredentials

    return OAuthCredentials(
        token=None,
        refresh_token=GMAIL_REFRESH_TOKEN,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=GMAIL_CLIENT_ID,
        client_secret=GMAIL_CLIENT_SECRET,
        scopes=["https://mail.google.com/"],
    )

# --- Subscription service ---
SUBSCRIPTION_SERVICE_URL = os.getenv("SUBSCRIPTION_SERVICE_URL", "")

# --- Support APIs (user data lookup) ---
REPUBLIC_API_URL = os.getenv("REPUBLIC_API_URL", "")
REPUBLIC_SUPPORT_API_KEY = os.getenv("REPUBLIC_SUPPORT_API_KEY", "")
REDEFINE_API_URL = os.getenv("REDEFINE_API_URL", "")
REDEFINE_SUPPORT_API_KEY = os.getenv("REDEFINE_SUPPORT_API_KEY", "")

# --- PNL (uses Redefine API) ---
EUR_RUB_CELL = os.getenv("EUR_RUB_CELL", "")

# --- Repos ---
REPOS_DIR = os.getenv("REPOS_DIR", "/opt/repos")
REPUBLIC_REPO_URL = os.getenv("REPUBLIC_REPO_URL", "")
REDEFINE_REPO_URL = os.getenv("REDEFINE_REPO_URL", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

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

# --- Business config ---
_BUSINESS_CONFIG_PATH = _CONFIG / "business_config.json"


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

# --- Tech config ---
_TECH_CONFIG_PATH = _CONFIG / "tech_config.json"


def _load_tech_config() -> dict:
    if _TECH_CONFIG_PATH.exists():
        with open(_TECH_CONFIG_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {}


_tech = _load_tech_config()

SUPPORT_ADDRESSES: list[str] = _tech.get("support_addresses", [])

# --- Groupchat ---
EDITORIAL_CHAT_ID = int(os.getenv("EDITORIAL_CHAT_ID", "0"))
BOT_USERNAME = os.getenv("BOT_USERNAME", "")

# --- Healthcheck ---
HEALTHCHECK_DOMAINS = [
    d.strip() for d in os.getenv("HEALTHCHECK_DOMAINS", "republicmag.io,redefine.media").split(",") if d.strip()
]
KUBECTL_ENABLED = os.getenv("KUBECTL_ENABLED", "").lower() in ("1", "true", "yes")
