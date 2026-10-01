from __future__ import annotations

import re
from typing import Any

from langsmith import traceable

# Classic jailbreaks + data-exfil / impersonation attempts (demo red-team)
INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions",
    r"disregard\s+(your\s+)?(system|policy)",
    r"you\s+are\s+now\s+(dan|jailbroken|unrestricted|a\s+hacker)",
    r"reveal\s+(your\s+)?system\s+prompt",
    r"pretend\s+policy\s+does\s+not\s+apply",
    r"override\s+(your\s+)?(rules|guardrails|policies)",
    r"jailbreak",
    r"developer\s+mode",
    r"act\s+as\s+(an?\s+)?(admin|root|superuser|internal\s+tool)",
    r"(dump|exfiltrate|export|leak)\s+(all\s+)?(orders?|customer|users?|ids?|pii|database|data)",
    r"(list|show|give)\s+(me\s+)?(all|every)\s+(orders?|customers?|emails?|phone)",
    r"without\s+(any\s+)?(verification|auth|identity)",
    r"skip\s+(identity|verification|auth)",
    r"steal\s+(orders?|data|ids?|customer)",
    r"other\s+customers?\s+(orders?|details|data)",
    r"cross[- ]customer",
]

OUTPUT_BLOCK_PATTERNS = [
    (r"\b(discount\s*code|promo\s*code|coupon)\s*[:=]?\s*[A-Z0-9-]{4,}\b", "invented_discount"),
    (r"\b(cvv|cvc)\b\s*[:=]?\s*\d{3,4}\b", "card_cvv"),
    (r"\b(?:\d[ -]*?){13,19}\b", "possible_card_number"),
    (r"\bifsc\b", "bank_ifsc_collection"),
    (r"share\s+(your\s+)?(bank|account)\s+(number|details)", "bank_details_request"),
]

SAFE_REFUSAL = (
    "I can't follow instructions that try to override Trendly's support policies "
    "or pull another customer's private order data. "
    "If this is your order, share your order id plus the email/phone on the account and I'll verify you. "
    "Otherwise I can connect you to a human agent."
)


@traceable(name="input_guardrail", run_type="chain")
def check_input(text: str) -> dict[str, Any]:
    low = text.lower()
    for pat in INJECTION_PATTERNS:
        if re.search(pat, low):
            return {
                "ok": False,
                "reason": "prompt_injection",
                "message": SAFE_REFUSAL,
            }
    return {"ok": True}


@traceable(name="output_guardrail", run_type="chain")
def check_output(text: str) -> dict[str, Any]:
    low = text.lower()
    hits: list[str] = []
    for pat, label in OUTPUT_BLOCK_PATTERNS:
        if re.search(pat, low if "discount" in label or "bank" in label or "ifsc" in label else text, re.I):
            hits.append(label)
    # Allow mentioning that we won't collect bank details
    if "bank_details_request" in hits and ("never" in low or "won't" in low or "will not" in low or "secure link" in low):
        hits = [h for h in hits if h != "bank_details_request"]
    if "bank_ifsc_collection" in hits and ("never" in low or "won't" in low or "human" in low):
        hits = [h for h in hits if h != "bank_ifsc_collection"]
    if hits:
        return {
            "ok": False,
            "reasons": hits,
            "message": (
                "I need to be careful with sensitive details and offers. "
                "I can't share invented discounts or collect bank/card details in chat. "
                "I can escalate you to a human agent who will use a secure process. "
                "Would you like me to escalate?"
            ),
        }
    return {"ok": True}
