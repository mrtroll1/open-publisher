"""Backward-compatible shim — moved to backend.infrastructure.repositories.sheets.rules_repo"""

from backend.infrastructure.repositories.sheets.rules_repo import *  # noqa: F401,F403
from backend.infrastructure.repositories.sheets.rules_repo import (  # noqa: F401
    ArticleRateRule,
    FlatRateRule,
    RedirectRule,
)
