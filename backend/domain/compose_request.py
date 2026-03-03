"""Backward-compatible shim — moved to backend.domain.services.compose_request

Includes __setattr__ propagation so that @patch("backend.domain.compose_request.X")
in tests also patches the actual services module where X is used.
"""

import sys as _sys
import types as _types

import backend.domain.services.compose_request as _real_module

from backend.domain.services.compose_request import *  # noqa: F401,F403
from backend.domain.services.compose_request import (  # noqa: F401
    _MODELS,
    _get_retriever,
    _retriever,
    set_retriever,
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
