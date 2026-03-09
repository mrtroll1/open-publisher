"""Postgres repository aggregate — all repos via single DbGateway class."""

from backend.infrastructure.repositories.postgres.environment_repo import EnvironmentRepo
from backend.infrastructure.repositories.postgres.knowledge_repo import KnowledgeRepo
from backend.infrastructure.repositories.postgres.message_repo import (
    MessageRepo,
    normalize_email_subject,  # noqa: F401
)
from backend.infrastructure.repositories.postgres.permission_repo import PermissionRepo
from backend.infrastructure.repositories.postgres.run_log_repo import RunLogRepo
from backend.infrastructure.repositories.postgres.user_repo import UserRepo


class DbGateway(KnowledgeRepo, EnvironmentRepo, UserRepo, MessageRepo, RunLogRepo, PermissionRepo):
    pass
