"""Backward-compatible shim — moved to backend.domain.services.tech_support_handler

Includes __setattr__ propagation so that @patch("backend.domain.tech_support_handler.X")
in tests also patches the actual services module where X is used.
"""

import sys as _sys
import types as _types

import backend.domain.services.tech_support_handler as _real_module

from backend.domain.services.tech_support_handler import *  # noqa: F401,F403


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
