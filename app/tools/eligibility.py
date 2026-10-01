from __future__ import annotations

from typing import Any

from app.data_store import (
    days_since_delivery,
    get_store,
    is_non_returnable_category,
)


def evaluate_eligibility(
    order_id: str,
    sku: str | None,
    action: str,
    *,
    has_shoe_box: bool | None = None,
    reason: str = "change_of_mind",
) -> dict[str, Any]:
    """Deterministic eligibility rules (policy + order). Used by tools and tests."""
    store = get_store()
    order = store.get_order(order_id)
    if not order:
        return {"eligible": False, "action": action, "reasons": [f"Order {order_id} not found."]}

    status = order["status"]
    items = order["items"]
    item = None
    if sku:
        item = next((i for i in items if i["sku"].upper() == sku.upper()), None)
        if not item:
            return {"eligible": False, "action": action, "reasons": [f"SKU {sku} not on order {order_id}."]}
    elif len(items) == 1:
        item = items[0]
        sku = item["sku"]
    else:
        return {
            "eligible": False,
            "action": action,
            "reasons": ["Order has multiple items — specify sku."],
            "items": [{"sku": i["sku"], "name": i["name"], "category": i["category"]} for i in items],
        }

    assert item is not None and sku is not None
    reasons: list[str] = []
    notes: list[str] = []
    action = action.lower().strip()

    if status == "cancelled":
        return {
            "eligible": False,
            "action": action,
            "order_id": order_id,
            "sku": sku,
            "reasons": ["Order is cancelled — no return/exchange can be raised (policy 2.6)."],
            "refund_status": order.get("refund_status"),
        }

    if status == "lost_in_transit":
        return {
            "eligible": False,
            "action": action,
            "order_id": order_id,
            "sku": sku,
            "reasons": [
                "This is a lost-parcel claim, not a return (policy 1.6). Escalate to a human agent."
            ],
            "must_escalate": True,
        }

    if status in {"in_transit", "partially_shipped", "delayed"} and action in {"return", "exchange"}:
        return {
            "eligible": False,
            "action": action,
            "order_id": order_id,
            "sku": sku,
            "reasons": [f"Order status is '{status}' — item not delivered yet, so return/exchange window has not started."],
            "status": status,
        }

    if reason in {"damaged", "defective", "wrong_item"}:
        days = days_since_delivery(order)
        if days is None:
            return {
                "eligible": False,
                "action": action,
                "reasons": ["No delivery date — cannot evaluate 48-hour damage window."],
            }
        if days > 2:
            return {
                "eligible": False,
                "action": action,
                "order_id": order_id,
                "sku": sku,
                "reasons": [
                    f"Damaged/wrong items must be reported within 48 hours of delivery (policy 6.1). "
                    f"Delivered {days} days ago."
                ],
                "must_escalate": True,
            }
        return {
            "eligible": True,
            "action": "replacement_or_full_refund",
            "order_id": order_id,
            "sku": sku,
            "item_name": item["name"],
            "reasons": ["Within 48-hour damaged/wrong-item window (policy 6). Photos required."],
            "requires_photos": True,
            "shipping_fee_refundable": True,
        }

    days = days_since_delivery(order)
    if days is None:
        return {
            "eligible": False,
            "action": action,
            "reasons": ["Item not delivered — return window starts on delivery date (policy 2.1)."],
        }
    if days > 30:
        return {
            "eligible": False,
            "action": action,
            "order_id": order_id,
            "sku": sku,
            "days_since_delivery": days,
            "reasons": [f"Outside 30-day return window (delivered {days} days ago). Policy 2.1 — not eligible under any circumstance."],
        }

    if is_non_returnable_category(item["category"]):
        return {
            "eligible": False,
            "action": action,
            "order_id": order_id,
            "sku": sku,
            "category": item["category"],
            "reasons": [
                f"Category '{item['category']}' is non-returnable/non-exchangeable for hygiene/safety (policy 2.3)."
            ],
        }

    final_sale = bool(item.get("final_sale"))
    if final_sale and action == "return":
        return {
            "eligible": False,
            "action": "return",
            "order_id": order_id,
            "sku": sku,
            "final_sale": True,
            "reasons": ["Final sale items: size exchange only — no refunds or store credit (policy 2.4)."],
            "suggest_action": "exchange",
        }

    if action == "exchange":
        if store.exchange_count(order_id, sku) >= 1:
            return {
                "eligible": False,
                "action": "exchange",
                "order_id": order_id,
                "sku": sku,
                "reasons": ["One exchange per item already used. Second exchange needs human approval (policy 4.4)."],
                "must_escalate": True,
            }
        notes.append("Size exchange only — not colour/style (policy 4.1).")
        if final_sale:
            notes.append("Final sale: exchange only, no refund if size unavailable converts carefully per policy.")
        return {
            "eligible": True,
            "action": "exchange",
            "order_id": order_id,
            "sku": sku,
            "item_name": item["name"],
            "current_size": item.get("size"),
            "days_since_delivery": days,
            "final_sale": final_sale,
            "reasons": ["Within window, category allowed, exchange available."],
            "notes": notes,
        }

    # return
    footwear_fee = 0
    if item["category"].lower() == "footwear":
        if has_shoe_box is False:
            footwear_fee = 300
            notes.append("Footwear returned without original box: ₹300 deduction (policy 2.5).")
        elif has_shoe_box is None:
            notes.append("Confirm original shoe box is included (policy 2.5).")

    shipping_refund = reason in {"wrong_item", "damaged", "defective", "trendly_error"}
    return {
        "eligible": True,
        "action": "return",
        "order_id": order_id,
        "sku": sku,
        "item_name": item["name"],
        "days_since_delivery": days,
        "payment_method": order.get("payment_method"),
        "footwear_deduction_inr": footwear_fee,
        "original_shipping_refundable": shipping_refund,
        "reasons": ["Within 30-day window, returnable category, not blocked."],
        "notes": notes
        + [
            "Item must be unworn/unwashed with tags (policy 2.2).",
            "COD refunds require bank details collected by a human via secure link (policy 3.3) — never collect in chat.",
        ],
    }
