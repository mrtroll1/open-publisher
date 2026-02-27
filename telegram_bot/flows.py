"""
Declarative flow definitions for the YaIzdatel Telegram bot.
==========================================================

This file IS the documentation. Each flow reads like a state machine diagram.
Custom logic lives in flow_callbacks.py, referenced here by name.

Flows:
  1. Contractor:    free text -> lookup/register -> invoice
  2. Documents:     file upload -> forward to admin
  3. Admin commands: /generate, /budget
"""

from telegram_bot.flow_dsl import (
    AdminCommand,
    BotFlows,
    Flow,
    FlowState,
    InputType,
    Transition,
)
from telegram_bot import replies
from telegram_bot.flow_callbacks import (
    handle_start,
    # Contractor flow
    handle_contractor_text,
    handle_verification_code,
    handle_type_selection,
    handle_data_input,
    handle_amount_input,
    # Document upload
    handle_document,
    # Admin
    handle_admin_reply,
    cmd_generate,
    cmd_budget,
    cmd_generate_invoices,
    cmd_send_global_invoices,
    cmd_upload_to_airtable,
)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  CONTRACTOR FLOW (unified: lookup + registration)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#
#  free text (no active state)
#    |
#    +-- [telegram_id bound] -> greet -> END
#    +-- [fuzzy matches] -> inline buttons -> stay
#    +-- [no match] -> waiting_type (registration)
#
#  inline button (dup:ID)
#    +-- [already bound to other] -> "already linked" -> stay
#    +-- [ok] -> waiting_verification (secret code)
#
#  waiting_verification
#    |  [correct code] -> bind TG -> greet -> END
#    |  [wrong, <3 attempts] -> stay
#    |  [wrong, >=3 attempts] -> "contact admin" -> END
#
#  waiting_type  (registration)
#    |  prompt: "1=Самозанятый, 2=ИП, 3=Global"
#    |  -> waiting_data
#
#  waiting_data  (registration)
#    |  LLM parses free-form text
#    |  [all valid, no articles] -> save -> END
#    |  [all valid, has articles] -> save -> waiting_amount
#
#  waiting_amount  (new contractor invoice)
#    |  amount input or /ok
#    |  -> generate invoice -> END
#
contractor_flow = Flow(
    name="contractor",
    description="Unified contractor flow: lookup and registration",
    trigger="text",
    states=[
        FlowState(
            name="lookup",
            handler=handle_contractor_text,
            transitions={
                "register": Transition(
                    to="waiting_type",
                    message=replies.registration.begin,
                ),
            },
        ),
        FlowState(
            name="waiting_verification",
            handler=handle_verification_code,
            transitions={
                "verified": Transition(to="end"),
                "invoice": Transition(to="waiting_amount"),
            },
        ),
        FlowState(
            name="waiting_type",
            message=replies.registration.type_prompt,
            handler=handle_type_selection,
            transitions={
                "valid": Transition(to="waiting_data"),
            },
        ),
        FlowState(
            name="waiting_data",
            # prompt is dynamic (depends on type), sent by handle_type_selection
            handler=handle_data_input,
            transitions={
                "complete": Transition(to="end"),
                "invoice": Transition(to="waiting_amount"),
            },
        ),
        FlowState(
            name="waiting_amount",
            handler=handle_amount_input,
            transitions={
                "done": Transition(to="end"),
            },
        ),
    ],
)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  DOCUMENT UPLOAD FLOW
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#
#  document message
#    +-- [admin] -> ignore
#    +-- [contractor] -> forward to admins -> END
#
document_flow = Flow(
    name="document",
    description="Handle document uploads from contractors and admins",
    trigger="document",
    states=[
        FlowState(
            name="handle_upload",
            handler=handle_document,
            input_type=InputType.DOCUMENT,
        ),
    ],
)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  ADMIN COMMANDS (stateless)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#
#  /generate <n>   -> find contractor -> fetch articles -> generate PDF
#  /budget         -> "in development"
#
admin_commands = [
    AdminCommand(
        command="generate",
        description="Сгенерировать документ для контрагента",
        handler=cmd_generate,
        usage="/generate <имя контрагента>",
    ),
    AdminCommand(
        command="generate_invoices",
        description="Сгенерировать счета для всех контрагентов",
        handler=cmd_generate_invoices,
        usage="/generate_invoices",
    ),
    AdminCommand(
        command="send_global_invoices",
        description="Отправить глобальные счета контрагентам в Telegram",
        handler=cmd_send_global_invoices,
        usage="/send_global_invoices",
    ),
    AdminCommand(
        command="budget",
        description="Расчёт бюджета (в разработке)",
        handler=cmd_budget,
        usage="/budget",
    ),
    AdminCommand(
        command="upload_to_airtable",
        description="Загрузить банковскую выписку в Airtable",
        handler=cmd_upload_to_airtable,
        usage="/upload_to_airtable <курс AED→RUB>",
    ),
]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  ASSEMBLE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

bot_flows = BotFlows(
    flows=[contractor_flow, document_flow],
    admin_commands=admin_commands,
    start_handler=handle_start,
    reply_handler=handle_admin_reply,
)
