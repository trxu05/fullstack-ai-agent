# StudyBoard

A study-planning web app: manage courses, tasks, and notes in one dashboard,
with an AI tutor that plans, explains, quizzes, and updates the board from your
own materials.

```
Next.js (:3000) → Spring Boot gateway (:8080) → FastAPI agent (:8001)
```

## Stack

| Layer | Tech |
| --- | --- |
| Dashboard | Next.js, React, TypeScript |
| API gateway | Java, Spring Boot |
| AI agent | Python, FastAPI, OpenAI tool calling |
| Storage | SQLite |

## What it does

- Board for courses, tasks, and notes
- Tutor tools: study plan, explain, quiz, flashcards, add/edit notes, add/complete tasks
- Works without an API key via a rules-based fallback

## Quick start

Python 3.11–3.12 recommended.

```bash
# 1) Agent
cd python-agent
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export OPENAI_API_KEY=sk-...   # optional
uvicorn main:app --port 8001 --reload

# 2) Gateway
cd java-api
mvn spring-boot:run

# 3) Dashboard
cd web
npm install
npm run dev
# open http://localhost:3000
```

Optional: `OPENAI_MODEL` (default `gpt-5`), `NEXT_PUBLIC_API_BASE=http://127.0.0.1:8080`
