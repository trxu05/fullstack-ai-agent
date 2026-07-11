"""StudyBoard FastAPI service — board CRUD + AI agent chat.

Architecture:
  Next.js dashboard → Java Spring Boot (:8080) → this FastAPI agent (:8001)

The agent uses OpenAI function calling to plan, explain, quiz, flashcards,
and mutate the live board (add tasks, complete work, add/edit notes).
Without OPENAI_API_KEY, an offline rules/extractive fallback runs the same tools.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from agent import run_chat
from board import board_for, board_snapshot, persist
from tools import add_course, add_notes, add_task, complete_task, edit_notes

app = FastAPI(title="StudyBoard Agent", version="4.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    session_id: str | None = None


class ToolTraceOut(BaseModel):
    name: str
    args: dict[str, Any]
    result: str


class ChatResponse(BaseModel):
    reply: str
    tools_used: list[ToolTraceOut]
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


class MaterialEdit(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    content: str | None = Field(default=None, max_length=50000)
    append: bool = False


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "studyboard-agent", "version": "4.0.0"}


@app.get("/board")
def get_board(session_id: str = "default") -> dict[str, Any]:
    _, board = board_for(session_id)
    return board_snapshot(board)


@app.post("/board/courses")
def api_add_course(body: CourseIn, session_id: str = "default") -> dict[str, Any]:
    sid, board = board_for(session_id)
    msg = add_course(board, body.code, body.name)
    if body.color:
        board["courses"][-1]["color"] = body.color
    persist(sid, board)
    return {"message": msg, "board": board_snapshot(board)}


@app.post("/board/tasks")
def api_add_task(body: TaskIn, session_id: str = "default") -> dict[str, Any]:
    sid, board = board_for(session_id)
    msg = add_task(board, body.title, body.course_id, body.due, body.priority)
    persist(sid, board)
    return {"message": msg, "board": board_snapshot(board)}


@app.post("/board/tasks/{task_id}/done")
def api_complete_task(task_id: str, session_id: str = "default") -> dict[str, Any]:
    sid, board = board_for(session_id)
    for t in board["tasks"]:
        if t["id"] == task_id:
            t["done"] = True
            persist(sid, board)
            return {"message": f"Marked done: {t['title']}", "board": board_snapshot(board)}
    raise HTTPException(404, "task not found")


@app.post("/board/materials")
def api_add_material(body: MaterialIn, session_id: str = "default") -> dict[str, Any]:
    sid, board = board_for(session_id)
    msg = add_notes(board, body.title, body.content, body.course_id)
    persist(sid, board)
    return {"message": msg, "board": board_snapshot(board)}


@app.put("/board/materials/{material_id}")
def api_edit_material(
    material_id: str, body: MaterialEdit, session_id: str = "default"
) -> dict[str, Any]:
    sid, board = board_for(session_id)
    msg = edit_notes(
        board,
        material_id,
        new_title=body.title,
        content=body.content,
        append=body.append,
    )
    if msg.startswith("Couldn't find"):
        raise HTTPException(404, msg)
    persist(sid, board)
    return {"message": msg, "board": board_snapshot(board)}


@app.post("/agent/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    sid, board = board_for(req.session_id)
    result = run_chat(sid, board, req.message)
    return ChatResponse(
        reply=result.reply,
        tools_used=[
            ToolTraceOut(name=t.name, args=t.args, result=t.result) for t in result.tools_used
        ],
        provider=result.provider,
    )
