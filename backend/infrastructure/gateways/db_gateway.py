"""Database gateway — backward-compatible shim.

All logic has moved to backend.infrastructure.repositories.postgres.*
This module re-exports DbGateway (via multiple inheritance) so existing
imports continue to work unchanged.
"""

from backend.infrastructure.repositories.postgres.email_repo import (  # noqa: F401
    EmailRepo,
    _normalize_subject,
)
from backend.infrastructure.repositories.postgres.knowledge_repo import KnowledgeRepo
from backend.infrastructure.repositories.postgres.conversation_repo import ConversationRepo
from backend.infrastructure.repositories.postgres.classification_repo import ClassificationRepo
from backend.infrastructure.repositories.postgres.payment_repo import PaymentRepo
from backend.infrastructure.repositories.postgres.code_task_repo import CodeTaskRepo


class DbGateway(EmailRepo, KnowledgeRepo, ConversationRepo, ClassificationRepo, PaymentRepo, CodeTaskRepo):
    pass
