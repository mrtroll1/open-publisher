"""Postgres repository aggregate — all repos via single DbGateway class."""

from backend.infrastructure.repositories.postgres.email_repo import (  # noqa: F401
    EmailRepo,
    _normalize_subject,
)
from backend.infrastructure.repositories.postgres.knowledge_repo import KnowledgeRepo  # noqa: F401
from backend.infrastructure.repositories.postgres.conversation_repo import ConversationRepo  # noqa: F401
from backend.infrastructure.repositories.postgres.classification_repo import ClassificationRepo  # noqa: F401
from backend.infrastructure.repositories.postgres.payment_repo import PaymentRepo  # noqa: F401
from backend.infrastructure.repositories.postgres.code_task_repo import CodeTaskRepo  # noqa: F401


class DbGateway(EmailRepo, KnowledgeRepo, ConversationRepo, ClassificationRepo, PaymentRepo, CodeTaskRepo):
    pass
