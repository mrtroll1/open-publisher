"""Backward-compatible re-exports. Real code lives in handlers/ and handler_utils.py.

Includes __setattr__ propagation so that @patch("telegram_bot.flow_callbacks.X")
in tests also patches the actual handler module where X is used.
"""

import sys as _sys
import types as _types

import telegram_bot.handler_utils as _handler_utils
import telegram_bot.handlers.contractor_handlers as _contractor_handlers
import telegram_bot.handlers.admin_handlers as _admin_handlers
import telegram_bot.handlers.support_handlers as _support_handlers
import telegram_bot.handlers.group_handlers as _group_handlers
import telegram_bot.handlers.conversation_handlers as _conversation_handlers
import telegram_bot.handlers.email_listener as _email_listener

from telegram_bot.handler_utils import *  # noqa: F401,F403
from telegram_bot.handlers.contractor_handlers import *  # noqa: F401,F403
from telegram_bot.handlers.admin_handlers import *  # noqa: F401,F403
from telegram_bot.handlers.support_handlers import *  # noqa: F401,F403
from telegram_bot.handlers.group_handlers import *  # noqa: F401,F403
from telegram_bot.handlers.conversation_handlers import *  # noqa: F401,F403
from telegram_bot.handlers.email_listener import *  # noqa: F401,F403

# Re-export names that tests expect to find on flow_callbacks.
# These were top-level imports in the original monolithic file.
from common.config import BOT_USERNAME  # noqa: F401
from backend import fetch_articles, find_contractor, fuzzy_find, parse_contractor_data, update_legium_link  # noqa: F401
from backend.domain.services import compose_request  # noqa: F401
from backend.domain.services.compose_request import _get_retriever  # noqa: F401
from backend.domain.code_runner import run_claude_code  # noqa: F401
from backend.domain.services.command_classifier import CommandClassifier  # noqa: F401
from backend.domain.healthcheck import run_healthchecks, format_healthcheck_results  # noqa: F401
from backend.infrastructure.gateways.gemini_gateway import GeminiGateway  # noqa: F401
from backend.infrastructure.gateways.repo_gateway import RepoGateway  # noqa: F401
from telegram_bot.bot_helpers import bot, get_contractors  # noqa: F401

# Propagate @patch("telegram_bot.flow_callbacks.X") to actual handler modules.
_HANDLER_MODULES = [
    _handler_utils,
    _contractor_handlers,
    _admin_handlers,
    _support_handlers,
    _group_handlers,
    _conversation_handlers,
    _email_listener,
]


class _PatchProxyModule(_types.ModuleType):
    def __setattr__(self, name, value):
        super().__setattr__(name, value)
        for mod in _HANDLER_MODULES:
            if name in mod.__dict__:
                mod.__dict__[name] = value

    def __delattr__(self, name):
        super().__delattr__(name)
        for mod in _HANDLER_MODULES:
            if name in mod.__dict__:
                try:
                    del mod.__dict__[name]
                except KeyError:
                    pass


_sys.modules[__name__].__class__ = _PatchProxyModule
