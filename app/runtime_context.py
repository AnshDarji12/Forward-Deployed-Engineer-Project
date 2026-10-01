from __future__ import annotations

import contextvars

_session_id: contextvars.ContextVar[str] = contextvars.ContextVar("trendly_session_id", default="")


def set_session_id(session_id: str):
    return _session_id.set(session_id or "")


def reset_session_id(token) -> None:
    _session_id.reset(token)


def get_session_id() -> str:
    return _session_id.get() or ""
