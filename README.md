# Trendly Agentic Support Assistant

Yellow.ai · Forward Deployed Engineer (Intern) · Screening Assignment

An **agentic** customer-support assistant for Trendly (D2C fashion) built with:

- **LangGraph** — graph orchestration (guardrails → planner/tools loop → output check)
- **LangChain** — Gemini LLM + `@tool` function calling
- **LangSmith** — full turn / tool / guardrail traces

Handles order status, policy Q&A (grounded in `data/trendly_policy.md`), return/exchange eligibility + actions, delay credits, and human escalation — with identity checks and safety refusals.

## One-command run

```bash
cd trendly-support-agent
python -m venv .venv
# Windows:
.\.venv\Scripts\activate
# macOS/Linux:
# source .venv/bin/activate

pip install -r requirements.txt
copy .env.example .env   # then set GOOGLE_API_KEY (+ optional LangSmith keys)
python -m app.main
```

Open **http://127.0.0.1:8080**

Health: `GET /health` · Chat: `POST /chat` · New session: `POST /session`

## AI usage note

Built with Cursor assistance for scaffolding, prompts, and docs. Tool schemas, eligibility rules, LangGraph topology, and edge-case tests were designed against the assignment fixtures (`orders.json`, `trendly_policy.md`) and reviewed/iterated manually. Be ready to explain and modify the graph live.

## What the agent can do

| Capability | How |
|------------|-----|
| Order lookup | `verify_customer` → `get_order_status` / `list_customer_orders` |
| Policy answers | `search_policy` over `trendly_policy.md` only |
| Returns / exchanges | `check_return_eligibility` (deterministic rules) → `initiate_return_or_exchange` |
| Delay credit | `issue_delay_credit` (₹250 when status=`delayed`) |
| Escalation | `escalate_to_human` with structured ticket |
| Safety | Input/output guardrail nodes + tool-level ownership checks |

## Observability (LangSmith)

Set in `.env`:

```
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=...
LANGCHAIN_PROJECT=trendly-support-agent
```

Each chat turn appears as a traced run with nested tool and guardrail spans.

## Caching / latency

- **Implicit Gemini prompt-prefix reuse**: system prompt + tool schemas kept stable across turns
- **`functools.lru_cache`** on policy section retrieval (`search_policy_cached`)
- Eligibility is pure Python (no LLM) — fast and non-hallucinating for money-path decisions

## Tests

```bash
pytest -q
```

## Demo fixtures

- `data/orders.json` — original 10 assignment orders (**TR-4521–TR-4530**) plus extra demo catalog (**TR-4531–TR-4545**, 11 customers)
- `data/trendly_policy.md` — sole policy source of truth
- `docs/trendly-ai-architecture.png` — AI system design architecture diagram

Useful demo identities:

| Customer | Email | Interesting orders |
|----------|-------|--------------------|
| Ananya Rao | ananya.rao@example.com | TR-4521 in transit, TR-4524 partial, TR-4529 cancelled, TR-4538 face mask |
| Marcus Bell | marcus.bell@example.com | TR-4530 happy return, TR-4526 lost |
| Priya Nair | priya.nair@example.com | TR-4527 jewellery, TR-4523 expired, TR-4540 mixed cart |
| Diego Ramos | diego.ramos@example.com | TR-4525 delayed, TR-4528 final sale |
| Meera Shah | meera.shah@example.com | TR-4531 damaged (48h), TR-4532 damage too late |
| Rohan Iyer | rohan.iyer@example.com | TR-4533 fragrance, TR-4541 cancel pending refund |
| Sara Khan | sara.khan@example.com | TR-4534 gift card, TR-4545 partial ship |
| Kenji Sato | kenji.sato@example.com | TR-4535 footwear box, TR-4543 final-sale mix |
| Leila Haddad | leila.haddad@example.com | TR-4536 processing, TR-4544 lost duffle |
| Omar Farouk | omar.farouk@example.com | TR-4537 COD return (no bank details in chat) |
| Nina Patel | nina.patel@example.com | TR-4539 delay credit, TR-4542 in transit |

## Docs

- [PROMPTS.md](PROMPTS.md) — prompts + iteration notes
- [SOLUTION.md](SOLUTION.md) — architecture, trade-offs, limitations, discovery questions
- [docs/agent_orchestration_graph.png](docs/agent_orchestration_graph.png) — orchestration diagram
- [docs/trendly-ai-architecture.png](docs/trendly-ai-architecture.png) — AI system design architecture diagram
