from __future__ import annotations

import os
from typing import Annotated, Any, Sequence, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langsmith import traceable

from app.agent.guardrails import check_input, check_output
from app.agent.prompts import SYSTEM_PROMPT, build_turn_context
from app.agent.text import message_text
from app.config import get_settings
from app.data_store import get_store
from app.runtime_context import reset_session_id, set_session_id
from app.tools import ALL_TOOLS


class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    session_id: str
    blocked: bool
    guardrail_message: str
    tool_trace: list[dict[str, Any]]
    flow_path: list[dict[str, Any]]


def _flow(state: AgentState, step: dict[str, Any]) -> list[dict[str, Any]]:
    path = list(state.get("flow_path") or [])
    path.append(step)
    return path


def _configure_langsmith() -> None:
    settings = get_settings()
    if settings.langchain_api_key:
        os.environ.setdefault("LANGCHAIN_API_KEY", settings.langchain_api_key)
        os.environ.setdefault("LANGSMITH_API_KEY", settings.langchain_api_key)
    if settings.langchain_tracing_v2 or settings.langchain_api_key:
        os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")
        os.environ.setdefault("LANGSMITH_TRACING", "true")
    os.environ.setdefault("LANGCHAIN_PROJECT", settings.langchain_project)
    os.environ.setdefault("LANGSMITH_PROJECT", settings.langchain_project)
    if settings.langchain_endpoint:
        os.environ.setdefault("LANGCHAIN_ENDPOINT", settings.langchain_endpoint)


def build_llm() -> ChatGoogleGenerativeAI:
    settings = get_settings()
    if not settings.has_gemini:
        raise RuntimeError("GOOGLE_API_KEY missing. Copy .env.example to .env and set your key.")
    return ChatGoogleGenerativeAI(
        model=settings.gemini_model,
        google_api_key=settings.google_api_key,
        temperature=0.2,
    )


def input_guardrail_node(state: AgentState) -> dict[str, Any]:
    last_human = None
    for m in reversed(state["messages"]):
        if isinstance(m, HumanMessage):
            last_human = m
            break
    text = message_text(last_human.content if last_human else "")
    flow = _flow(state, {"id": "user", "label": "User message"})
    result = check_input(text)
    if not result["ok"]:
        flow.append({"id": "input_guardrail", "label": "Input guardrail", "status": "blocked"})
        flow.append({"id": "blocked_safe", "label": "Safe refusal (no tools)", "status": "blocked"})
        flow.append({"id": "reply", "label": "Reply to user", "status": "done"})
        return {
            "blocked": True,
            "guardrail_message": result["message"],
            "messages": [AIMessage(content=result["message"])],
            "flow_path": flow,
        }
    flow.append({"id": "input_guardrail", "label": "Input guardrail", "status": "ok"})
    store = get_store()
    sid = state["session_id"]
    flow.append(
        {
            "id": "session_state",
            "label": "Session state loader",
            "status": "ok",
            "detail": store.session_customers.get(sid) or "unverified",
        }
    )
    return {"blocked": False, "guardrail_message": "", "flow_path": flow}


def agent_node(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    if state.get("blocked"):
        return {}
    settings = get_settings()
    store = get_store()
    sid = state["session_id"]
    verified = store.session_customers.get(sid)
    llm = build_llm().bind_tools(ALL_TOOLS)
    context = build_turn_context(settings.reference_date, sid, verified)
    sys = [SystemMessage(content=SYSTEM_PROMPT), SystemMessage(content=context)]
    # Avoid duplicating system messages every turn — only prepend for the model call
    history = [m for m in state["messages"] if not isinstance(m, SystemMessage)]
    response = llm.invoke(sys + history, config=config)
    had_tools = any(isinstance(m, ToolMessage) for m in state["messages"])
    if getattr(response, "tool_calls", None):
        return {
            "messages": [response],
            "flow_path": _flow(state, {"id": "planner", "label": "Planner / Router (Gemini)", "status": "ok"}),
        }
    if had_tools:
        return {
            "messages": [response],
            "flow_path": _flow(state, {"id": "synthesis", "label": "Synthesis (Gemini)", "status": "ok"}),
        }
    flow = _flow(state, {"id": "planner", "label": "Planner / Router (Gemini)", "status": "direct"})
    flow.append({"id": "synthesis", "label": "Synthesis (Gemini)", "status": "direct"})
    return {"messages": [response], "flow_path": flow}


def tools_node(state: AgentState) -> dict[str, Any]:
    if state.get("blocked"):
        return {}
    token = set_session_id(state["session_id"])
    try:
        tool_node = ToolNode(ALL_TOOLS)
        result = tool_node.invoke({"messages": state["messages"]})
    finally:
        reset_session_id(token)
    trace = list(state.get("tool_trace") or [])
    flow = list(state.get("flow_path") or [])
    for m in result.get("messages", []):
        if isinstance(m, ToolMessage):
            trace.append({"tool": m.name, "content": m.content[:2000]})
            flow.append({"id": f"tool:{m.name}", "label": m.name, "status": "ok", "tool": m.name})
    flow.append({"id": "tool_result", "label": "Tool result → state", "status": "ok"})
    flow.append({"id": "decision", "label": "Enough info?", "status": "loop"})
    return {"messages": result["messages"], "tool_trace": trace, "flow_path": flow}


def output_guardrail_node(state: AgentState) -> dict[str, Any]:
    if state.get("blocked"):
        return {}
    flow = list(state.get("flow_path") or [])
    if flow and flow[-1].get("id") == "decision":
        flow[-1] = {"id": "decision", "label": "Enough info?", "status": "yes"}
    elif not any(s.get("id") == "decision" for s in flow):
        flow.append({"id": "decision", "label": "Enough info?", "status": "yes"})
    last = state["messages"][-1]
    if not isinstance(last, AIMessage):
        flow.append({"id": "reply", "label": "Reply to user", "status": "done"})
        return {"flow_path": flow}
    text = message_text(last.content)
    if not text.strip():
        flow.append({"id": "reply", "label": "Reply to user", "status": "done"})
        return {"flow_path": flow}
    result = check_output(text)
    if not result["ok"]:
        flow.append({"id": "output_guardrail", "label": "Output guardrail", "status": "fail"})
        flow.append({"id": "tool:escalate_to_human", "label": "escalate_to_human", "status": "ok", "tool": "escalate_to_human"})
        flow.append({"id": "reply", "label": "Reply to user", "status": "done"})
        return {
            "messages": [AIMessage(content=result["message"])],
            "guardrail_message": result["message"],
            "flow_path": flow,
        }
    flow.append({"id": "output_guardrail", "label": "Output guardrail", "status": "ok"})
    flow.append({"id": "reply", "label": "Reply to user", "status": "done"})
    return {"flow_path": flow}


def route_after_input(state: AgentState) -> str:
    if state.get("blocked"):
        return END
    return "agent"


def route_after_agent(state: AgentState) -> str:
    if state.get("blocked"):
        return END
    last = state["messages"][-1]
    if isinstance(last, AIMessage) and last.tool_calls:
        return "tools"
    return "output_guardrail"


def build_graph():
    _configure_langsmith()
    graph = StateGraph(AgentState)
    graph.add_node("input_guardrail", input_guardrail_node)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tools_node)
    graph.add_node("output_guardrail", output_guardrail_node)

    graph.add_edge(START, "input_guardrail")
    graph.add_conditional_edges("input_guardrail", route_after_input, {"agent": "agent", END: END})
    graph.add_conditional_edges(
        "agent",
        route_after_agent,
        {"tools": "tools", "output_guardrail": "output_guardrail", END: END},
    )
    graph.add_edge("tools", "agent")
    graph.add_edge("output_guardrail", END)
    return graph.compile()


_graph = None


def get_graph():
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph


@traceable(name="trendly_chat_turn", run_type="chain")
def run_turn(
    user_message: str,
    session_id: str,
    history: list[BaseMessage] | None = None,
) -> dict[str, Any]:
    graph = get_graph()
    messages: list[BaseMessage] = list(history or [])
    messages.append(HumanMessage(content=user_message))
    result = graph.invoke(
        {
            "messages": messages,
            "session_id": session_id,
            "blocked": False,
            "guardrail_message": "",
            "tool_trace": [],
            "flow_path": [],
        },
        config={
            "run_name": "trendly_support_turn",
            "tags": ["trendly", "support-agent"],
            "metadata": {"session_id": session_id},
            "recursion_limit": 25,
        },
    )
    final_messages = result["messages"]
    reply = ""
    for m in reversed(final_messages):
        if isinstance(m, AIMessage) and message_text(m.content) and not m.tool_calls:
            reply = message_text(m.content)
            break
    return {
        "reply": reply,
        "messages": final_messages,
        "tool_trace": result.get("tool_trace") or [],
        "flow_path": result.get("flow_path") or [],
        "blocked": result.get("blocked", False),
        "session_id": session_id,
        "verified_customer_id": get_store().session_customers.get(session_id),
    }
