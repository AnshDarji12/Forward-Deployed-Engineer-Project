# SOLUTION.md — Architecture & FDE Notes

**Product:** Trendly Agentic Support Assistant  
**Stack:** LangGraph · LangChain · LangSmith · Gemini 2.5 Flash (free tier) · FastAPI  
**Assignment context:** Yellow.ai FDE Intern screening

## Architecture

The agent is a **LangGraph `StateGraph`** (cyclic, not a DAG):

1. **`input_guardrail`** (deterministic) — prompt-injection / abuse patterns  
2. **`agent`** (LLM node) — Gemini via LangChain `ChatGoogleGenerativeAI.bind_tools`  
3. **`tools`** (LangGraph `ToolNode`) — LangChain `@tool` functions; loop back to agent  
4. **`output_guardrail`** (deterministic checker) — blocks unsafe draft replies  

Session state (history + verified customer id) lives in process memory / `DataStore`, **outside** the raw LLM context window — aligned with “memory on disk / store, not only in chat” thinking from loop-engineering practice.

Policy answers are retrieved by `search_policy` over `trendly_policy.md`.  
Return/exchange money paths are decided by **`evaluate_eligibility`** (deterministic rules), then executed by action tools that **re-check** eligibility before writing records.

Observability: LangSmith traces each turn (`trendly_chat_turn`) with nested tool and guardrail spans when `LANGCHAIN_TRACING_V2` + API key are set.

See `docs/agent_orchestration_graph.png` for the whiteboard view.  
See [`docs/trendly-ai-architecture.png`](docs/trendly-ai-architecture.png) for the AI system design architecture diagram (client → FastAPI → LangGraph guardrail/LLM/tool loop → data + LangSmith traces).

## Key trade-offs

| Choice | Why | Cost |
|--------|-----|------|
| LangGraph explicit graph vs only `create_react_agent` | Makes guardrail nodes first-class and interview-explainable | Slightly more code than one-liner prebuilt |
| Deterministic eligibility in Python | No hallucinated refunds; evaluable with pytest | LLM must be instructed to trust tools |
| Gemini Flash free tier | Assignment cost constraint | Rate limits; need stable prompts |
| In-memory sessions / returns | One-command demo, no infra | Not multi-instance durable |
| Policy keyword/section retrieval | Tiny doc; transparent; cached | Not semantic RAG — fine for this corpus |

## Known limitations

1. Session state is in-process — restart clears verifications and demo return tickets.  
2. Size-exchange inventory is not modeled — unavailable-size → refund conversion (policy 4.3) is explained, not stock-checked.  
3. Damage claims need photos — agent can require them / escalate, but there is no upload API.  
4. Free-tier Gemini rate limits may slow multi-tool turns under load.  
5. Output guardrails are regex/heuristic — not a full safety classifier.  
6. `orders.json` keeps the original 10 assignment records and adds a demo catalog (TR-4531+) so tools can later wrap a real OMS.

## Five discovery questions for Trendly ops (before production)

1. **Auth:** What is the source of truth for customer identity in chat (OTP, logged-in app token, email magic link), and what is the false-accept tolerance?  
2. **Escalation SLA:** Which queue owns lost-parcel vs COD bank-detail vs second-exchange approvals, and what fields must the ticket always include?  
3. **Policy versioning:** How often does `Shipping & Returns` change, who signs off, and should the bot pin a policy version id in every answer?  
4. **Exception budget:** When may agents grant goodwill beyond the ₹250 delay credit, and should the bot ever soft-promise “I’ll ask a supervisor”?  
5. **Success metrics:** What % deflection target, CSAT floor, and “wrong refund issued” hard-fail rate define ship / no-ship for this agent?

## Demo video outline (3–5 min)

1. Happy path — TR-4530 return (Marcus)  
2. Edge — TR-4527 jewellery refused; or TR-4528 final-sale exchange-only  
3. Edge — TR-4526 lost parcel → escalation ticket  
4. One thing that doesn’t work — e.g. inventing a discount (refused), or asking about a policy gap → escalate  

## How to run

See [README.md](README.md).
