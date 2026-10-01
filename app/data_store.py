from __future__ import annotations

import json
import re
import uuid
from datetime import date, datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.config import DATA_DIR, get_settings

NON_RETURNABLE = {"innerwear", "jewellery", "jewelry", "beauty", "fragrance", "face masks", "gift cards", "socks"}


class DataStore:
    """In-memory store loaded from orders.json (assignment fixtures + extra demo catalog)."""

    def __init__(self, orders_path: Path | None = None, policy_path: Path | None = None) -> None:
        orders_path = orders_path or (DATA_DIR / "orders.json")
        policy_path = policy_path or (DATA_DIR / "trendly_policy.md")
        raw = json.loads(orders_path.read_text(encoding="utf-8"))
        self.customers: dict[str, dict[str, Any]] = {c["customer_id"]: c for c in raw["customers"]}
        self.orders: dict[str, dict[str, Any]] = {o["order_id"]: o for o in raw["orders"]}
        self.policy_text = policy_path.read_text(encoding="utf-8")
        self.returns: dict[str, dict[str, Any]] = {}
        self.exchanges: dict[str, dict[str, Any]] = {}
        self.delay_credits: dict[str, dict[str, Any]] = {}
        self.escalations: dict[str, dict[str, Any]] = {}
        # session_id -> verified customer_id
        self.session_customers: dict[str, str] = {}

    def reference_date(self) -> date:
        return date.fromisoformat(get_settings().reference_date)

    def get_customer(self, customer_id: str) -> dict[str, Any] | None:
        return self.customers.get(customer_id)

    def get_order(self, order_id: str) -> dict[str, Any] | None:
        return self.orders.get(order_id.upper())

    def orders_for_customer(self, customer_id: str) -> list[dict[str, Any]]:
        return [o for o in self.orders.values() if o["customer_id"] == customer_id]

    def find_customer_by_contact(self, email: str | None = None, phone: str | None = None) -> dict[str, Any] | None:
        email_n = (email or "").strip().lower()
        phone_n = re.sub(r"\D", "", phone or "")
        for c in self.customers.values():
            if email_n and c["email"].lower() == email_n:
                return c
            if phone_n and re.sub(r"\D", "", c["phone"]) == phone_n:
                return c
        return None

    def verify_order_ownership(self, order_id: str, customer_id: str) -> bool:
        order = self.get_order(order_id)
        return bool(order and order["customer_id"] == customer_id)

    def exchange_count(self, order_id: str, sku: str) -> int:
        return sum(
            1
            for e in self.exchanges.values()
            if e["order_id"] == order_id and e["sku"] == sku and e["status"] != "cancelled"
        )


_store: DataStore | None = None


def get_store() -> DataStore:
    global _store
    if _store is None:
        _store = DataStore()
    return _store


def reset_store() -> DataStore:
    global _store
    _store = DataStore()
    return _store


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    if "T" in value:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    return date.fromisoformat(value)


def days_since_delivery(order: dict[str, Any], today: date | None = None) -> int | None:
    today = today or get_store().reference_date()
    delivered = _parse_date(order.get("delivered_at"))
    if not delivered:
        return None
    return (today - delivered).days


def is_non_returnable_category(category: str) -> bool:
    c = category.lower().strip()
    if c in NON_RETURNABLE:
        return True
    return any(x in c for x in ("innerwear", "jewellery", "jewelry", "beauty", "fragrance", "mask", "sock", "gift card"))


@lru_cache(maxsize=128)
def search_policy_cached(query: str) -> str:
    """Deterministic section retrieval over the policy markdown (cached)."""
    store = get_store()
    text = store.policy_text
    q = query.lower().strip()
    sections = re.split(r"\n(?=## )", text)
    scored: list[tuple[int, str]] = []
    keywords = [w for w in re.findall(r"[a-z0-9₹]+", q) if len(w) > 2]
    for sec in sections:
        low = sec.lower()
        score = sum(1 for k in keywords if k in low)
        # boost exact topic hits
        for boost in (
            "shipping",
            "return",
            "refund",
            "exchange",
            "pickup",
            "damaged",
            "lost",
            "delay",
            "final sale",
            "cod",
            "cash on delivery",
            "assistant must not",
        ):
            if boost in q and boost in low:
                score += 3
        if score > 0:
            scored.append((score, sec.strip()))
    scored.sort(key=lambda x: x[0], reverse=True)
    if not scored:
        return (
            "NO_RELEVANT_SECTION: The policy document does not clearly cover this topic. "
            "You must say you do not know and offer to escalate to a human agent."
        )
    top = [s for _, s in scored[:3]]
    return "\n\n---\n\n".join(top)


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
