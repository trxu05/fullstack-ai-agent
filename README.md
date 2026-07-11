# News Digest Agent

**Real purpose:** a personal briefing assistant for job-search / industry catch-up.
You tell it a topic; it **collects public news**, then returns an **AI or extractive recap**.

## 2026 stack (what recruiters scan for)

| Layer | Tech |
| --- | --- |
| Frontend | **Next.js 15**, **React 19**, **TypeScript**, **Tailwind CSS** |
| API gateway | **Java 17**, **Spring Boot** (sessions, validation, proxy) |
| Agent | **Python**, **FastAPI** (RSS collect + filter + recap tools) |

```
Next.js UI (:3000) → Java gateway (:8080) → FastAPI agent (:8001) → public RSS
```

## Commands it understands

- `digest AI chips` — collect + recap now  
- `watch topic cloud networking` — remember a beat  
- `digest` / `brief me` — recap the watched topic  

Offline extractive recap works without keys. Set `OPENAI_API_KEY` for LLM recap.

## Quick start

**Python 3.11–3.12** recommended for the agent.

```bash
# 1) Agent
cd python-agent
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --port 8001 --reload

# 2) Java gateway
cd java-api
mvn spring-boot:run

# 3) Next.js UI
cd web
npm install
npm run dev
# open http://localhost:3000
```

Optional: `NEXT_PUBLIC_API_BASE=http://127.0.0.1:8080`

## Interview angles

- Why a Java gateway in front of Python (sessions / future auth / rate limits)
- Tool loop: collect → filter → recap (not a single chat completion)
- React/Next vs vanilla HTML for product UI
- Failure modes: dead RSS feed, empty topic match, agent down → 502

## Repo layout

```
web/            Next.js + React + TS + Tailwind
java-api/       Spring Boot gateway
python-agent/   FastAPI news digest agent
frontend/       legacy static UI (optional)
```
