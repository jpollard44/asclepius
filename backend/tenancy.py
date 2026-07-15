"""Request-scoped tenancy: which user's database the current work targets.

Asclepius runs in two modes:

* **Local mode** (the default): one person, one SQLite file, no accounts —
  exactly the original app. No user is ever set here and everything falls
  through to ``store.DB_PATH``.
* **Multi-tenant mode** (``ASCLEPIUS_MULTI_TENANT=1``): the public service
  behind the iOS app. Every authenticated request carries a user, and each
  user's health data lives in **their own SQLite database** under
  ``data/users/<id>/health.db``. Hard per-user file isolation is the point:
  a query can't leak across tenants because the other tenants aren't even in
  the file being queried.

The mechanism is a ``contextvars.ContextVar`` set by the auth dependency for
the duration of a request (Starlette copies the context into the threadpool
that runs sync endpoints, and APScheduler jobs set it explicitly per user).
``store.connect``/``store.init_db`` resolve it whenever no explicit
``db_path`` is passed, which is why the rest of the codebase needed no
changes to become multi-tenant.
"""
from __future__ import annotations

import contextvars
import shutil
from pathlib import Path

from . import config

_current_user: contextvars.ContextVar[dict | None] = contextvars.ContextVar(
    "asclepius_current_user", default=None)


def users_dir() -> Path:
    return Path(config.DATA_DIR) / "users"


def user_db_path(user_id: int, create: bool = True) -> Path:
    d = users_dir() / str(int(user_id))
    if create:
        d.mkdir(parents=True, exist_ok=True)
    return d / "health.db"


def set_current_user(user: dict | None) -> contextvars.Token:
    """Bind a user (an ``auth`` user row as a dict) to the current context.

    Returns the token to hand back to :func:`reset_current_user`.
    """
    return _current_user.set(user)


def reset_current_user(token: contextvars.Token) -> None:
    _current_user.reset(token)


def current_user() -> dict | None:
    return _current_user.get()


def current_user_id() -> int | None:
    user = _current_user.get()
    return int(user["id"]) if user else None


def current_db_path() -> Path | None:
    """The bound user's DB, or None so callers fall back to the local-mode DB."""
    user = _current_user.get()
    if user is None:
        return None
    return user_db_path(int(user["id"]))


def delete_user_data(user_id: int) -> bool:
    """Remove a user's entire data directory (account deletion). True if it existed."""
    d = users_dir() / str(int(user_id))
    if not d.exists():
        return False
    shutil.rmtree(d)
    return True
