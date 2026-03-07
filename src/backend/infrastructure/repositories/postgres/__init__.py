"""Postgres repository aggregate — all repos via single DbGateway class."""

from backend.infrastructure.repositories.postgres.environment_repo import EnvironmentRepo  # noqa: F401
from backend.infrastructure.repositories.postgres.knowledge_repo import KnowledgeRepo  # noqa: F401
from backend.infrastructure.repositories.postgres.message_repo import (
    MessageRepo,  # noqa: F401
    normalize_email_subject,  # noqa: F401
)
from backend.infrastructure.repositories.postgres.run_log_repo import RunLogRepo  # noqa: F401
from backend.infrastructure.repositories.postgres.user_repo import UserRepo  # noqa: F401


class DbGateway(KnowledgeRepo, EnvironmentRepo, UserRepo, MessageRepo, RunLogRepo):
    pass
