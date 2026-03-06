"""Unified interaction handler — single entry point for all bot business logic."""

import logging
from backend.interact import contractor as _contractor
from backend.interact import admin as _admin

logger = logging.getLogger(__name__)

_HANDLERS = {
    # Contractor commands
    "start": _contractor.handle_start,
    "menu": _contractor.handle_menu,
    "sign_doc": _contractor.handle_sign_doc,
    "update_payment_data": _contractor.handle_update_payment_data,
    "manage_redirects": _contractor.handle_manage_redirects,

    # Contractor FSM inputs
    "free_text": _contractor.handle_free_text,
    "type_selection": _contractor.handle_type_selection,
    "data_input": _contractor.handle_data_input,
    "verification_code": _contractor.handle_verification_code,
    "amount_input": _contractor.handle_amount_input,
    "update_data": _contractor.handle_update_data,
    "editor_source_name": _contractor.handle_editor_source_name,

    # Contractor callbacks
    "dup_callback": _contractor.handle_dup_callback,
    "esrc_callback": _contractor.handle_esrc_callback,
    "menu_callback": _contractor.handle_menu_callback,

    # File handling
    "document": _contractor.handle_document,
    "non_document": _contractor.handle_non_document,

    # Admin commands
    "admin_generate": _admin.handle_generate,
    "admin_articles": _admin.handle_articles,
    "admin_lookup": _admin.handle_lookup,
    "admin_batch_generate": _admin.handle_batch_generate,
    "admin_send_global": _admin.handle_send_global,
    "admin_send_legium": _admin.handle_send_legium,
    "admin_orphans": _admin.handle_orphans,
    "admin_upload_statement": _admin.handle_upload_statement,
    "admin_legium_reply": _admin.handle_legium_reply,
}


def handle(action: str, payload: dict, context: dict) -> dict:
    """Dispatch to the appropriate handler.

    Response format:
        messages: list of {text, keyboard?, file_b64?, filename?, track?}
        side_messages: list of {chat_id, text, file_b64?, filename?, track?}
        fsm_state: str (set) | None (clear) | absent (keep)
        fsm_data: dict (replace) | absent (keep)
    """
    handler = _HANDLERS.get(action)
    if not handler:
        return {"messages": [{"text": f"Неизвестное действие: {action}"}]}
    try:
        return handler(payload, context)
    except Exception as e:
        logger.exception("Interact error: action=%s", action)
        return {"messages": [{"text": f"Ошибка: {e}"}]}
