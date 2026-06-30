"""Serper (Google search) — used to find a relevant page URL when a beat references
an article, paper, or news and we want to capture the actual site."""

from __future__ import annotations

import httpx

from . import config

URL = "https://google.serper.dev/search"


def search(query: str, num: int = 5) -> list[dict]:
    if not config.SERPER_API_KEY:
        raise RuntimeError("SERPER_API_KEY not set (needed for web-capture URL discovery)")
    r = httpx.post(URL, headers={"X-API-KEY": config.SERPER_API_KEY,
                                 "Content-Type": "application/json"},
                   json={"q": query, "num": num}, timeout=20)
    r.raise_for_status()
    out = []
    for o in r.json().get("organic", [])[:num]:
        link = o.get("link")
        if link:
            out.append({"title": o.get("title", ""), "url": link, "snippet": o.get("snippet", "")})
    return out
