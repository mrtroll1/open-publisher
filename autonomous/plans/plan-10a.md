# Plan 10a: Base Abstractions (Brain Skeleton)

## Context

This plan creates `backend/brain/` with all base classes and orchestration components. It introduces the unifying abstractions that every subsequent phase builds on: `BaseGenAI`, `BaseController`, `BasePreparer`, `Route`, `AuthContext`, `Brain`, `Authorizer`, and `Router`.

No existing code is modified. Everything is new. After this phase, the brain package is importable and its classes can be instantiated, but no controllers or dynamic implementations exist yet.

## Files to Create

### 1. `backend/brain/__init__.py` — Brain orchestrator

Top-level orchestrator. Receives raw input + environment_id + user_id, delegates to Authorizer, Router, and the chosen Controller.

```python
class Brain:
    def __init__(self, authorizer: Authorizer, router: Router): ...

    def process(self, input: str, environment_id: str, user_id: str) -> Any:
        """NL input flow: authorize -> route -> controller.execute()"""
        auth = self.authorizer.authorize(environment_id, user_id)
        route = self.router.route(input, auth.routes)
        return route.controller.execute(input, auth.env, auth.user)

    def process_command(self, command: str, args: str, environment_id: str, user_id: str) -> Any:
        """Slash command flow: authorize -> direct controller dispatch (skip router)"""
        auth = self.authorizer.authorize(environment_id, user_id)
        route = ROUTES[command]
        return route.controller.execute(args, auth.env, auth.user)
```

### 2. `backend/brain/base_genai.py` — Template method for all LLM operations

Abstract base for anything that calls an LLM. Router, dynamic preparers, dynamic use-cases all extend this.

```python
class RecursionLimitError(Exception): ...

class BaseGenAI:
    MAX_DEPTH = 5

    def __init__(self, gemini: GeminiGateway):
        self._gemini = gemini

    def run(self, input: str, context: dict, *, _depth: int = 0) -> dict:
        if _depth >= self.MAX_DEPTH:
            raise RecursionLimitError(...)
        template = self._pick_template(input, context)
        built_context = self._build_context(input, context)
        prompt = render(template, built_context)
        raw = self._call_ai(prompt)
        return self._parse_response(raw)

    # Abstract methods for children:
    def _pick_template(self, input: str, context: dict) -> str: ...
    def _build_context(self, input: str, context: dict) -> dict: ...
    def _call_ai(self, prompt: str) -> str:
        """Default: call self._gemini. Override for non-standard calls."""
        return self._gemini.call(prompt, self._model)
    def _parse_response(self, raw: dict) -> dict: ...
```

Dependencies: `common.prompt_loader.load_template`, `backend.infrastructure.gateways.gemini_gateway.GeminiGateway`

### 3. `backend/brain/base_controller.py` — Template method for all controllers

Every command has a controller with a preparer + use_case.

```python
class BasePreparer:
    def prepare(self, input: str, env: dict, user: dict) -> Any:
        raise NotImplementedError

class PassThroughPreparer(BasePreparer):
    """Returns input unchanged."""
    def prepare(self, input: str, env: dict, user: dict) -> str:
        return input

class BaseUseCase:
    def execute(self, prepared: Any, env: dict, user: dict) -> Any:
        raise NotImplementedError

class BaseController:
    def __init__(self, preparer: BasePreparer, use_case: BaseUseCase):
        self.preparer = preparer
        self.use_case = use_case

    def execute(self, input: str, env: dict, user: dict) -> Any:
        prepared = self.preparer.prepare(input, env, user)
        return self.use_case.execute(prepared, env, user)
```

### 4. `backend/brain/routes.py` — Route dataclass and registry

Central registry of all available routes. Each route maps a command name to a controller + metadata.

```python
@dataclass
class Route:
    name: str
    controller: BaseController
    description: str             # Used by Router LLM prompt
    examples: list[str] = field(default_factory=list)
    permissions: set[str] = field(default_factory=lambda: {"admin"})
    slash_command: str | None = None

ROUTES: dict[str, Route] = {}

def register_route(route: Route) -> None:
    ROUTES[route.name] = route
```

### 5. `backend/brain/authorizer.py` — Resolves environment, user, available routes

Solid singleton. Looks up environment (by name or chat_id), resolves user/entity, filters routes by permissions.

```python
@dataclass
class AuthContext:
    env: dict          # environment record (system_context, allowed_domains, etc.)
    user: dict         # entity record (id, name, summary, etc.)
    routes: list[Route]

class Authorizer:
    def __init__(self, db: DbGateway):
        self._db = db

    def authorize(self, environment_id: str, user_id: str) -> AuthContext:
        env = self._resolve_env(environment_id)
        user = self._resolve_user(user_id)
        routes = self._filter_routes(env, user)
        return AuthContext(env=env, user=user, routes=routes)

    def _resolve_env(self, environment_id: str) -> dict:
        """Resolve by name or chat_id. Returns empty dict if unbound."""

    def _resolve_user(self, user_id: str) -> dict:
        """Lookup entity by telegram_user_id. Returns empty dict if unknown."""

    def _filter_routes(self, env: dict, user: dict) -> list[Route]:
        """Return routes whose permissions match the env/user context."""
```

Current logic lives in: `telegram_bot/handler_utils.py` → `resolve_environment()` (line ~120) and `resolve_entity_context()` (line ~130). Move and adapt.

Dependencies: `backend.infrastructure.repositories.postgres.DbGateway`, `backend.brain.routes.ROUTES`

### 6. `backend/brain/router.py` — LLM-based command classifier (extends BaseGenAI)

Takes NL input + available routes, calls LLM to pick a route. Replaces `command_classifier.py`.

```python
class Router(BaseGenAI):
    def __init__(self, gemini: GeminiGateway, db: DbGateway | None = None):
        super().__init__(gemini)
        self._model = "gemini-2.5-flash"
        self._db = db

    def route(self, input: str, routes: list[Route]) -> Route:
        context = {"routes": routes}
        result = self.run(input, context)
        route_name = result.get("command", "")
        # Find matching route; fall back to conversation
        ...

    def _pick_template(self, input, context) -> str:
        return "chat/classify-command.md"

    def _build_context(self, input, context) -> dict:
        routes = context["routes"]
        commands_desc = "\n".join(f"- **{r.name}** -- {r.description}" for r in routes)
        return {"COMMANDS": commands_desc, "TEXT": input, "CONTEXT": ""}

    def _call_ai(self, prompt) -> dict:
        return self._gemini.call(prompt, self._model)

    def _parse_response(self, raw) -> dict:
        return raw
```

Source: `backend/domain/services/command_classifier.py` `classify()` method (lines 35-54) + `compose_request.classify_command()` (lines 129-136).

### 7. `backend/brain/dynamic/__init__.py` — Empty, placeholder for Phase 10b

## Verification Checklist

- [ ] `from backend.brain import Brain` imports without error
- [ ] `from backend.brain.base_genai import BaseGenAI, RecursionLimitError` imports
- [ ] `from backend.brain.base_controller import BaseController, BasePreparer, PassThroughPreparer, BaseUseCase` imports
- [ ] `from backend.brain.routes import Route, ROUTES, register_route` imports
- [ ] `from backend.brain.authorizer import Authorizer, AuthContext` imports
- [ ] `from backend.brain.router import Router` imports
- [ ] `Router` is a subclass of `BaseGenAI`
- [ ] `Brain` can be instantiated with `Authorizer` and `Router`
- [ ] All existing tests still pass (no existing code was changed)
- [ ] `backend/brain/dynamic/` directory exists with `__init__.py`
