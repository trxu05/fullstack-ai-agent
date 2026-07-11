# Full-Stack AI Agent Workbench

Java API gateway + Python tool-calling agent + JavaScript chat UI.

```
Browser (JS)  →  Java Spring Boot (:8080)  →  Python Agent (:8001)
                     sessions / proxy           tools + LLM loop
```

## Stack

| Layer | Tech | Role |
| --- | --- | --- |
| Frontend | JavaScript, HTML/CSS | Chat UI with tool-trace metadata |
| API | Java 17, Spring Boot | Session store, validation, proxy to agent |
| Agent | Python, FastAPI | Tool calling (calculator, time, memory) |

Runs **without an API key** via a mock LLM that still exercises the tool loop.
Set `OPENAI_API_KEY` to use a real model.

## Quick start

```bash
# Terminal 1 — Python agent
cd python-agent
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --port 8001 --reload

# Terminal 2 — Java API (also serves frontend/)
cd java-api
mvn spring-boot:run

# Open http://localhost:8080
```

## API

- `POST /api/sessions` — create session
- `POST /api/sessions/{id}/chat` — `{ "message": "..." }`
- `GET /api/sessions/{id}` — history

## Interview talking points

- Why a Java gateway in front of the Python agent (sessions, validation, future auth)
- Tool-calling loop vs plain chat completion
- Failure mode when the agent is down (502 from gateway)
- What you would add next: Redis session store, rate limits, eval harness
