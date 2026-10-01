from __future__ import annotations

import json

from app.data_store import reset_store
from app.runtime_context import reset_session_id, set_session_id
from app.tools import escalate_to_human, get_order_status, verify_customer
from app.tools.eligibility import evaluate_eligibility


def setup_function():
    reset_store()


def test_verify_and_block_cross_customer():
    token = set_session_id("S-TEST")
    try:
        out = json.loads(
            verify_customer.invoke(
                {
                    "email": "marcus.bell@example.com",
                    "order_id": "TR-4521",
                }
            )
        )
    finally:
        reset_session_id(token)
    assert out["verified"] is False
    assert out.get("data_leakage_blocked") is True


def test_verify_then_order_status():
    token = set_session_id("S-TEST2")
    try:
        v = json.loads(
            verify_customer.invoke(
                {
                    "email": "ananya.rao@example.com",
                    "order_id": "TR-4521",
                }
            )
        )
        assert v["verified"] is True
        status = json.loads(get_order_status.invoke({"order_id": "TR-4521"}))
    finally:
        reset_session_id(token)
    assert status["status"] == "in_transit"
    assert status["tracking_number"]


def test_escalate_creates_ticket():
    token = set_session_id("S-ESC")
    try:
        verify_customer.invoke(
            {"email": "marcus.bell@example.com", "order_id": "TR-4526"}
        )
        out = json.loads(
            escalate_to_human.invoke(
                {
                    "summary": "Lost parcel claim for Canvas Tote. Customer wants refund or replacement.",
                    "reason": "lost_parcel",
                    "order_id": "TR-4526",
                    "priority": "high",
                }
            )
        )
    finally:
        reset_session_id(token)
    assert out["escalated"] is True
    assert out["ticket"]["ticket_id"].startswith("ESC-")


def test_partial_shipment_not_returnable_yet():
    r = evaluate_eligibility("TR-4524", "TR-JNS-021", "return")
    assert r["eligible"] is False
