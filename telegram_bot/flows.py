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
    GroupChatConfig,
    InputType,
    Transition,
)
from common.config import EDITORIAL_CHAT_ID
from telegram_bot import replies
from telegram_bot.flow_callbacks import (
    handle_start,
    handle_menu,
    handle_sign_doc,
    handle_update_payment_data,
    handle_manage_redirects,
    # Contractor flow
    handle_contractor_text,
    handle_verification_code,
    handle_type_selection,
    handle_data_input,
    handle_amount_input,
    handle_update_data,
    handle_editor_source_name,
    # Document upload
    handle_document,
    # Admin
    handle_admin_reply,
    cmd_articles,
    cmd_generate,
    cmd_health,
    cmd_lookup,
    cmd_tech_support,
    cmd_code,
    cmd_budget,
    cmd_generate_invoices,
    cmd_send_global_invoices,
    cmd_send_legium_links,
    cmd_orphan_contractors,
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
        FlowState(
            name="waiting_update_data",
            handler=handle_update_data,
            transitions={
                "done": Transition(to="end"),
            },
        ),
        FlowState(
            name="waiting_editor_source_name",
            handler=handle_editor_source_name,
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
        command="send_legium_links",
        description="Отправить ссылки на Легиум контрагентам в Telegram",
        handler=cmd_send_legium_links,
        usage="/send_legium_links",
    ),
    AdminCommand(
        command="orphan_contractors",
        description="Показать несовпадения между бюджетом и контрагентами",
        handler=cmd_orphan_contractors,
        usage="/orphan_contractors",
    ),
    AdminCommand(
        command="articles",
        description="Статьи контрагента за месяц",
        handler=cmd_articles,
        usage="/articles <имя> [YYYY-MM]",
    ),
    AdminCommand(
        command="lookup",
        description="Информация о контрагенте",
        handler=cmd_lookup,
        usage="/lookup <имя>",
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
    AdminCommand(
        command="health",
        description="Проверка доступности сайтов и подов",
        handler=cmd_health,
        usage="/health",
    ),
    AdminCommand(
        command="tech_support",
        description="Задать вопрос по техподдержке",
        handler=cmd_tech_support,
        usage="/tech_support [-v] <вопрос>",
    ),
    AdminCommand(
        command="code",
        description="Запустить Claude Code",
        handler=cmd_code,
        usage="/code [-v] <запрос>",
    ),
]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  GROUPCHAT CONFIGS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

group_configs = [
    gc for gc in [
        GroupChatConfig(
            chat_id=EDITORIAL_CHAT_ID,
            allowed_commands=["health", "tech_support", "code", "articles", "lookup"],
        ) if EDITORIAL_CHAT_ID else None,
    ] if gc is not None
]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  ASSEMBLE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

bot_flows = BotFlows(
    flows=[contractor_flow, document_flow],
    admin_commands=admin_commands,
    start_handler=handle_start,
    menu_handler=handle_menu,
    reply_handler=handle_admin_reply,
    command_handlers={
        "sign_doc": handle_sign_doc,
        "update_payment_data": handle_update_payment_data,
        "manage_redirects": handle_manage_redirects,
    },
    group_configs=group_configs,
)
