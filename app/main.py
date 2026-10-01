from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.config import ROOT, get_settings
from app.data_store import get_store
from app.sessions import sessions

load_dotenv(ROOT / ".env")

app = FastAPI(
    title="Trendly Agentic Support Assistant",
    description="LangGraph + LangChain + LangSmith support agent for Yellow.ai FDE assignment",
    version="1.0.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

STATIC = ROOT / "static"
if STATIC.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    session_id: str | None = None


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    tool_trace: list[dict] = []
    flow_path: list[dict] = []
    verified_customer_id: str | None = None
    blocked: bool = False


class SessionResponse(BaseModel):
    session_id: str


@app.get("/")
def index():
    index_path = STATIC / "index.html"
    if not index_path.exists():
        raise HTTPException(404, "UI not found")
    return FileResponse(index_path)


@app.get("/health")
def health():
    settings = get_settings()
    store = get_store()
    return {
        "ok": True,
        "model": settings.gemini_model,
        "has_gemini": settings.has_gemini,
        "langsmith": settings.has_langsmith,
        "orders_loaded": len(store.orders),
        "reference_date": settings.reference_date,
    }


@app.post("/session", response_model=SessionResponse)
def create_session():
    return SessionResponse(session_id=sessions.create())


@app.post("/session/{session_id}/reset", response_model=SessionResponse)
def reset_session(session_id: str):
    sessions.reset(session_id)
    return SessionResponse(session_id=session_id)


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    settings = get_settings()
    if not settings.has_gemini:
        raise HTTPException(500, "GOOGLE_API_KEY not configured")
    sid = req.session_id or sessions.create()
    try:
        result = sessions.chat(sid, req.message.strip())
    except Exception as e:
        raise HTTPException(500, f"Agent error: {e}") from e
    return ChatResponse(**result)


@app.get("/demo/orders")
def demo_orders():
    """Helper for demos — lists order ids and statuses (no PII beyond what's in fixture notes)."""
    store = get_store()
    return [
        {
            "order_id": o["order_id"],
            "status": o["status"],
            "customer_id": o["customer_id"],
            "items": [i["name"] for i in o["items"]],
        }
        for o in store.orders.values()
    ]


def main():
    import uvicorn

    settings = get_settings()
    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=False)


if __name__ == "__main__":
    main()
