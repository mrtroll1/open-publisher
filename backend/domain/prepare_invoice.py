"""Backward-compatible shim — moved to backend.domain.use_cases.prepare_invoice

Includes __setattr__ propagation so that @patch("backend.domain.prepare_invoice.X")
in tests also patches the actual use_cases module where X is used.
"""

import sys as _sys
import types as _types

import backend.domain.use_cases.prepare_invoice as _real_module

from backend.domain.use_cases.prepare_invoice import *  # noqa: F401,F403


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
