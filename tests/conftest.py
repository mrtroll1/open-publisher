import sys
from pathlib import Path
from unittest.mock import MagicMock

# Ensure project root is on sys.path so imports work
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Stub external packages not available in the local dev environment.
# These are only needed at runtime (Google Sheets API, Postgres).
for _mod in (
    "googleapiclient", "googleapiclient.discovery", "googleapiclient.http",
    "psycopg2",
    "pyairtable",
):
    sys.modules.setdefault(_mod, MagicMock())
