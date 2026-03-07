"""Authorizer — does the right user get the right tools?"""

from conftest import make_tool

from backend.brain.authorizer import Authorizer
from backend.brain.tool import register_tool


def _setup(fake_db, env=None, user=None, tools=None):
    if env:
        fake_db.environments[env["id"]] = env
    if user:
        fake_db.users[user["telegram_id"]] = user
    for t in (tools or []):
        register_tool(t)
    return Authorizer(fake_db)


# ── Permission filtering ────────────────────────────────────────────


def test_admin_gets_admin_tools(fake_db):
    admin_only = make_tool("secret", permissions={"*": {"admin"}})
    auth = _setup(fake_db,
                  env={"id": "e1", "name": "main"},
                  user={"id": "u1", "role": "admin", "telegram_id": 100},
                  tools=[admin_only])

    result = auth.authorize("e1", "100")

    assert result.role == "admin"
    assert admin_only in result.tools


def test_user_excluded_from_admin_tools(fake_db):
    admin_only = make_tool("secret", permissions={"*": {"admin"}})
    _setup(fake_db,
           env={"id": "e1", "name": "main"},
           user={"id": "u1", "role": "user", "telegram_id": 200},
           tools=[admin_only])
    auth = Authorizer(fake_db)

    result = auth.authorize("e1", "200")

    assert admin_only not in result.tools


def test_wildcard_permission_grants_everyone(fake_db):
    public = make_tool("public", permissions={"*": {"*"}})
    auth = _setup(fake_db,
                  env={"id": "e1", "name": "main"},
                  user={"id": "u1", "role": "user", "telegram_id": 300},
                  tools=[public])

    result = auth.authorize("e1", "300")

    assert public in result.tools


def test_env_specific_override(fake_db):
    """A tool denied by default but allowed in a specific environment."""
    tool = make_tool("special", permissions={"*": set(), "vip": {"user"}})
    auth = _setup(fake_db,
                  env={"id": "e1", "name": "vip"},
                  user={"id": "u1", "role": "user", "telegram_id": 400},
                  tools=[tool])

    result = auth.authorize("e1", "400")

    assert tool in result.tools


def test_env_specific_override_denies_other_envs(fake_db):
    tool = make_tool("special", permissions={"*": set(), "vip": {"user"}})
    auth = _setup(fake_db,
                  env={"id": "e1", "name": "general"},
                  user={"id": "u1", "role": "user", "telegram_id": 500},
                  tools=[tool])

    result = auth.authorize("e1", "500")

    assert tool not in result.tools


# ── Fallback resolution ─────────────────────────────────────────────


def test_chat_id_fallback(fake_db):
    """When env_id looks like a number, try chat_id lookup."""
    fake_db.environments_by_chat[12345] = {"id": "e1", "name": "main"}
    auth = _setup(fake_db, tools=[])

    result = auth.authorize("12345", "")

    assert result.env_name == "main"


def test_unknown_env_returns_empty(fake_db):
    auth = _setup(fake_db, tools=[])

    result = auth.authorize("nonexistent", "")

    assert result.env_name == ""
    assert result.tools == []


def test_empty_user_id(fake_db):
    auth = _setup(fake_db, env={"id": "e1", "name": "main"}, tools=[])

    result = auth.authorize("e1", "")

    assert result.role == "user"  # default
    assert result.ctx.user == {}
