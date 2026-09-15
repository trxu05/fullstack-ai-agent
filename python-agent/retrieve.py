"""Keyword retrieval over lecture notes (no vector DB).

Chunks notes into paragraphs, scores overlap with the query, and returns
top-k passages with note titles so the agent can cite sources.
"""

from __future__ import annotations

import math
import re
from typing import Any

_STOP = {
    "the",
    "and",
    "for",
    "are",
    "but",
    "not",
    "you",
    "all",
    "can",
    "her",
    "was",
    "one",
    "our",
    "out",
    "has",
    "have",
    "this",
    "that",
    "with",
    "from",
    "your",
    "what",
    "when",
    "which",
    "about",
    "into",
    "them",
    "then",
    "than",
    "some",
    "will",
    "just",
    "like",
    "over",
    "also",
    "more",
    "notes",
    "note",
    "explain",
    "quiz",
    "flashcards",
    "study",
}


def tokenize(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]{3,}", text.lower()) if t not in _STOP]


def chunk_notes(board: dict[str, Any]) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    for m in board.get("materials") or []:
        body = (m.get("content") or "").strip()
        parts = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
        if not parts and body:
            parts = [body]
        for i, para in enumerate(parts):
            # Split long paragraphs so scoring stays local.
            pieces = [para]
            if len(para) > 600:
                sents = re.split(r"(?<=[.!?])\s+", para)
                pieces = []
                buf = ""
                for s in sents:
                    if len(buf) + len(s) > 400 and buf:
                        pieces.append(buf.strip())
                        buf = s
                    else:
                        buf = f"{buf} {s}".strip()
                if buf:
                    pieces.append(buf)
            for j, text in enumerate(pieces):
                if len(text) < 12:
                    continue
                chunks.append(
                    {
                        "note_id": m["id"],
                        "title": m.get("title") or "Untitled",
                        "course_id": m.get("course_id"),
                        "index": i,
                        "part": j,
                        "text": text[:2000],
                    }
                )
    return chunks


def _score(query_toks: list[str], text: str, title: str) -> float:
    if not query_toks:
        return 0.0
    doc = tokenize(f"{title} {text}")
    if not doc:
        return 0.0
    hits = sum(doc.count(t) for t in query_toks)
    if hits == 0:
        return 0.0
    title_l = title.lower()
    boost = 1.4 if any(t in title_l for t in query_toks) else 1.0
    return boost * hits / (1.0 + math.log(1.0 + len(doc)))


def retrieve(board: dict[str, Any], query: str, k: int = 4) -> list[dict[str, Any]]:
    q = tokenize(query) or tokenize(query.lower())
    scored: list[tuple[float, dict[str, Any]]] = []
    for ch in chunk_notes(board):
        s = _score(q, ch["text"], ch["title"])
        if s <= 0 and q:
            continue
        scored.append((s, ch))
    if not scored:
        # Fall back to first chunks so explain/quiz still have material.
        return chunk_notes(board)[:k]
    scored.sort(key=lambda x: -x[0])
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    for s, ch in scored:
        key = (ch["note_id"], ch["index"])
        if key in seen:
            continue
        seen.add(key)
        out.append({**ch, "score": round(s, 3)})
        if len(out) >= max(1, min(k, 8)):
            break
    return out


def format_passages(hits: list[dict[str, Any]]) -> str:
    if not hits:
        return "(no matching notes)"
    lines = []
    for i, h in enumerate(hits, 1):
        lines.append(f"[{i}] {h['title']} (id={h['note_id']}, score={h.get('score', 0)})")
        lines.append(h["text"])
        lines.append("")
    return "\n".join(lines).strip()


def citation_line(hits: list[dict[str, Any]]) -> str:
    titles = []
    seen: set[str] = set()
    for h in hits:
        t = h["title"]
        if t not in seen:
            seen.add(t)
            titles.append(t)
    if not titles:
        return ""
    return "Sources: " + "; ".join(titles)


def notes_from_hits(hits: list[dict[str, Any]]) -> str:
    return "\n\n".join(h["text"] for h in hits)
