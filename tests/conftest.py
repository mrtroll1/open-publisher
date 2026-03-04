import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure project root is on sys.path so imports work
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Stub external packages not available in the local dev environment.
# These are only needed at runtime (Google Sheets API, Postgres, Embeddings).
for _mod in (
    "googleapiclient", "googleapiclient.discovery", "googleapiclient.http",
    "psycopg2",
    "pyairtable",
    "google.genai", "google.genai.types", "google.genai.errors",
):
    sys.modules.setdefault(_mod, MagicMock())


# Stub KnowledgeRetriever so tests don't need real embeddings / DB.
_mock_retriever = MagicMock()
_mock_retriever.get_core.return_value = ""
_mock_retriever.get_domain_context.return_value = ""
_mock_retriever.retrieve.return_value = ""
_mock_retriever.retrieve_full_domain.return_value = ""


@pytest.fixture(autouse=True)
def _stub_knowledge_retriever():
    with patch("backend.domain.services.compose_request._get_retriever", return_value=_mock_retriever):
        yield
