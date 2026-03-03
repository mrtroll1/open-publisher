"""Backward-compatible shim — moved to backend.domain.use_cases.compute_budget"""

from backend.domain.use_cases.compute_budget import *  # noqa: F401,F403
from backend.domain.use_cases.compute_budget import (  # noqa: F401
    _compute_budget_amount,
    _pick_by_currency,
    _role_label,
    _target_month_name,
)
