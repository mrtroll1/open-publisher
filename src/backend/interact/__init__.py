"""Unified interaction handler — single entry point for all bot business logic."""

from __future__ import annotations

import logging

from backend.interact.admin import AdminHandlers
from backend.interact.contractor import ContractorHandlers
from backend.interact.helpers import InteractContext, Payload
from backend.models import ProgressEmitter

logger = logging.getLogger(__name__)

_admin = AdminHandlers()
_contractor = ContractorHandlers()

_HANDLERS = {
    # Contractor commands
    "start": _contractor.start,
    "menu": _contractor.menu,
    "sign_doc": _contractor.sign_doc,
    "update_payment_data": _contractor.update_payment_data,
    "manage_redirects": _contractor.manage_redirects,
    "change_type": _contractor.change_type,

    # Contractor FSM inputs
    "free_text": _contractor.free_text,
    "type_selection": _contractor.type_selection,
    "data_input": _contractor.data_input,
    "verification_code": _contractor.verification_code,
    "amount_input": _contractor.amount_input,
    "update_data": _contractor.update_data,
    "editor_source_name": _contractor.editor_source_name,

    # Contractor callbacks
    "dup_callback": _contractor.dup_callback,
    "esrc_callback": _contractor.esrc_callback,
    "menu_callback": _contractor.menu_callback,

    # File handling
    "document": _contractor.document,
    "non_document": _contractor.non_document,

    # Admin commands
    "admin_generate": _admin.generate,
    "admin_articles": _admin.articles,
    "admin_lookup": _admin.lookup,
    "admin_batch_generate": _admin.batch_generate,
    "admin_send_global": _admin.send_global,
    "admin_send_legium": _admin.send_legium,
    "admin_orphans": _admin.orphans,
    "admin_upload_statement": _admin.upload_statement,
    "admin_legium_reply": _admin.legium_reply,
}


def handle(action: str, payload: Payload, context: InteractContext,
           progress: ProgressEmitter | None = None) -> dict:
    handler = _HANDLERS.get(action)
    if not handler:
        return {"messages": [{"text": f"Неизвестное действие: {action}"}]}
    if progress is None:
        progress = ProgressEmitter()
    context["progress"] = progress
    try:
        result = handler(payload, context)
    except Exception as e:
        logger.exception("Interact error: action=%s", action)
        return {"messages": [{"text": f"Ошибка: {e}"}]}
    if progress.events:
        result["progress"] = [{"stage": e.stage, "detail": e.detail} for e in progress.events]
    return result
