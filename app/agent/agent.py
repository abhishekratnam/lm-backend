"""Streaming agent loop: model -> tool calls against Hasura -> results -> final answer."""

from __future__ import annotations

import json
import uuid
from typing import AsyncIterator

from openai import AsyncOpenAI

from ..config import get_settings
from ..hasura.schema import get_schema
from .prompts import build_system_prompt
from .tools import TOOLS, execute_tool


def _llm() -> AsyncOpenAI:
    settings = get_settings()
    if not settings.llm_api_key:
        raise RuntimeError("LLM_API_KEY is not set — add it to .env (see .env.example)")
    return AsyncOpenAI(
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        default_headers={"User-Agent": "lm-backend-agent/0.1"},
    )


def _history_messages(history: list[dict]) -> list[dict]:
    messages = []
    for item in history:
        role = item.get("role")
        content = item.get("content")
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    return messages


def _parse_args(raw: str):
    try:
        return json.loads(raw or "{}")
    except json.JSONDecodeError:
        return raw


async def agent_stream(message: str, history: list[dict]) -> AsyncIterator[dict]:
    """Yield events: {"type": "token"|"tool"|"done"|"error", "data": ...}."""
    settings = get_settings()
    schema_text = await get_schema()

    messages: list[dict] = [
        {"role": "system", "content": build_system_prompt(schema_text)},
        *_history_messages(history),
        {"role": "user", "content": message},
    ]

    llm = _llm()

    for _ in range(max(1, settings.llm_max_tool_rounds)):
        # OpenCode Go requires a stable x-opencode-session per conversation
        # (routing consistency + prompt-cache reuse).
        stream = await llm.chat.completions.create(
            model=settings.llm_model,
            messages=messages,
            tools=TOOLS,
            stream=True,
            extra_headers={"x-opencode-session": f"ses_{uuid.uuid4().hex}"},
        )

        content_parts: list[str] = []
        calls: dict[int, dict] = {}

        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta is None:
                continue
            if delta.content:
                content_parts.append(delta.content)
                yield {"type": "token", "data": delta.content}
            for tc in delta.tool_calls or []:
                index = tc.index if tc.index is not None else 0
                slot = calls.setdefault(index, {"id": "", "name": "", "arguments": ""})
                if tc.id:
                    slot["id"] = tc.id
                if tc.function:
                    if tc.function.name:
                        slot["name"] = tc.function.name
                    if tc.function.arguments:
                        slot["arguments"] += tc.function.arguments

        text = "".join(content_parts)

        if not calls:
            yield {"type": "done", "data": text}
            return

        # Build the assistant message carrying the tool calls.
        assistant = {"role": "assistant", "content": text or None, "tool_calls": []}
        for index in sorted(calls):
            slot = calls[index]
            slot["id"] = slot["id"] or f"call_{index}"
            assistant["tool_calls"].append(
                {
                    "id": slot["id"],
                    "type": "function",
                    "function": {"name": slot["name"], "arguments": slot["arguments"] or "{}"},
                }
            )
            yield {"type": "tool", "data": {"name": slot["name"], "arguments": _parse_args(slot["arguments"])}}
        messages.append(assistant)

        # Execute tools and feed results back as tool messages.
        for index in sorted(calls):
            slot = calls[index]
            try:
                result = await execute_tool(slot["name"], slot["arguments"])
            except Exception as exc:  # never crash the loop on one tool failure
                result = f"TOOL_ERROR: {exc}"
            messages.append({"role": "tool", "tool_call_id": slot["id"], "content": result})

    yield {"type": "error", "data": f"Agent hit the tool-round limit ({settings.llm_max_tool_rounds})."}
