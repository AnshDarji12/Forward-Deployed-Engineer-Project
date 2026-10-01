from __future__ import annotations

import uuid
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from app.agent import run_turn
from app.agent.text import message_text
from app.data_store import get_store


class SessionManager:
    def __init__(self) -> None:
        self._history: dict[str, list[BaseMessage]] = {}

    def create(self) -> str:
        sid = f"S-{uuid.uuid4().hex[:10].upper()}"
        self._history[sid] = []
        return sid

    def reset(self, session_id: str) -> None:
        self._history[session_id] = []
        store = get_store()
        store.session_customers.pop(session_id, None)

    def chat(self, session_id: str, message: str) -> dict[str, Any]:
        if session_id not in self._history:
            self._history[session_id] = []
        history = self._history[session_id]
        result = run_turn(message, session_id, history=history)
        # Persist only human/ai conversational turns (drop tool noise for context size)
        compact: list[BaseMessage] = []
        for m in result["messages"]:
            if isinstance(m, HumanMessage):
                compact.append(HumanMessage(content=message_text(m.content)))
            elif isinstance(m, AIMessage) and message_text(m.content) and not m.tool_calls:
                compact.append(AIMessage(content=message_text(m.content)))
        # Keep last N exchanges
        self._history[session_id] = compact[-20:]
        return {
            "session_id": session_id,
            "reply": result["reply"],
            "tool_trace": result["tool_trace"],
            "flow_path": result.get("flow_path") or [],
            "verified_customer_id": result.get("verified_customer_id"),
            "blocked": result.get("blocked", False),
        }


sessions = SessionManager()
