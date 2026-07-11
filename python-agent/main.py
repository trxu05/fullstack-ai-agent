"""News Digest Agent — fetch headlines for a topic and produce an AI recap.

Real purpose: tell the agent what to cover (e.g. "AI chips", "Arista networking");
it pulls public RSS feeds, filters by topic, and returns a short briefing you
can use for job-search / industry catch-up.

Works offline with a built-in extractive recap. Set OPENAI_API_KEY for LLM recap.
Requires Python 3.11–3.12 recommended.
"""

from __future__ import annotations

import json
import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

app = FastAPI(title="News Digest Agent", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Topic preferences remembered across turns (short-term agent memory).
PREFERENCES: dict[str, str] = {}

# Public RSS sources (no API key). Enough for a real digest workflow.
FEEDS = [
    ("BBC Technology", "https://feeds.bbci.co.uk/news/technology/rss.xml"),
    ("HN Front Page", "https://hnrss.org/frontpage"),
    ("CNBC Top News", "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114"),
]


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    session_id: str | None = None


class ToolTrace(BaseModel):
    name: str
    args: dict[str, Any]
    result: str


class ChatResponse(BaseModel):
    reply: str
    tools_used: list[ToolTrace]
    provider: str


def _http_get(url: str, timeout: float = 8.0) -> bytes:
    req = Request(url, headers={"User-Agent": "NewsDigestAgent/2.0 (+github.com/trxu05)"})
    with urlopen(req, timeout=timeout) as resp:  # noqa: S310 — intentional outbound fetch
        return resp.read()


def fetch_rss_items(limit_per_feed: int = 8) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for source, url in FEEDS:
        try:
            raw = _http_get(url)
            root = ET.fromstring(raw)
            # RSS 2.0
            for item in root.findall(".//item")[:limit_per_feed]:
                title = (item.findtext("title") or "").strip()
                link = (item.findtext("link") or "").strip()
                desc = re.sub(r"<[^>]+>", "", item.findtext("description") or "").strip()
                pub = (item.findtext("pubDate") or "").strip()
                if title:
                    items.append(
                        {
                            "source": source,
                            "title": title,
                            "link": link,
                            "summary": desc[:280],
                            "published": pub,
                        }
                    )
        except (URLError, ET.ParseError, TimeoutError, OSError) as exc:
            items.append(
                {
                    "source": source,
                    "title": f"(feed unavailable: {source})",
                    "link": "",
                    "summary": str(exc)[:120],
                    "published": "",
                }
            )
    return items


def filter_by_topic(items: list[dict[str, str]], topic: str) -> list[dict[str, str]]:
    tokens = [t for t in re.split(r"[^a-z0-9]+", topic.lower()) if len(t) > 2]
    if not tokens:
        return items[:12]
    scored: list[tuple[int, dict[str, str]]] = []
    for it in items:
        blob = f"{it['title']} {it['summary']}".lower()
        score = sum(1 for t in tokens if t in blob)
        if score:
            scored.append((score, it))
    scored.sort(key=lambda x: -x[0])
    return [it for _, it in scored[:10]] or items[:8]


def extractive_recap(topic: str, items: list[dict[str, str]]) -> str:
    if not items:
        return f"No headlines matched “{topic}”. Try a broader topic (e.g. AI, chips, markets)."
    lines = [f"## Briefing: {topic}", f"_Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}_", ""]
    lines.append(f"Pulled {len(items)} relevant headlines from public RSS feeds:")
    for i, it in enumerate(items, 1):
        lines.append(f"{i}. **{it['title']}** ({it['source']})")
        if it["summary"]:
            lines.append(f"   - {it['summary']}")
        if it["link"]:
            lines.append(f"   - {it['link']}")
    lines.append("")
    lines.append(
        "Takeaway: skim the top 3 links above for depth; ask me to “recap #2” or "
        "“watch topic X” to refine the next digest."
    )
    return "\n".join(lines)


def openai_recap(topic: str, items: list[dict[str, str]]) -> str | None:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key or not items:
        return None
    try:
        import httpx

        bullet = "\n".join(f"- ({it['source']}) {it['title']}: {it['summary']}" for it in items[:8])
        payload = {
            "model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a concise industry briefing assistant for a software engineer. "
                        "Write a short recap (6–10 bullets + 2-sentence takeaway). No fluff."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Topic: {topic}\nHeadlines:\n{bullet}",
                },
            ],
            "temperature": 0.3,
        }
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json=payload,
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception:
        return None


def tool_collect_and_recap(topic: str) -> tuple[str, str]:
    items = filter_by_topic(fetch_rss_items(), topic)
    llm = openai_recap(topic, items)
    if llm:
        header = f"## AI recap: {topic}\n_Sources: {', '.join(sorted({i['source'] for i in items}))}_\n\n"
        return header + llm, "openai"
    return extractive_recap(topic, items), "extractive"


def tool_watch_topic(topic: str) -> str:
    PREFERENCES["watch_topic"] = topic
    return f"Watching topic “{topic}”. Say “digest” or “brief me” anytime."


def tool_list_watch() -> str:
    t = PREFERENCES.get("watch_topic")
    return f"Currently watching: {t}" if t else "No watched topic yet. Try: watch topic AI infrastructure"


def parse_intent(message: str) -> tuple[str, dict[str, Any]]:
    lower = message.lower().strip()

    m = re.search(r"watch(?:ing)?\s+topic\s+(.+)$", message, re.I)
    if m:
        return "watch_topic", {"topic": m.group(1).strip()}

    if lower in {"digest", "brief me", "briefing", "what's new", "whats new"}:
        topic = PREFERENCES.get("watch_topic", "technology")
        return "collect_and_recap", {"topic": topic}

    m = re.search(
        r"(?:digest|brief|recap|summarize|collect|news(?:\s+about)?|headlines(?:\s+on)?)\s+(.+)$",
        message,
        re.I,
    )
    if m:
        return "collect_and_recap", {"topic": m.group(1).strip()}

    if "watch" in lower and "topic" in lower:
        return "list_watch", {}

    # Default: treat whole message as a topic request if it looks like keywords.
    if len(message.split()) <= 6 and not message.endswith("?"):
        return "collect_and_recap", {"topic": message.strip()}

    return "help", {}


HELP = (
    "I'm your **News Digest Agent**. Tell me what to cover and I'll collect "
    "public headlines and write a recap.\n\n"
    "Examples:\n"
    "- `digest AI chips`\n"
    "- `brief networking and cloud`\n"
    "- `watch topic semiconductor` then later `digest`\n"
    "- `what's new` (uses your watched topic)\n"
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "news-digest-agent"}


@app.post("/agent/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    intent, args = parse_intent(req.message)
    traces: list[ToolTrace] = []
    provider = "rules"

    if intent == "help":
        return ChatResponse(reply=HELP, tools_used=[], provider=provider)

    if intent == "watch_topic":
        result = tool_watch_topic(str(args["topic"]))
        traces.append(ToolTrace(name="watch_topic", args=args, result=result))
        return ChatResponse(reply=result, tools_used=traces, provider=provider)

    if intent == "list_watch":
        result = tool_list_watch()
        traces.append(ToolTrace(name="list_watch", args={}, result=result))
        return ChatResponse(reply=result, tools_used=traces, provider=provider)

    # collect_and_recap
    topic = str(args.get("topic") or PREFERENCES.get("watch_topic") or "technology")
    reply, provider = tool_collect_and_recap(topic)
    traces.append(
        ToolTrace(
            name="collect_and_recap",
            args={"topic": topic},
            result=f"digest generated ({provider})",
        )
    )
    return ChatResponse(reply=reply, tools_used=traces, provider=provider)
