"""Backward-compatible shim — moved to backend.domain.use_cases.parse_bank_statement

Includes __setattr__ propagation so that @patch("backend.domain.parse_bank_statement.X")
in tests also patches the actual use_cases module where X is used.
"""

import sys as _sys
import types as _types

import backend.domain.use_cases.parse_bank_statement as _real_module

from backend.domain.use_cases.parse_bank_statement import *  # noqa: F401,F403
from backend.domain.use_cases.parse_bank_statement import (  # noqa: F401
    _FROM_PATTERN,
    _TO_PATTERN,
    _aggregate_fx_fees,
    _aggregate_swift_fees,
    _bo,
    _categorize_transactions,
    _classify_person,
    _handle_card_payment,
    _handle_fee,
    _handle_incoming_transfer,
    _handle_outgoing_transfer,
    _is_owner,
    _match_service,
    _month_label,
    _read_csv,
    _to_rub,
)


class _PatchProxyModule(_types.ModuleType):
    def __setattr__(self, name, value):
        super().__setattr__(name, value)
        if name in _real_module.__dict__:
            _real_module.__dict__[name] = value

    def __delattr__(self, name):
        super().__delattr__(name)
        if name in _real_module.__dict__:
            try:
                del _real_module.__dict__[name]
            except KeyError:
                pass


_sys.modules[__name__].__class__ = _PatchProxyModule
