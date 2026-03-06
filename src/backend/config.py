"""Configuration: env vars, Google auth, business config."""

import json
import os
from pathlib import Path

from dotenv import load_dotenv
from google.oauth2.service_account import Credentials

_ROOT = Path(__file__).resolve().parent.parent
_CONFIG = Path(os.getenv("CONFIG_DIR", _ROOT / "config"))

# In Docker: env vars come from env_file directive. Locally: load from file.
load_dotenv(_CONFIG / "backend.env", override=False)

# --- Admin ---
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

# --- Republic API ---
REPUBLIC_API_URL = os.environ.get("REPUBLIC_API_URL", "")

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
REPUBLIC_SUPPORT_API_KEY = os.getenv("REPUBLIC_SUPPORT_API_KEY", "")
REDEFINE_API_URL = os.getenv("REDEFINE_API_URL", "")
REDEFINE_SUPPORT_API_KEY = os.getenv("REDEFINE_SUPPORT_API_KEY", "")

# --- PNL (uses Redefine API) ---
EUR_RUB_CELL = os.getenv("EUR_RUB_CELL", "")

# --- Repos ---
REPOS_DIR = os.getenv("REPOS_DIR", "/opt/repos")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# Dynamic: every REPO_* env var becomes a clone target (REPO_FOO_BAR=url -> "foo-bar": url)
REPO_URLS: dict[str, str] = {}
for _k, _v in os.environ.items():
    if _k.startswith("REPO_") and _k != "REPOS_DIR" and _v:
        REPO_URLS[_k[5:].lower().replace("_", "-")] = _v

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

# --- Scheduling intervals (seconds) ---
KNOWLEDGE_PIPELINE_INTERVAL = int(os.getenv("KNOWLEDGE_PIPELINE_INTERVAL", 6 * 3600))
EMAIL_POLL_INTERVAL = int(os.getenv("EMAIL_POLL_INTERVAL", 60))
EMAIL_RECENT_WINDOW = int(os.getenv("EMAIL_RECENT_WINDOW", 120))
EMAIL_IDLE_TIMEOUT = int(os.getenv("EMAIL_IDLE_TIMEOUT", 300))
EMAIL_ERROR_RETRY_DELAY = int(os.getenv("EMAIL_ERROR_RETRY_DELAY", 30))

# --- Knowledge expiry (days) ---
EXPIRY_CONVERSATION_FACTS_DAYS = int(os.getenv("EXPIRY_CONVERSATION_FACTS_DAYS", 30))
EXPIRY_ARTICLE_SUMMARY_DAYS = int(os.getenv("EXPIRY_ARTICLE_SUMMARY_DAYS", 90))
EXPIRY_COMPETITOR_SUMMARY_DAYS = int(os.getenv("EXPIRY_COMPETITOR_SUMMARY_DAYS", 90))

# --- External DBs (read-only, via SSH tunnel) ---
REPUBLIC_SSH_HOST = os.getenv("REPUBLIC_SSH_HOST", "")
REPUBLIC_SSH_USER = os.getenv("REPUBLIC_SSH_USER", "")
REPUBLIC_SSH_KEY_PATH = os.getenv("REPUBLIC_SSH_KEY_PATH", "")
REPUBLIC_RO_DB_HOST = os.getenv("REPUBLIC_RO_DB_HOST", "127.0.0.1")
REPUBLIC_RO_DB_PORT = int(os.getenv("REPUBLIC_RO_DB_PORT", "5432"))
REPUBLIC_RO_DB_NAME = os.getenv("REPUBLIC_RO_DB_NAME", "")
REPUBLIC_RO_DB_USER = os.getenv("REPUBLIC_RO_DB_USER", "")
REPUBLIC_RO_DB_PASS = os.getenv("REPUBLIC_RO_DB_PASS", "")

REDEFINE_SSH_HOST = os.getenv("REDEFINE_SSH_HOST", "")
REDEFINE_SSH_USER = os.getenv("REDEFINE_SSH_USER", "")
REDEFINE_SSH_KEY_PATH = os.getenv("REDEFINE_SSH_KEY_PATH", "")
REDEFINE_RO_DB_HOST = os.getenv("REDEFINE_RO_DB_HOST", "127.0.0.1")
REDEFINE_RO_DB_PORT = int(os.getenv("REDEFINE_RO_DB_PORT", "5432"))
REDEFINE_RO_DB_NAME = os.getenv("REDEFINE_RO_DB_NAME", "")
REDEFINE_RO_DB_USER = os.getenv("REDEFINE_RO_DB_USER", "")
REDEFINE_RO_DB_PASS = os.getenv("REDEFINE_RO_DB_PASS", "")

# --- Healthcheck ---
HEALTHCHECK_DOMAINS = [
    d.strip() for d in os.getenv("HEALTHCHECK_DOMAINS", "republicmag.io,redefine.media").split(",") if d.strip()
]
KUBECTL_ENABLED = os.getenv("KUBECTL_ENABLED", "").lower() in ("1", "true", "yes")

# --- Backend API ---
BACKEND_URL = os.getenv("BACKEND_URL")
