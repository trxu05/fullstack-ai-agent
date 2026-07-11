# StudyBoard AI Agent

Personal **course dashboard** + an **AI agent** that can plan, explain, quiz,
and update your board using **tool calls** grounded in *your* courses, tasks,
and notes.

Ask: *what should I study tonight?* / *explain Bayes* / *quiz me* / *add task: …*

## Stack

| Layer | Tech |
| --- | --- |
| Dashboard UI | **Next.js 15**, **React 19**, **TypeScript**, **Tailwind CSS** |
| API gateway | **Java 17**, **Spring Boot** (sessions, board proxy, chat) |
| AI agent | **Python**, **FastAPI** (board store + tutor tools) |

```
Next.js (:3000) → Java gateway (:8080) → FastAPI agent (:8001)
```

## Agent tools

| Tool | What it does |
| --- | --- |
| `plan tonight` | Prioritize open tasks |
| `what's on my board` | Status snapshot |
| `explain …` | Teach from **your** notes |
| `quiz me` / `flashcards` | Check understanding from notes |
| `add task` / `add notes` / `done` | Mutate board state |

Offline **extractive** mode works without an API key. Set `OPENAI_API_KEY`
for stronger tutoring. Board state can persist via **SQLite**.

## Quick start

**Python 3.11–3.12** recommended.

```bash
# 1) Agent
cd python-agent
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
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

Optional: `NEXT_PUBLIC_API_BASE=http://127.0.0.1:8080`

## Interview angles

- Why **dashboard + agent**, not chat-only (state lives on the board)
- Tool loop: plan / explain / quiz grounded in user materials
- Java gateway for sessions + board CRUD in front of Python
- Fallback when no API key (extractive explain/quiz)
- Failure modes: empty notes, agent down → 502, weak topic match

## Repo layout

```
web/            Next.js StudyBoard dashboard
java-api/       Spring Boot gateway
python-agent/   FastAPI board + AI agent tools
frontend/       legacy static UI (unused)
```

## GitHub

https://github.com/trxu05/fullstack-ai-agent
