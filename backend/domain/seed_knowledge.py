"""Backward-compatible shim — moved to backend.domain.use_cases.seed_knowledge

Includes __setattr__ propagation so that @patch("backend.domain.seed_knowledge.X")
in tests also patches the actual use_cases module where X is used.
"""

import sys as _sys
import types as _types

import backend.domain.use_cases.seed_knowledge as _real_module

from backend.domain.use_cases.seed_knowledge import *  # noqa: F401,F403
from backend.domain.use_cases.seed_knowledge import (  # noqa: F401
    _chunk_payment_validation,
    _chunk_tech_support,
    _read,
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
