"""Session-scoped study board: courses, tasks, and notes."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import store


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def new_board() -> dict[str, Any]:
    return {
        "courses": [],
        "tasks": [],
        "materials": [],
        "quiz_history": [],
    }


BOARDS: dict[str, dict[str, Any]] = {}


def board_for(session_id: str | None) -> tuple[str, dict[str, Any]]:
    sid = session_id or "default"
    if sid not in BOARDS:
        loaded = store.load_board(sid)
        if loaded is not None:
            BOARDS[sid] = loaded
        else:
            BOARDS[sid] = new_board()
            seed(BOARDS[sid])
            store.save_board(sid, BOARDS[sid])
    return sid, BOARDS[sid]


def persist(sid: str, board: dict[str, Any]) -> None:
    store.save_board(sid, board)


def seed(board: dict[str, Any]) -> None:
    if board["courses"]:
        return
    c1 = {"id": "c-cs101", "code": "CS 101", "name": "Intro to CS", "color": "#0ea5e9"}
    c2 = {"id": "c-algo", "code": "CS 201", "name": "Algorithms", "color": "#6366f1"}
    board["courses"].extend([c1, c2])
    board["tasks"].extend(
        [
            {
                "id": "t1",
                "course_id": c1["id"],
                "title": "Review lecture notes",
                "due": "this week",
                "done": False,
                "priority": "high",
            },
            {
                "id": "t2",
                "course_id": c2["id"],
                "title": "Practice recursion problems",
                "due": "this week",
                "done": False,
                "priority": "medium",
            },
            {
                "id": "t3",
                "course_id": c1["id"],
                "title": "Quiz myself on key terms",
                "due": "tonight",
                "done": False,
                "priority": "high",
            },
        ]
    )
    board["materials"].append(
        {
            "id": "m1",
            "course_id": c1["id"],
            "title": "Course overview",
            "content": (
                "Variables store values. Functions group reusable steps.\n"
                "Conditionals branch on true/false. Loops repeat work.\n"
                "Arrays hold ordered collections. Recursion solves a problem via smaller copies.\n"
                "Tip: write a small example before coding the full solution."
            ),
            "created_at": now(),
            "updated_at": now(),
        }
    )


def find_course(board: dict[str, Any], ref: str) -> dict[str, Any] | None:
    ref_l = ref.lower().strip()
    for c in board["courses"]:
        if c["id"] == ref or c["code"].lower() == ref_l or ref_l in c["name"].lower():
            return c
    return None


def find_material(board: dict[str, Any], ref: str) -> dict[str, Any] | None:
    ref_l = ref.lower().strip()
    for m in board["materials"]:
        if m["id"] == ref or m["title"].lower() == ref_l or ref_l in m["title"].lower():
            return m
    return None


def materials_for(board: dict[str, Any], course_id: str | None = None) -> list[dict[str, Any]]:
    mats = board["materials"]
    if course_id:
        mats = [m for m in mats if m.get("course_id") == course_id]
    return mats


def open_tasks(board: dict[str, Any]) -> list[dict[str, Any]]:
    return [t for t in board["tasks"] if not t.get("done")]


def notes_blob(board: dict[str, Any], course_id: str | None = None) -> str:
    mats = materials_for(board, course_id)
    if not mats:
        return ""
    return "\n\n".join(f"### {m['title']}\n{m['content']}" for m in mats)


def board_snapshot(board: dict[str, Any]) -> dict[str, Any]:
    return {
        "courses": board["courses"],
        "tasks": board["tasks"],
        "materials": [
            {
                **m,
                "preview": m["content"][:160] + ("…" if len(m["content"]) > 160 else ""),
            }
            for m in board["materials"]
        ],
        "stats": {
            "courses": len(board["courses"]),
            "open_tasks": len(open_tasks(board)),
            "materials": len(board["materials"]),
            "quizzes_taken": len(board["quiz_history"]),
        },
    }


def board_context_for_llm(board: dict[str, Any]) -> str:
    """Compact board index — full note bodies are fetched via retrieve_notes."""
    lines = ["## Live study board (index only)", ""]
    lines.append("Courses:")
    for c in board["courses"]:
        lines.append(f"- id={c['id']} code={c['code']} name={c['name']}")
    if not board["courses"]:
        lines.append("- (none)")
    lines.append("")
    lines.append("Open tasks:")
    for t in open_tasks(board):
        lines.append(
            f"- id={t['id']} title={t['title']} due={t.get('due')} "
            f"priority={t.get('priority')} course_id={t.get('course_id')}"
        )
    if not open_tasks(board):
        lines.append("- (none)")
    lines.append("")
    lines.append("Notes (titles only — call retrieve_notes for content):")
    for m in board["materials"]:
        preview = (m.get("content") or "")[:80].replace("\n", " ")
        lines.append(f"- id={m['id']} title={m['title']} preview={preview}")
    if not board["materials"]:
        lines.append("(no notes yet)")
    return "\n".join(lines)
