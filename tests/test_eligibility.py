from __future__ import annotations

import pytest

from app.data_store import reset_store, search_policy_cached
from app.tools.eligibility import evaluate_eligibility


@pytest.fixture(autouse=True)
def _fresh_store():
    reset_store()
    search_policy_cached.cache_clear()
    yield
    reset_store()


def test_happy_path_return_eligible():
    r = evaluate_eligibility("TR-4530", "TR-KRT-033", "return")
    assert r["eligible"] is True
    assert r["action"] == "return"


def test_expired_window_refused():
    r = evaluate_eligibility("TR-4523", "TR-JKT-008", "return")
    assert r["eligible"] is False
    assert any("30-day" in x for x in r["reasons"])


def test_jewellery_non_returnable():
    r = evaluate_eligibility("TR-4527", "TR-EAR-042", "return")
    assert r["eligible"] is False
    assert any("non-returnable" in x.lower() or "jewellery" in x.lower() for x in r["reasons"])


def test_final_sale_exchange_only():
    r = evaluate_eligibility("TR-4528", "TR-SHR-009", "return")
    assert r["eligible"] is False
    assert r.get("suggest_action") == "exchange"
    ex = evaluate_eligibility("TR-4528", "TR-SHR-009", "exchange")
    assert ex["eligible"] is True


def test_lost_parcel_must_escalate():
    r = evaluate_eligibility("TR-4526", "TR-BAG-011", "return")
    assert r["eligible"] is False
    assert r.get("must_escalate") is True


def test_cancelled_order_no_return():
    r = evaluate_eligibility("TR-4529", "TR-SCF-027", "return")
    assert r["eligible"] is False
    assert any("cancelled" in x.lower() for x in r["reasons"])


def test_socks_in_mixed_order_non_returnable():
    r = evaluate_eligibility("TR-4522", "TR-SOK-031", "return")
    assert r["eligible"] is False
    tee = evaluate_eligibility("TR-4522", "TR-TSH-002", "return")
    assert tee["eligible"] is True


def test_policy_search_returns_sections():
    text = search_policy_cached("return window 30 days")
    assert "30" in text
    assert "NO_RELEVANT_SECTION" not in text


def test_damaged_within_48h_eligible():
    r = evaluate_eligibility("TR-4531", "TR-DRS-022", "return", reason="damaged")
    assert r["eligible"] is True
    assert r.get("requires_photos") is True


def test_fragrance_non_returnable():
    r = evaluate_eligibility("TR-4533", "TR-FRG-004", "return")
    assert r["eligible"] is False
    assert any("non-returnable" in x.lower() or "fragrance" in x.lower() for x in r["reasons"])


def test_cod_return_eligible_but_no_bank_in_chat():
    r = evaluate_eligibility("TR-4537", "TR-SHT-015", "return")
    assert r["eligible"] is True
    assert any("bank" in n.lower() for n in r.get("notes", []))
