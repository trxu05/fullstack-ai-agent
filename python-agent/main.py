"""StudyBoard agent — personal course dashboard + AI tutor.

Keep courses, tasks, and notes in one board. The agent can plan what to study,
explain from your materials, quiz you, and make flashcards.

Works offline with extractive/rule helpers. Set OPENAI_API_KEY for stronger tutoring.
Python 3.11–3.12 recommended.
"""

from __future__ import annotations

import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

app = FastAPI(title="StudyBoard Agent", version="3.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# In-memory boards (keyed by session_id)
# ---------------------------------------------------------------------------


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _new_board() -> dict[str, Any]:
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
        BOARDS[sid] = _new_board()
        _seed(BOARDS[sid])
    return sid, BOARDS[sid]


def _seed(board: dict[str, Any]) -> None:
    """Light demo content so the dashboard isn't empty on first open."""
    if board["courses"]:
        return
    c1 = {"id": "c-ecs132", "code": "ECS 132", "name": "Prob & Stat for CS", "color": "#0ea5e9"}
    c2 = {"id": "c-ecs122b", "code": "ECS 122B", "name": "Algorithm Design", "color": "#6366f1"}
    board["courses"].extend([c1, c2])
    board["tasks"].extend(
        [
            {
                "id": "t1",
                "course_id": c1["id"],
                "title": "Review Bayes theorem notes",
                "due": "this week",
                "done": False,
                "priority": "high",
            },
            {
                "id": "t2",
                "course_id": c2["id"],
                "title": "Practice DP on trees",
                "due": "this week",
                "done": False,
                "priority": "medium",
            },
            {
                "id": "t3",
                "course_id": c1["id"],
                "title": "Quiz myself on distributions",
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
            "title": "Bayes & conditional probability",
            "content": (
                "Bayes theorem: P(A|B) = P(B|A) P(A) / P(B).\n"
                "Prior P(A), likelihood P(B|A), posterior P(A|B).\n"
                "Independent events: P(A and B) = P(A) P(B).\n"
                "Law of total probability: sum over partitions of the sample space.\n"
                "Common trap: confusing P(A|B) with P(B|A)."
            ),
            "created_at": _now(),
        }
    )


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    session_id: str | None = None


class ToolTrace(BaseModel):
    name: str
    args: dict[str, Any]
    result: str


class ChatResponse(BaseModel):
    reply: str
    tools_used: list[ToolTrace]
    provider: str


class CourseIn(BaseModel):
    code: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=120)
    color: str | None = None


class TaskIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    course_id: str | None = None
    due: str = "sometime"
    priority: str = "medium"


class MaterialIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=50000)
    course_id: str | None = None


# ---------------------------------------------------------------------------
# Board helpers
# ---------------------------------------------------------------------------


def find_course(board: dict[str, Any], ref: str) -> dict[str, Any] | None:
    ref_l = ref.lower().strip()
    for c in board["courses"]:
        if c["id"] == ref or c["code"].lower() == ref_l or ref_l in c["name"].lower():
            return c
    return None


def materials_for(board: dict[str, Any], course_id: str | None = None) -> list[dict[str, Any]]:
    mats = board["materials"]
    if course_id:
        mats = [m for m in mats if m.get("course_id") == course_id]
    return mats


def open_tasks(board: dict[str, Any]) -> list[dict[str, Any]]:
    return [t for t in board["tasks"] if not t.get("done")]


def board_snapshot(board: dict[str, Any]) -> dict[str, Any]:
    return {
        "courses": board["courses"],
        "tasks": board["tasks"],
        "materials": [
            {**m, "preview": m["content"][:160] + ("…" if len(m["content"]) > 160 else "")}
            for m in board["materials"]
        ],
        "stats": {
            "courses": len(board["courses"]),
            "open_tasks": len(open_tasks(board)),
            "materials": len(board["materials"]),
            "quizzes_taken": len(board["quiz_history"]),
        },
    }


# ---------------------------------------------------------------------------
# LLM + extractive helpers
# ---------------------------------------------------------------------------


def openai_chat(system: str, user: str) -> str | None:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None
    try:
        import httpx

        payload = {
            "model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.3,
        }
        with httpx.Client(timeout=45.0) as client:
            resp = client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json=payload,
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception:
        return None


def notes_blob(board: dict[str, Any], course_id: str | None = None) -> str:
    mats = materials_for(board, course_id)
    if not mats:
        return ""
    parts = []
    for m in mats:
        parts.append(f"### {m['title']}\n{m['content']}")
    return "\n\n".join(parts)


def extractive_explain(topic: str, notes: str) -> str:
    if not notes.strip():
        return (
            f"I don't have notes about “{topic}” yet. "
            "Add material on the board (or say `add notes: ...`), then ask again."
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
    out = [f"## Explain: {topic}", f"_From your notes · {_now()}_", ""]
    out.extend(f"- {p}" for p in picks)
    out.append("")
    out.append("Tip: ask `quiz me on this` to check yourself.")
    return "\n".join(out)


def extractive_quiz(topic: str, notes: str, n: int = 3) -> tuple[str, list[dict[str, str]]]:
    lines = [ln.strip(" -•\t") for ln in notes.splitlines() if len(ln.strip()) > 20]
    if not lines:
        return "No notes to quiz from. Add some material first.", []
    topic_l = topic.lower()
    ranked = sorted(
        lines,
        key=lambda ln: (topic_l in ln.lower(), len(ln)),
        reverse=True,
    )
    questions: list[dict[str, str]] = []
    for i, ln in enumerate(ranked[:n], 1):
        # Turn a fact line into a fill-in style prompt
        q = f"In your own words: what does this mean?\n“{ln[:140]}”"
        questions.append({"id": f"q{i}", "question": q, "answer": ln})
    body = [f"## Quiz: {topic}", f"_{n} questions from your notes_", ""]
    for i, q in enumerate(questions, 1):
        body.append(f"**Q{i}.** {q['question']}")
        body.append("")
    body.append("Reply like `answer 1: ...` or ask me to `grade` after you answer in chat.")
    body.append("(Offline mode: answers are the source lines — compare yourself, or use OpenAI for auto-grade.)")
    return "\n".join(body), questions


def extractive_flashcards(notes: str, n: int = 6) -> str:
    lines = [ln.strip(" -•\t") for ln in notes.splitlines() if ":" in ln or "—" in ln or len(ln) > 25]
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
    return "\n".join(out) if cards else "Need more notes to build flashcards."


def plan_tonight(board: dict[str, Any]) -> str:
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
    lines = [f"## Study plan · {_now()}", ""]
    lines.append("Focus order (due soon + priority):")
    for i, t in enumerate(ordered[:5], 1):
        course = find_course(board, t["course_id"]) if t.get("course_id") else None
        label = course["code"] if course else "General"
        lines.append(f"{i}. **[{label}]** {t['title']} _(due: {t.get('due', '?')}, {t.get('priority', 'medium')})_")
    lines.append("")
    # Suggest a material if any
    top = ordered[0]
    mats = materials_for(board, top.get("course_id"))
    if mats:
        lines.append(f"Start with notes: **{mats[0]['title']}** — say `explain {mats[0]['title']}` or `quiz me`.")
    else:
        lines.append("No notes for the top task yet — paste material with `add notes titled X: ...`")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


def tool_list_board(board: dict[str, Any]) -> str:
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
        lines.append(f"- {m['title']}")
    if not board["materials"]:
        lines.append("- (none)")
    return "\n".join(lines)


def tool_add_course(board: dict[str, Any], code: str, name: str) -> str:
    colors = ["#0ea5e9", "#6366f1", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6"]
    course = {
        "id": f"c-{uuid.uuid4().hex[:8]}",
        "code": code.strip(),
        "name": name.strip(),
        "color": colors[len(board["courses"]) % len(colors)],
    }
    board["courses"].append(course)
    return f"Added course **{course['code']}** — {course['name']}."


def tool_add_task(
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
        "due": due.strip() or "sometime",
        "done": False,
        "priority": priority if priority in {"high", "medium", "low"} else "medium",
    }
    board["tasks"].append(task)
    label = course["code"] if course else "General"
    return f"Task added under **{label}**: {task['title']} (due {task['due']})."


def tool_complete_task(board: dict[str, Any], title_ref: str) -> str:
    ref = title_ref.lower().strip()
    for t in board["tasks"]:
        if not t["done"] and (t["id"] == title_ref or ref in t["title"].lower()):
            t["done"] = True
            return f"Marked done: **{t['title']}**."
    return f"Couldn't find an open task matching “{title_ref}”."


def tool_add_material(
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
        "created_at": _now(),
    }
    board["materials"].append(mat)
    return f"Saved notes **{mat['title']}** ({len(mat['content'])} chars)."


def tool_explain(board: dict[str, Any], topic: str, course_ref: str | None = None) -> tuple[str, str]:
    course = find_course(board, course_ref) if course_ref else None
    notes = notes_blob(board, course["id"] if course else None)
    if not notes:
        notes = notes_blob(board)
    system = (
        "You are a friendly study tutor. Explain using ONLY the student's notes when possible. "
        "Be clear and concise. If notes are thin, say what is missing."
    )
    user = f"Topic: {topic}\n\nStudent notes:\n{notes[:12000] or '(no notes yet)'}"
    llm = openai_chat(system, user)
    if llm:
        return f"## Explain: {topic}\n\n{llm}", "openai"
    return extractive_explain(topic, notes), "extractive"


def tool_quiz(board: dict[str, Any], topic: str, n: int = 3) -> tuple[str, str]:
    notes = notes_blob(board)
    system = (
        "Create a short quiz from the student's notes. "
        f"Return exactly {n} questions with answers clearly marked as ANSWER: ..."
    )
    user = f"Topic: {topic}\n\nNotes:\n{notes[:12000] or '(empty)'}"
    llm = openai_chat(system, user)
    if llm:
        board["quiz_history"].append({"topic": topic, "at": _now(), "provider": "openai"})
        return f"## Quiz: {topic}\n\n{llm}\n\nWhen ready, tell me your answers and ask me to grade.", "openai"
    text, _qs = extractive_quiz(topic, notes, n=n)
    board["quiz_history"].append({"topic": topic, "at": _now(), "provider": "extractive"})
    return text, "extractive"


def tool_flashcards(board: dict[str, Any], topic: str | None = None) -> tuple[str, str]:
    notes = notes_blob(board)
    if topic:
        # Prefer lines matching topic
        filtered = "\n".join(
            ln for ln in notes.splitlines() if topic.lower() in ln.lower()
        ) or notes
    else:
        filtered = notes
    system = "Make up to 6 flashcards (term → definition) from the notes. Short and study-friendly."
    llm = openai_chat(system, f"Notes:\n{filtered[:12000]}")
    if llm:
        return f"## Flashcards\n\n{llm}", "openai"
    return extractive_flashcards(filtered), "extractive"


HELP = """I'm **StudyBoard** — your course dashboard tutor.

I know your courses, tasks, and notes on this board.

**Try:**
- `what's on my board`
- `plan tonight` — what to study next
- `explain Bayes theorem`
- `quiz me on probability`
- `flashcards`
- `add task: finish problem set (ECS 132) due tonight`
- `add notes titled Heap invariants: ...`
- `done: Review Bayes`

Or use the dashboard buttons to add courses / tasks / notes, then chat with me.
"""


def parse_intent(message: str) -> tuple[str, dict[str, Any]]:
    raw = message.strip()
    lower = raw.lower()

    if lower in {"help", "?", "hi", "hello"}:
        return "help", {}

    if any(p in lower for p in ("what's on my board", "whats on my board", "show board", "list board", "status")):
        return "list_board", {}

    if any(p in lower for p in ("plan tonight", "what should i study", "study plan", "what next")):
        return "plan_tonight", {}

    m = re.match(r"add\s+course\s+([A-Za-z]{2,6}\s*\d{1,3}[A-Za-z]?)\s*[—:\-]\s*(.+)$", raw, re.I)
    if m:
        return "add_course", {"code": m.group(1).strip(), "name": m.group(2).strip()}

    m = re.match(r"add\s+course\s+(.+)$", raw, re.I)
    if m:
        parts = re.split(r"[—:\-]", m.group(1), maxsplit=1)
        if len(parts) == 2:
            return "add_course", {"code": parts[0].strip(), "name": parts[1].strip()}
        return "add_course", {"code": parts[0].strip()[:16], "name": parts[0].strip()}

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
        if "high priority" in body.lower():
            priority = "high"
            body = re.sub(r"high\s+priority", "", body, flags=re.I).strip(" ,.-")
        return "add_task", {"title": body, "course_ref": course_ref, "due": due, "priority": priority}

    m = re.match(r"done:\s*(.+)$", raw, re.I) or re.match(r"complete\s+task\s+(.+)$", raw, re.I)
    if m:
        return "complete_task", {"title_ref": m.group(1).strip()}

    m = re.match(r"add\s+notes?\s+titled\s+([^:]+):\s*(.+)$", raw, re.I | re.S)
    if m:
        return "add_material", {"title": m.group(1).strip(), "content": m.group(2).strip()}

    m = re.match(r"add\s+notes?\s*:\s*(.+)$", raw, re.I | re.S)
    if m:
        content = m.group(1).strip()
        title = content.split("\n", 1)[0][:60]
        return "add_material", {"title": title, "content": content}

    m = re.match(r"explain\s+(.+)$", raw, re.I)
    if m:
        return "explain", {"topic": m.group(1).strip()}

    m = re.match(r"(?:quiz\s+me(?:\s+on)?|quiz)\s+(.+)$", raw, re.I)
    if m:
        return "quiz", {"topic": m.group(1).strip()}
    if lower in {"quiz me", "quiz"}:
        return "quiz", {"topic": "my notes"}

    if lower.startswith("flashcard"):
        rest = raw.split(None, 1)
        topic = rest[1] if len(rest) > 1 else None
        return "flashcards", {"topic": topic}

    # Default: treat as explain/ask about notes
    if len(raw) < 200:
        return "explain", {"topic": raw}

    return "help", {}


# ---------------------------------------------------------------------------
# HTTP API
# ---------------------------------------------------------------------------


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "studyboard-agent"}


@app.get("/board")
def get_board(session_id: str = "default") -> dict[str, Any]:
    _, board = board_for(session_id)
    return board_snapshot(board)


@app.post("/board/courses")
def api_add_course(body: CourseIn, session_id: str = "default") -> dict[str, Any]:
    _, board = board_for(session_id)
    msg = tool_add_course(board, body.code, body.name)
    if body.color:
        board["courses"][-1]["color"] = body.color
    return {"message": msg, "board": board_snapshot(board)}


@app.post("/board/tasks")
def api_add_task(body: TaskIn, session_id: str = "default") -> dict[str, Any]:
    _, board = board_for(session_id)
    msg = tool_add_task(board, body.title, body.course_id, body.due, body.priority)
    return {"message": msg, "board": board_snapshot(board)}


@app.post("/board/tasks/{task_id}/done")
def api_complete_task(task_id: str, session_id: str = "default") -> dict[str, Any]:
    _, board = board_for(session_id)
    for t in board["tasks"]:
        if t["id"] == task_id:
            t["done"] = True
            return {"message": f"Marked done: {t['title']}", "board": board_snapshot(board)}
    raise HTTPException(404, "task not found")


@app.post("/board/materials")
def api_add_material(body: MaterialIn, session_id: str = "default") -> dict[str, Any]:
    _, board = board_for(session_id)
    msg = tool_add_material(board, body.title, body.content, body.course_id)
    return {"message": msg, "board": board_snapshot(board)}


@app.post("/agent/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    sid, board = board_for(req.session_id)
    intent, args = parse_intent(req.message)
    traces: list[ToolTrace] = []
    provider = "rules"

    def trace(name: str, result: str, a: dict[str, Any] | None = None) -> None:
        traces.append(ToolTrace(name=name, args=a or {}, result=result[:500]))

    if intent == "help":
        return ChatResponse(reply=HELP, tools_used=[], provider=provider)

    if intent == "list_board":
        result = tool_list_board(board)
        trace("list_board", result)
        return ChatResponse(reply=result, tools_used=traces, provider=provider)

    if intent == "plan_tonight":
        result = plan_tonight(board)
        trace("plan_tonight", result)
        return ChatResponse(reply=result, tools_used=traces, provider=provider)

    if intent == "add_course":
        result = tool_add_course(board, args["code"], args["name"])
        trace("add_course", result, args)
        return ChatResponse(reply=result, tools_used=traces, provider=provider)

    if intent == "add_task":
        result = tool_add_task(
            board,
            args["title"],
            args.get("course_ref"),
            args.get("due", "sometime"),
            args.get("priority", "medium"),
        )
        trace("add_task", result, args)
        return ChatResponse(reply=result, tools_used=traces, provider=provider)

    if intent == "complete_task":
        result = tool_complete_task(board, args["title_ref"])
        trace("complete_task", result, args)
        return ChatResponse(reply=result, tools_used=traces, provider=provider)

    if intent == "add_material":
        result = tool_add_material(board, args["title"], args["content"])
        trace("add_material", result, {"title": args["title"]})
        return ChatResponse(reply=result, tools_used=traces, provider=provider)

    if intent == "explain":
        reply, provider = tool_explain(board, args["topic"])
        trace("explain", f"explained ({provider})", args)
        return ChatResponse(reply=reply, tools_used=traces, provider=provider)

    if intent == "quiz":
        reply, provider = tool_quiz(board, args.get("topic") or "my notes")
        trace("quiz", f"quiz generated ({provider})", args)
        return ChatResponse(reply=reply, tools_used=traces, provider=provider)

    if intent == "flashcards":
        reply, provider = tool_flashcards(board, args.get("topic"))
        trace("flashcards", f"cards ({provider})", args)
        return ChatResponse(reply=reply, tools_used=traces, provider=provider)

    return ChatResponse(reply=HELP, tools_used=[], provider=provider)
