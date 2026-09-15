"""OpenAI tool-calling agent loop + offline rules fallback."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any

import httpx

from board import board_context_for_llm, persist
from tools import HELP, OPENAI_TOOLS, dispatch, list_board, plan_study
from tools import (
    add_course,
    add_notes,
    add_task,
    complete_task,
    edit_notes,
    explain_topic,
    generate_flashcards,
    generate_quiz,
)


@dataclass
class ToolTrace:
    name: str
    args: dict[str, Any]
    result: str


@dataclass
class AgentResult:
    reply: str
    tools_used: list[ToolTrace] = field(default_factory=list)
    provider: str = "rules"


def default_model() -> str:
    return os.getenv("OPENAI_MODEL", "gpt-5")


def _openai_chat_with_tools(messages: list[dict[str, Any]]) -> dict[str, Any] | None:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None
    model = default_model()
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "tools": OPENAI_TOOLS,
        "tool_choice": "auto",
    }
    # gpt-5 family often rejects custom temperature; only set for classic chat models.
    if not model.startswith("gpt-5"):
        payload["temperature"] = 0.3
    try:
        with httpx.Client(timeout=90.0) as client:
            resp = client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json=payload,
            )
            resp.raise_for_status()
            return resp.json()
    except Exception:
        return None


def run_openai_agent(
    sid: str,
    board: dict[str, Any],
    message: str,
    history: list[dict[str, str]] | None = None,
) -> AgentResult | None:
    """Multi-round OpenAI function-calling loop. Returns None if API unavailable."""
    system = (
        "You are StudyBoard, a study tutor agent. "
        "Use tools to plan, explain, quiz, make flashcards, and update the live board "
        "(add/complete tasks, add/edit notes). "
        "The board index lists note titles only. "
        "Before explain, quiz, or flashcards, call retrieve_notes so answers are grounded "
        "in retrieved passages. Cite note titles. "
        "Prefer calling tools over inventing board state. After board mutations, briefly confirm what changed."
        "\n\n"
        + board_context_for_llm(board)[:8000]
    )
    messages: list[dict[str, Any]] = [{"role": "system", "content": system}]
    for turn in (history or [])[-8:]:
        role = turn.get("role")
        text = (turn.get("text") or "").strip()
        if role in {"user", "assistant"} and text:
            messages.append({"role": role, "content": text[:4000]})
    messages.append({"role": "user", "content": message})
    traces: list[ToolTrace] = []
    mutated = False
    model_name = default_model()

    for _ in range(6):
        data = _openai_chat_with_tools(messages)
        if not data:
            return None
        choice = data["choices"][0]["message"]
        tool_calls = choice.get("tool_calls") or []
        if not tool_calls:
            reply = (choice.get("content") or "").strip() or "Done."
            if mutated:
                persist(sid, board)
            return AgentResult(reply=reply, tools_used=traces, provider=model_name)

        # Assistant turn with tool calls must be appended as returned by the API.
        messages.append(
            {
                "role": "assistant",
                "content": choice.get("content"),
                "tool_calls": tool_calls,
            }
        )
        for tc in tool_calls:
            name = tc["function"]["name"]
            raw_args = tc["function"].get("arguments") or "{}"
            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
            except json.JSONDecodeError:
                args = {}
            result = dispatch(board, name, args)
            if name in {
                "add_task",
                "complete_task",
                "add_notes",
                "edit_notes",
                "add_course",
                "generate_quiz",
            }:
                mutated = True
            traces.append(ToolTrace(name=name, args=args, result=result[:500]))
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": result[:12000],
                }
            )

    if mutated:
        persist(sid, board)
    summary = " · ".join(t.name for t in traces) or "tools"
    return AgentResult(
        reply=f"Finished tool loop ({summary}). Ask another question if you need more.",
        tools_used=traces,
        provider=model_name,
    )


def parse_intent(message: str) -> tuple[str, dict[str, Any]]:
    raw = message.strip()
    lower = raw.lower()

    if lower in {"help", "?", "hi", "hello"}:
        return "help", {}

    if any(p in lower for p in ("what's on my board", "whats on my board", "show board", "list board", "status")):
        return "list_board", {}

    if any(p in lower for p in ("plan tonight", "what should i study", "study plan", "what next")):
        return "plan_study", {}

    m = re.match(r"add\s+course\s+([A-Za-z]{2,6}\s*\d{1,3}[A-Za-z]?)\s*[—:\-]\s*(.+)$", raw, re.I)
    if m:
        return "add_course", {"code": m.group(1).strip(), "name": m.group(2).strip()}

    m = re.match(r"(?:add\s+)?task:\s*(.+)$", raw, re.I)
    if m:
        body = m.group(1).strip()
        due = "sometime"
        priority = "medium"
        course_ref = None
        dm = re.search(r"\bdue\s+(\w+(?:\s+\w+)?)\s*$", body, re.I)
        if dm:
            due = dm.group(1)
            body = body[: dm.start()].strip(" ,.-")
        cm = re.search(r"\(([A-Za-z]{2,6}\s*\d{1,3}[A-Za-z]?)\)", body)
        if cm:
            course_ref = cm.group(1)
            body = (body[: cm.start()] + body[cm.end() :]).strip(" ,.-")
        return "add_task", {"title": body, "course_ref": course_ref, "due": due, "priority": priority}

    m = re.match(r"done:\s*(.+)$", raw, re.I) or re.match(r"complete\s+task\s+(.+)$", raw, re.I)
    if m:
        return "complete_task", {"title_ref": m.group(1).strip()}

    m = re.match(
        r"edit\s+notes?\s+(?:titled\s+)?([^:]+):\s*(.+)$",
        raw,
        re.I | re.S,
    )
    if m:
        return "edit_notes", {"note_ref": m.group(1).strip(), "content": m.group(2).strip(), "append": True}

    m = re.match(r"add\s+notes?\s+titled\s+([^:]+):\s*(.+)$", raw, re.I | re.S)
    if m:
        return "add_notes", {"title": m.group(1).strip(), "content": m.group(2).strip()}

    m = re.match(r"add\s+notes?\s*:\s*(.+)$", raw, re.I | re.S)
    if m:
        content = m.group(1).strip()
        title = content.split("\n", 1)[0][:60]
        return "add_notes", {"title": title, "content": content}

    m = re.match(r"explain\s+(.+)$", raw, re.I)
    if m:
        return "explain_topic", {"topic": m.group(1).strip()}

    m = re.match(r"(?:quiz\s+me(?:\s+on)?|quiz)\s+(.+)$", raw, re.I)
    if m:
        return "generate_quiz", {"topic": m.group(1).strip()}
    if lower in {"quiz me", "quiz"}:
        return "generate_quiz", {"topic": "my notes"}

    if lower.startswith("flashcard"):
        rest = raw.split(None, 1)
        topic = rest[1] if len(rest) > 1 else None
        return "generate_flashcards", {"topic": topic}

    if len(raw) < 200:
        return "explain_topic", {"topic": raw}

    return "help", {}


def run_rules_agent(sid: str, board: dict[str, Any], message: str) -> AgentResult:
    intent, args = parse_intent(message)
    traces: list[ToolTrace] = []

    def trace(name: str, result: str, a: dict[str, Any] | None = None) -> None:
        traces.append(ToolTrace(name=name, args=a or {}, result=result[:500]))

    if intent == "help":
        return AgentResult(reply=HELP, tools_used=[], provider="rules")

    if intent == "list_board":
        result = list_board(board)
        trace("list_board", result)
        return AgentResult(reply=result, tools_used=traces, provider="rules")

    if intent == "plan_study":
        result = plan_study(board)
        trace("plan_study", result)
        return AgentResult(reply=result, tools_used=traces, provider="rules")

    if intent == "add_course":
        result = add_course(board, args["code"], args["name"])
        trace("add_course", result, args)
        persist(sid, board)
        return AgentResult(reply=result, tools_used=traces, provider="rules")

    if intent == "add_task":
        result = add_task(
            board,
            args["title"],
            args.get("course_ref"),
            args.get("due", "sometime"),
            args.get("priority", "medium"),
        )
        trace("add_task", result, args)
        persist(sid, board)
        return AgentResult(reply=result, tools_used=traces, provider="rules")

    if intent == "complete_task":
        result = complete_task(board, args["title_ref"])
        trace("complete_task", result, args)
        persist(sid, board)
        return AgentResult(reply=result, tools_used=traces, provider="rules")

    if intent == "add_notes":
        result = add_notes(board, args["title"], args["content"])
        trace("add_notes", result, {"title": args["title"]})
        persist(sid, board)
        return AgentResult(reply=result, tools_used=traces, provider="rules")

    if intent == "edit_notes":
        result = edit_notes(
            board,
            args["note_ref"],
            args.get("new_title"),
            args.get("content"),
            bool(args.get("append", False)),
        )
        trace("edit_notes", result, args)
        persist(sid, board)
        return AgentResult(reply=result, tools_used=traces, provider="rules")

    if intent == "explain_topic":
        trace("retrieve_notes", "passages", {"query": args["topic"]})
        reply = explain_topic(board, args["topic"])
        trace("explain_topic", "explained (extractive)", args)
        return AgentResult(reply=reply, tools_used=traces, provider="extractive")

    if intent == "generate_quiz":
        trace("retrieve_notes", "passages", {"query": args.get("topic") or "my notes"})
        reply = generate_quiz(board, args.get("topic") or "my notes")
        persist(sid, board)
        trace("generate_quiz", "quiz generated", args)
        return AgentResult(reply=reply, tools_used=traces, provider="extractive")

    if intent == "generate_flashcards":
        topic = args.get("topic") or "key terms"
        trace("retrieve_notes", "passages", {"query": topic})
        reply = generate_flashcards(board, args.get("topic"))
        trace("generate_flashcards", "cards", args)
        return AgentResult(reply=reply, tools_used=traces, provider="extractive")

    return AgentResult(reply=HELP, tools_used=[], provider="rules")


def run_chat(
    sid: str,
    board: dict[str, Any],
    message: str,
    history: list[dict[str, str]] | None = None,
) -> AgentResult:
    """Prefer OpenAI tool calling when OPENAI_API_KEY is set; otherwise rules/extractive."""
    if os.getenv("OPENAI_API_KEY"):
        result = run_openai_agent(sid, board, message, history)
        if result is not None:
            return result
    return run_rules_agent(sid, board, message)
