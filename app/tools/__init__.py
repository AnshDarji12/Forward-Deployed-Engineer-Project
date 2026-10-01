from __future__ import annotations

import json
from typing import Any

from langchain_core.tools import tool

from app.data_store import (
    days_since_delivery,
    get_store,
    new_id,
    now_iso,
    search_policy_cached,
)
from app.runtime_context import get_session_id
from app.tools.eligibility import evaluate_eligibility


def _json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)


def _sid() -> str:
    return get_session_id()


@tool
def verify_customer(
    email: str = "",
    phone: str = "",
    order_id: str = "",
) -> str:
    """Verify the customer identity using email and/or phone. Optionally confirm they own an order_id.
    Call this BEFORE revealing any order details. Prefer email if available.
    """
    store = get_store()
    session_id = _sid()
    customer = store.find_customer_by_contact(email=email or None, phone=phone or None)
    if not customer:
        return _json(
            {
                "verified": False,
                "error": "No customer matched that email/phone. Ask the user to recheck contact details.",
            }
        )

    if order_id:
        order = store.get_order(order_id)
        if not order:
            return _json({"verified": False, "error": f"Order {order_id} not found."})
        if order["customer_id"] != customer["customer_id"]:
            return _json(
                {
                    "verified": False,
                    "error": "That order does not belong to this customer. Do NOT reveal any order details.",
                    "data_leakage_blocked": True,
                }
            )

    if session_id:
        store.session_customers[session_id] = customer["customer_id"]

    return _json(
        {
            "verified": True,
            "customer_id": customer["customer_id"],
            "name": customer["name"],
            "email": customer["email"],
            "order_id_checked": order_id or None,
            "message": "Identity verified. You may now look up this customer's orders.",
        }
    )


@tool
def get_order_status(order_id: str) -> str:
    """Look up a single order and return status, tracking, items, and edge-case flags.
    Requires the session customer to be verified and to own the order.
    """
    store = get_store()
    session_id = _sid()
    order = store.get_order(order_id)
    if not order:
        return _json({"error": f"Order {order_id} not found."})

    verified_cid = store.session_customers.get(session_id) if session_id else None
    if not verified_cid:
        return _json(
            {
                "error": "Customer not verified for this session. Call verify_customer first.",
                "requires_verification": True,
            }
        )
    if order["customer_id"] != verified_cid:
        return _json(
            {
                "error": "Order does not belong to the verified customer. Access denied.",
                "data_leakage_blocked": True,
            }
        )

    customer = store.get_customer(order["customer_id"])
    days = days_since_delivery(order)
    expected = order.get("expected_delivery")

    payload = {
        "order_id": order["order_id"],
        "status": order["status"],
        "placed_at": order.get("placed_at"),
        "delivered_at": order.get("delivered_at"),
        "expected_delivery": expected,
        "days_since_delivery": days,
        "carrier": order.get("carrier"),
        "tracking_number": order.get("tracking_number"),
        "payment_method": order.get("payment_method"),
        "shipping_city": order.get("shipping_city"),
        "total": order.get("total"),
        "items": order.get("items"),
        "customer_name": customer["name"] if customer else None,
        "cancelled_at": order.get("cancelled_at"),
        "refund_status": order.get("refund_status"),
        "flags": {
            "lost_parcel": order["status"] == "lost_in_transit",
            "must_escalate_lost_parcel": order["status"] == "lost_in_transit",
            "delayed": order["status"] == "delayed",
            "delay_credit_eligible_inr": 250 if order["status"] == "delayed" else 0,
            "partially_shipped": order["status"] == "partially_shipped",
            "cancelled": order["status"] == "cancelled",
        },
        "plain_language_hint": _status_hint(order),
    }
    return _json(payload)


def _status_hint(order: dict) -> str:
    s = order["status"]
    if s == "in_transit":
        return f"On the way via {order.get('carrier')}. Expected by {order.get('expected_delivery')}."
    if s == "delivered":
        return f"Delivered on {order.get('delivered_at')}."
    if s == "partially_shipped":
        shipped = [i["name"] for i in order["items"] if i.get("shipped")]
        pending = [i for i in order["items"] if not i.get("shipped")]
        eta = pending[0].get("backorder_eta") if pending else None
        return (
            f"Partial shipment: shipped {shipped}. "
            f"Backordered items ETA {eta}. No second shipping fee (policy 1.4)."
        )
    if s == "delayed":
        return (
            f"Delayed past expected delivery {order.get('expected_delivery')}. "
            "Eligible for ₹250 store credit on request (policy 1.5) — acknowledge delay first."
        )
    if s == "lost_in_transit":
        return "Carrier marked lost. Escalate as lost-parcel claim (policy 1.6) — do not process as return."
    if s == "cancelled":
        return f"Cancelled at {order.get('cancelled_at')}. Refund status: {order.get('refund_status')}."
    return f"Status: {s}"


@tool
def list_customer_orders() -> str:
    """List all orders for the verified customer in this session."""
    store = get_store()
    session_id = _sid()
    cid = store.session_customers.get(session_id) if session_id else None
    if not cid:
        return _json({"error": "Customer not verified. Call verify_customer first.", "requires_verification": True})
    orders = store.orders_for_customer(cid)
    summary = [
        {
            "order_id": o["order_id"],
            "status": o["status"],
            "total": o["total"],
            "placed_at": o.get("placed_at"),
            "item_names": [i["name"] for i in o["items"]],
        }
        for o in orders
    ]
    return _json({"customer_id": cid, "orders": summary})


@tool
def search_policy(query: str) -> str:
    """Search Trendly shipping & returns policy. ONLY source of truth for policy answers.
    Use for shipping, returns, refunds, exchanges, pickup, damaged items, lost parcels, delays.
    If result says NO_RELEVANT_SECTION, do not invent policy — offer human escalation.
    """
    return search_policy_cached(query)


@tool
def check_return_eligibility(
    order_id: str,
    action: str,
    sku: str = "",
    reason: str = "change_of_mind",
    has_shoe_box: bool | None = None,
) -> str:
    """Deterministically check return or exchange eligibility by combining order data with policy rules.
    action: 'return' or 'exchange'. reason: change_of_mind | damaged | defective | wrong_item.
    """
    store = get_store()
    session_id = _sid()
    order = store.get_order(order_id)
    if not order:
        return _json({"eligible": False, "error": f"Order {order_id} not found."})

    cid = store.session_customers.get(session_id) if session_id else None
    if not cid:
        return _json({"eligible": False, "error": "Customer not verified.", "requires_verification": True})
    if order["customer_id"] != cid:
        return _json({"eligible": False, "error": "Order ownership check failed.", "data_leakage_blocked": True})

    result = evaluate_eligibility(
        order_id,
        sku or None,
        action,
        has_shoe_box=has_shoe_box,
        reason=reason,
    )
    return _json(result)


@tool
def initiate_return_or_exchange(
    order_id: str,
    action: str,
    sku: str,
    reason: str = "change_of_mind",
    requested_size: str = "",
    has_shoe_box: bool | None = None,
) -> str:
    """Create a return or size-exchange request ONLY if eligibility re-check passes.
    For exchanges, provide requested_size. Never invent discounts.
    """
    store = get_store()
    session_id = _sid()
    order = store.get_order(order_id)
    if not order:
        return _json({"ok": False, "error": f"Order {order_id} not found."})
    cid = store.session_customers.get(session_id) if session_id else None
    if not cid or order["customer_id"] != cid:
        return _json({"ok": False, "error": "Verification/ownership required."})

    check = evaluate_eligibility(
        order_id, sku, action, has_shoe_box=has_shoe_box, reason=reason
    )
    if not check.get("eligible"):
        return _json({"ok": False, "created": False, "eligibility": check})

    action = action.lower().strip()
    if action == "exchange":
        if not requested_size:
            return _json({"ok": False, "error": "requested_size is required for exchanges."})
        rid = new_id("EX")
        record = {
            "exchange_id": rid,
            "order_id": order_id,
            "sku": sku,
            "from_size": check.get("current_size"),
            "to_size": requested_size,
            "status": "scheduled",
            "created_at": now_iso(),
            "notes": check.get("notes", []),
        }
        store.exchanges[rid] = record
        return _json({"ok": True, "created": True, "type": "exchange", "record": record})

    rid = new_id("RT")
    record = {
        "return_id": rid,
        "order_id": order_id,
        "sku": sku,
        "reason": reason,
        "status": "pickup_to_be_scheduled",
        "footwear_deduction_inr": check.get("footwear_deduction_inr", 0),
        "payment_method": order.get("payment_method"),
        "created_at": now_iso(),
        "notes": check.get("notes", []),
    }
    store.returns[rid] = record
    cod_note = None
    if order.get("payment_method") == "cash_on_delivery":
        cod_note = (
            "COD refund requires bank details via secure link from a human agent (policy 3.3). "
            "Escalate for bank-detail collection — do not collect in chat."
        )
    return _json({"ok": True, "created": True, "type": "return", "record": record, "cod_followup": cod_note})


@tool
def issue_delay_credit(order_id: str) -> str:
    """Issue the policy-defined ₹250 store credit for a delayed order (policy 1.5). Only when order status is delayed."""
    store = get_store()
    session_id = _sid()
    order = store.get_order(order_id)
    if not order:
        return _json({"ok": False, "error": f"Order {order_id} not found."})
    cid = store.session_customers.get(session_id) if session_id else None
    if not cid or order["customer_id"] != cid:
        return _json({"ok": False, "error": "Verification/ownership required."})
    if order["status"] != "delayed":
        return _json(
            {
                "ok": False,
                "error": f"Order status is '{order['status']}', not delayed. Credit not issued.",
            }
        )
    if order_id in store.delay_credits:
        return _json({"ok": True, "already_issued": True, "record": store.delay_credits[order_id]})

    record = {
        "credit_id": new_id("CR"),
        "order_id": order_id,
        "amount_inr": 250,
        "type": "store_credit",
        "created_at": now_iso(),
        "policy": "1.5",
    }
    store.delay_credits[order_id] = record
    return _json({"ok": True, "issued": True, "record": record})


@tool
def escalate_to_human(
    summary: str,
    reason: str,
    order_id: str = "",
    priority: str = "normal",
) -> str:
    """Escalate to a human support agent with a structured summary a person can act on.
    Use for: lost parcels, policy gaps, second exchanges, COD bank details, abuse, low confidence, customer request.
    reason examples: lost_parcel | policy_gap | second_exchange | cod_bank_details | customer_request | safety | other
    """
    store = get_store()
    session_id = _sid()
    cid = store.session_customers.get(session_id) if session_id else None
    customer = store.get_customer(cid) if cid else None
    ticket_id = new_id("ESC")
    ticket = {
        "ticket_id": ticket_id,
        "created_at": now_iso(),
        "priority": priority,
        "reason": reason,
        "summary": summary,
        "order_id": order_id or None,
        "customer_id": cid,
        "customer_name": customer["name"] if customer else None,
        "customer_email": customer["email"] if customer else None,
        "support_hours": "9:00 AM – 9:00 PM IST, seven days a week",
        "status": "queued_for_human",
    }
    store.escalations[ticket_id] = ticket
    return _json({"ok": True, "escalated": True, "ticket": ticket})


ALL_TOOLS = [
    verify_customer,
    get_order_status,
    list_customer_orders,
    search_policy,
    check_return_eligibility,
    initiate_return_or_exchange,
    issue_delay_credit,
    escalate_to_human,
]
