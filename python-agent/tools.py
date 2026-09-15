"""StudyBoard agent tools — callable by the OpenAI tool loop or the rules fallback."""

from __future__ import annotations

import json
import re
import uuid
from typing import Any, Callable

from board import (
    find_course,
    find_material,
    materials_for,
    now,
    open_tasks,
    board_snapshot,
)
from retrieve import citation_line, format_passages, notes_from_hits, retrieve

# OpenAI Chat Completions tool schemas.
OPENAI_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "retrieve_notes",
            "description": (
                "Search the student's notes by keyword overlap and return the most relevant "
                "passages with titles. Call this before explain, quiz, or flashcards."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Topic or question to search in notes",
                    },
                    "k": {"type": "integer", "description": "Max passages (default 4)"},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_board",
            "description": "Show courses, open tasks, and note titles on the live study board.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "plan_study",
            "description": "Build a prioritized study plan from open tasks (what to study next / tonight).",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "explain_topic",
            "description": "Explain a topic using ONLY the student's own course notes when possible.",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "description": "Topic to explain"},
                    "course_ref": {
                        "type": "string",
                        "description": "Optional course code/name to scope notes",
                    },
                },
                "required": ["topic"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_quiz",
            "description": "Generate a short quiz grounded in the student's course materials.",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string"},
                    "n": {"type": "integer", "description": "Number of questions (default 3)"},
                },
                "required": ["topic"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_flashcards",
            "description": "Make flashcards from the student's notes for spaced review.",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "description": "Optional topic filter"},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_task",
            "description": "Add a task to the live study board.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "course_ref": {"type": "string"},
                    "due": {"type": "string"},
                    "priority": {"type": "string", "enum": ["high", "medium", "low"]},
                },
                "required": ["title"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "complete_task",
            "description": "Mark a task done on the live study board.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title_ref": {"type": "string", "description": "Task id or title substring"},
                },
                "required": ["title_ref"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_notes",
            "description": "Add a new notes entry to the board.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "content": {"type": "string"},
                    "course_ref": {"type": "string"},
                },
                "required": ["title", "content"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_notes",
            "description": "Edit an existing notes entry (title and/or content) on the live board.",
            "parameters": {
                "type": "object",
                "properties": {
                    "note_ref": {"type": "string", "description": "Note id or title substring"},
                    "new_title": {"type": "string"},
                    "content": {"type": "string", "description": "Replacement note body"},
                    "append": {
                        "type": "boolean",
                        "description": "If true, append content instead of replacing",
                    },
                },
                "required": ["note_ref"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_course",
            "description": "Add a course to the board.",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string"},
                    "name": {"type": "string"},
                },
                "required": ["code", "name"],
                "additionalProperties": False,
            },
        },
    },
]


def list_board(board: dict[str, Any]) -> str:
    s = board_snapshot(board)["stats"]
    lines = [
        f"Board: **{s['courses']}** courses · **{s['open_tasks']}** open tasks · "
        f"**{s['materials']}** notes · **{s['quizzes_taken']}** quizzes",
        "",
        "Courses:",
    ]
    for c in board["courses"]:
        lines.append(f"- {c['code']} — {c['name']}")
    lines.append("")
    lines.append("Open tasks:")
    for t in open_tasks(board)[:8]:
        lines.append(f"- [{t.get('priority', 'med')}] {t['title']} (due {t.get('due')})")
    if not open_tasks(board):
        lines.append("- (none)")
    lines.append("")
    lines.append("Notes:")
    for m in board["materials"][:8]:
        lines.append(f"- {m['title']} (id={m['id']})")
    if not board["materials"]:
        lines.append("- (none)")
    return "\n".join(lines)


def plan_study(board: dict[str, Any]) -> str:
    tasks = open_tasks(board)
    if not tasks:
        return "No open tasks. Add something to study, or ask me to quiz you on your notes."

    def rank(t: dict[str, Any]) -> tuple[int, int]:
        due = (t.get("due") or "").lower()
        pri = (t.get("priority") or "medium").lower()
        due_score = 0 if "tonight" in due else 1 if "week" in due else 2
        pri_score = 0 if pri == "high" else 1 if pri == "medium" else 2
        return (due_score, pri_score)

    ordered = sorted(tasks, key=rank)
    lines = [f"## Study plan · {now()}", "", "Focus order (due soon + priority):"]
    for i, t in enumerate(ordered[:5], 1):
        course = find_course(board, t["course_id"]) if t.get("course_id") else None
        label = course["code"] if course else "General"
        lines.append(
            f"{i}. **[{label}]** {t['title']} _(due: {t.get('due', '?')}, {t.get('priority', 'medium')})_"
        )
    lines.append("")
    top = ordered[0]
    mats = materials_for(board, top.get("course_id"))
    if mats:
        lines.append(f"Start with notes: **{mats[0]['title']}** — ask me to explain or quiz you.")
    else:
        lines.append("No notes for the top task yet — add or edit notes on the board.")
    return "\n".join(lines)


def add_course(board: dict[str, Any], code: str, name: str) -> str:
    colors = ["#0ea5e9", "#6366f1", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6"]
    course = {
        "id": f"c-{uuid.uuid4().hex[:8]}",
        "code": code.strip(),
        "name": name.strip(),
        "color": colors[len(board["courses"]) % len(colors)],
    }
    board["courses"].append(course)
    return f"Added course **{course['code']}** — {course['name']}."


def add_task(
    board: dict[str, Any],
    title: str,
    course_ref: str | None = None,
    due: str = "sometime",
    priority: str = "medium",
) -> str:
    course = find_course(board, course_ref) if course_ref else None
    task = {
        "id": f"t-{uuid.uuid4().hex[:8]}",
        "course_id": course["id"] if course else None,
        "title": title.strip(),
        "due": (due or "sometime").strip(),
        "done": False,
        "priority": priority if priority in {"high", "medium", "low"} else "medium",
    }
    board["tasks"].append(task)
    label = course["code"] if course else "General"
    return f"Task added under **{label}**: {task['title']} (due {task['due']})."


def complete_task(board: dict[str, Any], title_ref: str) -> str:
    ref = title_ref.lower().strip()
    for t in board["tasks"]:
        if not t["done"] and (t["id"] == title_ref or ref in t["title"].lower()):
            t["done"] = True
            return f"Marked done: **{t['title']}**."
    return f"Couldn't find an open task matching “{title_ref}”."


def add_notes(
    board: dict[str, Any],
    title: str,
    content: str,
    course_ref: str | None = None,
) -> str:
    course = find_course(board, course_ref) if course_ref else None
    mat = {
        "id": f"m-{uuid.uuid4().hex[:8]}",
        "course_id": course["id"] if course else (board["courses"][0]["id"] if board["courses"] else None),
        "title": title.strip(),
        "content": content.strip(),
        "created_at": now(),
        "updated_at": now(),
    }
    board["materials"].append(mat)
    return f"Saved notes **{mat['title']}** ({len(mat['content'])} chars)."


def edit_notes(
    board: dict[str, Any],
    note_ref: str,
    new_title: str | None = None,
    content: str | None = None,
    append: bool = False,
) -> str:
    mat = find_material(board, note_ref)
    if not mat:
        return f"Couldn't find notes matching “{note_ref}”."
    if new_title:
        mat["title"] = new_title.strip()
    if content is not None:
        body = content.strip()
        mat["content"] = (mat["content"].rstrip() + "\n\n" + body) if append else body
    mat["updated_at"] = now()
    return f"Updated notes **{mat['title']}** (id={mat['id']}, {len(mat['content'])} chars)."


def retrieve_notes(board: dict[str, Any], query: str, k: int = 4) -> str:
    hits = retrieve(board, query, k=max(1, min(int(k or 4), 8)))
    if not hits:
        return "No notes on the board yet. Ask the student to paste lecture notes."
    return format_passages(hits)


def _extractive_explain(topic: str, notes: str, sources: str = "") -> str:
    if not notes.strip():
        return (
            f"I don't have notes about “{topic}” yet. "
            "Add or edit notes on the board, then ask again."
        )
    lines = [ln.strip() for ln in notes.splitlines() if ln.strip()]
    topic_toks = [t for t in re.split(r"[^a-z0-9]+", topic.lower()) if len(t) > 2]
    scored = []
    for ln in lines:
        low = ln.lower()
        score = sum(1 for t in topic_toks if t in low) if topic_toks else 0
        if score or topic.lower() in low:
            scored.append((score, ln))
    scored.sort(key=lambda x: -x[0])
    picks = [ln for _, ln in scored[:6]] or lines[:6]
    out = [f"## Explain: {topic}", f"_From your notes · {now()}_", ""]
    out.extend(f"- {p}" for p in picks)
    if sources:
        out.extend(["", sources])
    return "\n".join(out)


def _extractive_quiz(topic: str, notes: str, n: int = 3, sources: str = "") -> str:
    lines = [ln.strip(" -•\t") for ln in notes.splitlines() if len(ln.strip()) > 20]
    if not lines:
        return "No notes to quiz from. Add or edit notes first."
    topic_l = topic.lower()
    ranked = sorted(lines, key=lambda ln: (topic_l in ln.lower(), len(ln)), reverse=True)
    body = [f"## Quiz: {topic}", f"_{n} questions from your notes_", ""]
    for i, ln in enumerate(ranked[:n], 1):
        body.append(f"**Q{i}.** In your own words: what does this mean?\n“{ln[:140]}”")
        body.append("")
    if sources:
        body.append(sources)
    return "\n".join(body)


def _extractive_flashcards(notes: str, n: int = 6, sources: str = "") -> str:
    lines = [ln.strip(" -•\t") for ln in notes.splitlines() if ":" in ln or len(ln) > 25]
    if not lines:
        lines = [ln.strip() for ln in notes.splitlines() if ln.strip()][:n]
    cards = []
    for ln in lines[:n]:
        if ":" in ln:
            term, rest = ln.split(":", 1)
            cards.append((term.strip()[:60], rest.strip()[:200]))
        else:
            cards.append((ln[:40] + "…", ln[:200]))
    out = ["## Flashcards", ""]
    for i, (front, back) in enumerate(cards, 1):
        out.append(f"**{i}. {front}**")
        out.append(f"   → {back}")
        out.append("")
    if sources:
        out.append(sources)
    return "\n".join(out) if cards else "Need more notes to build flashcards."


def explain_topic(board: dict[str, Any], topic: str, course_ref: str | None = None) -> str:
    query = f"{course_ref or ''} {topic}".strip()
    hits = retrieve(board, query, k=4)
    notes = notes_from_hits(hits)
    return _extractive_explain(topic, notes, citation_line(hits))


def generate_quiz(board: dict[str, Any], topic: str, n: int = 3) -> str:
    hits = retrieve(board, topic, k=5)
    notes = notes_from_hits(hits)
    board["quiz_history"].append({"topic": topic, "at": now(), "provider": "tool"})
    return _extractive_quiz(topic, notes, n=max(1, min(int(n or 3), 8)), sources=citation_line(hits))


def generate_flashcards(board: dict[str, Any], topic: str | None = None) -> str:
    hits = retrieve(board, topic or "key terms", k=6)
    notes = notes_from_hits(hits)
    return _extractive_flashcards(notes, sources=citation_line(hits))


def dispatch(board: dict[str, Any], name: str, args: dict[str, Any]) -> str:
    """Run one named tool against the board. Mutating tools update `board` in place."""
    handlers: dict[str, Callable[..., str]] = {
        "retrieve_notes": lambda: retrieve_notes(board, args.get("query", ""), args.get("k", 4)),
        "list_board": lambda: list_board(board),
        "plan_study": lambda: plan_study(board),
        "explain_topic": lambda: explain_topic(board, args.get("topic", ""), args.get("course_ref")),
        "generate_quiz": lambda: generate_quiz(board, args.get("topic", "my notes"), args.get("n", 3)),
        "generate_flashcards": lambda: generate_flashcards(board, args.get("topic")),
        "add_task": lambda: add_task(
            board,
            args.get("title", ""),
            args.get("course_ref"),
            args.get("due", "sometime"),
            args.get("priority", "medium"),
        ),
        "complete_task": lambda: complete_task(board, args.get("title_ref", "")),
        "add_notes": lambda: add_notes(
            board, args.get("title", ""), args.get("content", ""), args.get("course_ref")
        ),
        "edit_notes": lambda: edit_notes(
            board,
            args.get("note_ref", ""),
            args.get("new_title"),
            args.get("content"),
            bool(args.get("append", False)),
        ),
        "add_course": lambda: add_course(board, args.get("code", ""), args.get("name", "")),
    }
    fn = handlers.get(name)
    if not fn:
        return json.dumps({"error": f"unknown tool: {name}"})
    try:
        return fn()
    except Exception as ex:  # noqa: BLE001 — surface tool errors to the model
        return f"Tool error ({name}): {ex}"


HELP = """I'm **StudyBoard** — your course dashboard tutor.

I can plan what to study, explain from your notes, quiz you, make flashcards,
and update your board (tasks and notes).

Try: what's on my board · plan tonight · explain a topic · quiz me · flashcards
"""
