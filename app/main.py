"""Thin FastAPI shell that hosts the agent. No CRUD endpoints — Hasura is the data API."""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import bootstrap
from .agent.agent import agent_stream
from .config import get_settings
from .hasura import client
from .hasura.schema import get_schema

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("app")

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    await bootstrap.run()
    yield
    await client.aclose()


app = FastAPI(
    title="Agent + Hasura + Postgres (backendless)",
    description="The agent is the business-logic layer; Hasura auto-exposes Postgres as GraphQL.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class Message(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    message: str
    history: list[Message] = []


def _sse(event: dict) -> str:
    return "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"


@app.post("/chat")
async def chat(req: ChatRequest):
    """Server-Sent Events stream of token / tool / done / error events."""

    async def generate():
        try:
            async for event in agent_stream(req.message, [m.model_dump() for m in req.history]):
                yield _sse(event)
        except Exception as exc:
            log.exception("agent stream failed")
            yield _sse({"type": "error", "data": str(exc)})

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/ask")
async def ask(req: ChatRequest):
    """Non-streaming convenience endpoint: full answer + the tool calls it made."""
    tokens: list[str] = []
    tools_used: list[str] = []
    try:
        async for event in agent_stream(req.message, [m.model_dump() for m in req.history]):
            if event["type"] == "token":
                tokens.append(event["data"])
            elif event["type"] == "tool":
                tools_used.append(event["data"]["name"])
            elif event["type"] == "error":
                return {"error": event["data"], "tool_calls": tools_used}
    except Exception as exc:
        log.exception("agent failed")
        return {"error": str(exc), "tool_calls": tools_used}
    return {"answer": "".join(tokens), "tool_calls": tools_used}


@app.get("/healthz")
async def healthz():
    try:
        await client.ping()
        hasura = "ok"
    except Exception as exc:
        hasura = f"error: {exc}"
    tracked_tables = None
    try:
        schema_text = await get_schema()
        tracked_tables = sum(1 for line in schema_text.splitlines() if line.startswith("TABLE "))
    except Exception:
        pass
    return {
        "agent_api": "ok",
        "hasura": hasura,
        "tracked_tables": tracked_tables,
        "model": get_settings().llm_model,
    }


@app.get("/")
async def root():
    return {
        "service": "agent + hasura + postgres (backendless)",
        "endpoints": {
            "chat_sse": "POST /chat",
            "ask_json": "POST /ask",
            "health": "GET /healthz",
            "ui": "GET /demo",
            "docs": "/docs",
        },
    }


if STATIC_DIR.is_dir():
    app.mount("/demo", StaticFiles(directory=str(STATIC_DIR), html=True), name="demo")
