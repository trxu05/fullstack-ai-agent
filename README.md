# StudyBoard AI Agent

Personal **course dashboard** with a **GPT-5 agent** that plans, explains, quizzes,
and updates your board through **tool calls**, grounded in your courses, tasks,
and notes.

```
Next.js (:3000) → Java Spring Boot gateway (:8080) → FastAPI GPT-5 agent (:8001)
```

## Stack

| Layer | Tech |
| --- | --- |
| Dashboard UI | **Next.js 15**, **React 19**, **TypeScript**, **Tailwind CSS** |
| API gateway | **Java 17**, **Spring Boot** (sessions, board proxy, chat) |
| AI agent | **Python**, **FastAPI**, **GPT-5** function calling |

## Agent tools

| Tool | What it does |
| --- | --- |
| `plan_study` | Prioritize open tasks |
| `explain_topic` | Teach from your notes |
| `generate_quiz` / `generate_flashcards` | Check understanding from notes |
| `list_board` | Status snapshot |
| `add_task` / `complete_task` | Mutate tasks |
| `add_notes` / `edit_notes` | Add or edit notes on the live board |

Set `OPENAI_API_KEY` (optional `OPENAI_MODEL`, default **`gpt-5`**). Without a key,
the same tools run via an offline rules/extractive fallback. Board state persists
to **SQLite** (`studyboard.db`).

## Quick start

**Python 3.11–3.12** recommended.

```bash
# 1) Agent
cd python-agent
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export OPENAI_API_KEY=sk-...   # optional but enables GPT-5 tool calling
uvicorn main:app --port 8001 --reload

# 2) Java gateway
cd java-api
mvn spring-boot:run

# 3) Dashboard
cd web
npm install
npm run dev
# open http://localhost:3000
```

## Layout

```
web/            Next.js StudyBoard dashboard
java-api/       Spring Boot gateway
python-agent/
  main.py       FastAPI routes
  agent.py      GPT-5 tool-calling loop + rules fallback
  tools.py      Tool implementations + OpenAI schemas
  board.py      Session board + grounding context
  store.py      SQLite persistence
```
