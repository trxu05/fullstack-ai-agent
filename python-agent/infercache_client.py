"""Optional InferCache client — LLM prompt→completion sidecar."""

from __future__ import annotations

import os
from typing import Any

import httpx

INFERCACHE_URL = os.getenv("INFERCACHE_URL", "http://127.0.0.1:8088").rstrip("/")
INFERCACHE_TOKEN = os.getenv("INFERCACHE_TOKEN", "")
INFERCACHE_TTL_MS = int(os.getenv("INFERCACHE_TTL_MS", "300000"))


def _headers() -> dict[str, str]:
    h = {"Content-Type": "application/json"}
    if INFERCACHE_TOKEN:
        h["X-InferCache-Token"] = INFERCACHE_TOKEN
    return h


def get_completion(prompt: str) -> str | None:
    if os.getenv("INFERCACHE_ENABLED", "1") not in {"1", "true", "TRUE", "yes"}:
        return None
    try:
        with httpx.Client(timeout=1.5) as client:
            r = client.post(
                f"{INFERCACHE_URL}/v1/cache/completion",
                headers=_headers(),
                json={"prompt": prompt},
            )
            if r.status_code == 404:
                return None
            r.raise_for_status()
            data = r.json()
            if data.get("hit") and data.get("completion"):
                return str(data["completion"])
    except Exception:
        return None
    return None


def put_completion(prompt: str, completion: str) -> None:
    if os.getenv("INFERCACHE_ENABLED", "1") not in {"1", "true", "TRUE", "yes"}:
        return
    try:
        with httpx.Client(timeout=1.5) as client:
            client.post(
                f"{INFERCACHE_URL}/v1/cache/completion",
                headers=_headers(),
                json={"prompt": prompt, "completion": completion, "ttl_ms": INFERCACHE_TTL_MS},
            )
    except Exception:
        return


def cache_stats() -> dict[str, Any] | None:
    try:
        with httpx.Client(timeout=1.0) as client:
            r = client.get(f"{INFERCACHE_URL}/stats", headers=_headers())
            r.raise_for_status()
            return r.json()
    except Exception:
        return None
