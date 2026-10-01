from __future__ import annotations

from typing import Any


def message_text(content: Any) -> str:
    """Normalize LLM message content (str | Gemini blocks | LC parts) to plain text."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
                continue
            if isinstance(item, dict):
                if item.get("text") is not None:
                    parts.append(str(item["text"]))
                elif item.get("content") is not None:
                    parts.append(message_text(item["content"]))
                continue
            text = getattr(item, "text", None)
            if text is not None:
                parts.append(str(text))
                continue
            nested = getattr(item, "content", None)
            if nested is not None:
                parts.append(message_text(nested))
                continue
        return "\n".join(p for p in parts if p).strip()
    return str(content).strip()
