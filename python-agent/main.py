"""Tool-calling AI agent service (FastAPI).

Uses OpenAI when OPENAI_API_KEY is set; otherwise a deterministic mock LLM
that still exercises the tool loop so the demo runs offline.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

app = FastAPI(title="AI Agent Service", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

MEMORY: dict[str, str] = {}


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    session_id: str | None = None


class ToolTrace(BaseModel):
    name: str
    args: dict[str, Any]
    result: str


class ChatResponse(BaseModel):
    reply: str
    tools_used: list[ToolTrace]
    provider: str


def tool_calculator(expression: str) -> str:
    allowed = re.fullmatch(r"[\d\.\+\-\*/\(\) ]+", expression or "")
    if not allowed:
        return "error: only basic arithmetic is allowed"
    try:
        value = eval(expression, {"__builtins__": {}}, {})  # noqa: S307 — demo sandbox
        return str(value)
    except Exception as exc:  # noqa: BLE001
        return f"error: {exc}"


def tool_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def tool_memory_set(key: str, value: str) -> str:
    MEMORY[key] = value
    return f"stored {key}={value}"


def tool_memory_get(key: str) -> str:
    return MEMORY.get(key, f"(no value for {key})")


TOOLS = {
    "calculator": lambda args: tool_calculator(str(args.get("expression", ""))),
    "current_time": lambda _args: tool_now(),
    "memory_set": lambda args: tool_memory_set(str(args.get("key", "")), str(args.get("value", ""))),
    "memory_get": lambda args: tool_memory_get(str(args.get("key", ""))),
}


def run_tools_from_text(message: str) -> tuple[str, list[ToolTrace]]:
    """Mock agent policy: detect intents and call tools, then answer."""
    traces: list[ToolTrace] = []
    lower = message.lower()
    facts: list[str] = []

    calc = re.search(r"(?:calculate|compute|what is|what's)\s+([0-9\.\+\-\*/\(\) ]+)", lower)
    if calc or re.fullmatch(r"[\d\.\+\-\*/\(\) ]+", message.strip()):
        expr = calc.group(1) if calc else message.strip()
        result = TOOLS["calculator"]({"expression": expr})
        traces.append(ToolTrace(name="calculator", args={"expression": expr}, result=result))
        facts.append(f"calculation result: {result}")

    if any(k in lower for k in ("time", "date", "utc", "clock")):
        result = TOOLS["current_time"]({})
        traces.append(ToolTrace(name="current_time", args={}, result=result))
        facts.append(f"current time: {result}")

    remember = re.search(r"remember\s+(\w+)\s*(?:is|=)\s*(.+)$", message, re.I)
    if remember:
        key, value = remember.group(1), remember.group(2).strip()
        result = TOOLS["memory_set"]({"key": key, "value": value})
        traces.append(ToolTrace(name="memory_set", args={"key": key, "value": value}, result=result))
        facts.append(result)

    recall = re.search(r"(?:what(?:'s| is)|recall|get)\s+(\w+)", lower)
    if recall and "time" not in lower:
        key = recall.group(1)
        if key not in {"the", "a", "an", "my", "current"}:
            result = TOOLS["memory_get"]({"key": key})
            traces.append(ToolTrace(name="memory_get", args={"key": key}, result=result))
            facts.append(f"{key}: {result}")

    if facts:
        reply = "I used tools to answer.\n" + "\n".join(f"- {f}" for f in facts)
    else:
        reply = (
            "I'm a demo tool-calling agent. Try: "
            "'calculate 12 * (3 + 4)', 'what time is it', "
            "or 'remember project is fullstack-ai-agent'."
        )
    return reply, traces


def run_openai(message: str) -> tuple[str, list[ToolTrace], str]:
    """Optional real-model path; falls back to mock on any failure."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        reply, traces = run_tools_from_text(message)
        return reply, traces, "mock-llm"

    try:
        import httpx

        # Keep the live path simple: one-shot completion that may emit tool JSON.
        system = (
            "You are a concise engineering assistant. "
            "If you need a tool, reply ONLY with JSON: "
            '{"tool":"calculator|current_time|memory_set|memory_get","args":{...}}. '
            "Otherwise answer normally."
        )
        payload = {
            "model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": message},
            ],
            "temperature": 0.2,
        }
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json=payload,
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"].strip()

        traces: list[ToolTrace] = []
        if content.startswith("{") and "tool" in content:
            spec = json.loads(content)
            name = spec.get("tool")
            args = spec.get("args") or {}
            if name in TOOLS:
                result = TOOLS[name](args)
                traces.append(ToolTrace(name=name, args=args, result=result))
                return f"Tool {name} → {result}", traces, "openai"

        return content, traces, "openai"
    except Exception:
        reply, traces = run_tools_from_text(message)
        return reply, traces, "mock-llm-fallback"


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/agent/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    reply, traces, provider = run_openai(req.message)
    return ChatResponse(reply=reply, tools_used=traces, provider=provider)
