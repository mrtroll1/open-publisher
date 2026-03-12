"""Tool — unified abstraction for all callable operations.

A Tool is both a /command handler and a Gemini function-calling target.
Slash commands and Gemini tool calls both invoke Tool.execute().
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TypedDict


class EnvContext(TypedDict, total=False):
    """Environment configuration from the DB."""
    name: str
    system_context: str


class UserContext(TypedDict, total=False):
    """User record from the DB."""
    id: str
    role: str
    name: str
    telegram_id: int


@dataclass
class ToolContext:
    """Execution context passed to every tool."""
    env: EnvContext
    user: UserContext
    progress: object | None = None  # ProgressEmitter, when streaming


@dataclass
class Tool:
    """A callable operation, usable both as a /command and as a Gemini tool."""
    name: str
    description: str
    parameters: dict  # JSON Schema for arguments
    fn: Callable[[dict, ToolContext], dict]
    permissions: dict[str, set[str]] = field(default_factory=lambda: {"*": {"admin"}})
    slash_command: str | None = None
    examples: list[str] = field(default_factory=list)
    nl_routable: bool = True
    conversational: bool = False

    def execute(self, args: dict, ctx: ToolContext) -> dict:
        return self.fn(args, ctx)


TOOLS: dict[str, Tool] = {}


def register_tool(tool: Tool) -> None:
    TOOLS[tool.name] = tool
