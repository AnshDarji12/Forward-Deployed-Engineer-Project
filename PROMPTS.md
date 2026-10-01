# PROMPTS.md — Trendly Support Assistant

## System prompt (production)

Located in `app/agent/prompts.py` as `SYSTEM_PROMPT`.

Design goals:
1. Force **tool grounding** for policy (never invent).
2. Force **identity verification** before order disclosure.
3. Encode **hard refusals** from policy §7 (discounts, bank details, cross-customer data).
4. Encode **lost-parcel ≠ return** and escalate path.
5. Prefer short, empathetic, operational language (FDE / ops-friendly).

### Iteration log

| Version | Change | Why |
|---------|--------|-----|
| v0 | “You are a helpful fashion support bot…” | Too soft — model offered goodwill discounts in dry runs |
| v1 | Added explicit “never invent policy / discounts” | Still leaked order details before verify in one trial |
| v2 | Required `verify_customer` before any order reveal; listed tools by name | Better, but COD bank-detail asks still slipped into prose |
| v3 (current) | Enumerated hard rules 1–10; COD → escalate only; lost parcel rule; reference_date context message | Matches assignment safety + edge cases |

### Per-turn context message

`build_turn_context(...)` injects:
- `reference_date` (for 30-day / 48-hour windows — assignment fixtures are dated mid-2026)
- `session_id`
- `verified_customer_id`

This keeps **state outside the model’s imagination** (session store + DataStore), while still giving the planner situational awareness.

## Guardrail copy

**Input (injection):** refuses override attempts; offers real help or human handoff.  
**Output (safety):** if draft contains invented coupon / card / bank collection patterns, replace with refusal + escalate offer (`app/agent/guardrails.py`).

## Tool docstrings = prompt surface

LangChain `@tool` docstrings are part of the model-facing schema. Iterated to be imperative and failure-mode explicit, e.g.:
- `search_policy`: “If NO_RELEVANT_SECTION… do not invent”
- `get_order_status`: “Requires verified session”
- `escalate_to_human`: lists reason enums for structured tickets

## What we deliberately did *not* put in the prompt

Business eligibility math (30 days, final sale, jewellery, etc.) lives in **`evaluate_eligibility`** Python — not in prose — so the model cannot “talk itself into” a refund.
