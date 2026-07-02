"""YouTube sourcing: search AND fetch via yt-dlp — no Data API, no quota.

Search used to hit the YouTube Data API (search.list = 100 quota units, ~100 searches/day
total — one long video could exhaust it). yt-dlp's `ytsearch` scrapes the same results with
no key and no quota. Results are cached on disk so repeat topics across videos (and repeated
queries within one run) cost nothing. See notes/09 + the manual-sourcing plan."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import config

_SEARCH_TTL = 14 * 86400  # cache a query's results for two weeks


class SourcingError(RuntimeError):
    """Carries forward-pointing guidance (tool-design principle 9)."""
    def __init__(self, reason: str, nxt: str):
        super().__init__(f"{reason} — next: {nxt}")
        self.reason = reason
        self.next = nxt


# --- search cache (also the dedupe: a repeated query is a cache hit, not a new search) ----
def _cache_dir() -> Path:
    d = config.WORKSPACE / "_cache" / "ytsearch"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _cache_key(query: str, n: int) -> str:
    return hashlib.sha1(f"{n}|{query.strip().lower()}".encode("utf-8")).hexdigest()


def _cache_get(query: str, n: int):
    f = _cache_dir() / f"{_cache_key(query, n)}.json"
    if not f.exists():
        return None
    try:
        obj = json.loads(f.read_text(encoding="utf-8"))   # our own cache file, not LLM output
    except (ValueError, OSError):
        return None
    if time.time() - obj.get("ts", 0) > _SEARCH_TTL:
        return None
    return obj.get("results")


def _cache_put(query: str, n: int, results: list[dict]) -> None:
    try:
        (_cache_dir() / f"{_cache_key(query, n)}.json").write_text(
            json.dumps({"ts": time.time(), "query": query, "results": results}),
            encoding="utf-8")
    except OSError:
        pass


def _clean(v: str) -> str:
    return "" if v.strip() == "NA" else v.strip()


def search(query: str, max_results: int = 5, duration: str = "short",
           published_after: str | None = None, published_before: str | None = None) -> list[dict]:
    """Return lightweight candidate handles via yt-dlp (no key, no quota), cached 14d.

    `duration` and `published_*` are kept for call-site compatibility. ytsearch has no
    date-range filter, so `published_*` only flips ordering to by-date (`ytsearchdate`);
    `duration` is ignored (we only download a SECTION anyway). See notes/09."""
    n = max(int(max_results), 1)
    cached = _cache_get(query, n)
    if cached is not None:
        return cached

    prefix = "ytsearchdate" if (published_after or published_before) else "ytsearch"
    cmd = ["yt-dlp", f"{prefix}{n}:{query}", "--flat-playlist", "--no-warnings", "--quiet",
           "--print", "%(id)s\t%(title)s\t%(channel)s"]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        raise SourcingError("yt-dlp search timed out",
                            "retry, refine the query, or paste a YouTube URL directly")
    if res.returncode != 0:
        tail = " ".join((res.stderr or res.stdout).strip().splitlines()[-2:])
        raise SourcingError(f"yt-dlp search failed: {tail[:160]}",
                            "retry, refine the query, or paste a YouTube URL directly")

    out: list[dict] = []
    for line in res.stdout.splitlines():
        parts = line.split("\t")
        vid = parts[0].strip() if parts else ""
        if not vid or vid == "NA":
            continue
        out.append({
            "video_id": vid,
            "title": _clean(parts[1]) if len(parts) > 1 else "",
            "channel": _clean(parts[2]) if len(parts) > 2 else "",
            "thumb_url": f"https://i.ytimg.com/vi/{vid}/mqdefault.jpg",
            "url": f"https://www.youtube.com/watch?v={vid}",
        })
    _cache_put(query, n, out)
    return out


def _parse_timestamp(t: str) -> float:
    """'90' / '90s' / '1m30s' / '1h2m3s' -> seconds. Deterministic (exact parse, not judgment)."""
    t = t.strip().lower()
    if not t:
        return 0.0
    if t.isdigit():
        return float(t)
    m = re.fullmatch(r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?", t)
    if m and any(m.groups()):
        h, mnt, s = (int(x) if x else 0 for x in m.groups())
        return float(h * 3600 + mnt * 60 + s)
    digits = re.sub(r"\D", "", t)
    return float(digits) if digits else 0.0


def parse_youtube_url(url: str) -> tuple[str, float] | None:
    """Return (video_id, start_seconds) for a YouTube link, else None. Handles watch?v=,
    youtu.be/, /shorts/, /embed/, and the t/start timestamp param. Deterministic URL parse."""
    try:
        u = urlparse((url or "").strip())
    except ValueError:
        return None
    host = (u.hostname or "").lower().removeprefix("www.")
    vid = None
    if host == "youtu.be":
        vid = u.path.lstrip("/").split("/")[0] or None
    elif host in ("youtube.com", "m.youtube.com", "music.youtube.com"):
        if u.path == "/watch":
            vid = (parse_qs(u.query).get("v") or [None])[0]
        elif u.path.startswith("/shorts/"):
            vid = u.path.split("/shorts/", 1)[1].split("/")[0] or None
        elif u.path.startswith("/embed/"):
            vid = u.path.split("/embed/", 1)[1].split("/")[0] or None
    if not vid:
        return None
    qs = parse_qs(u.query)
    tval = (qs.get("t") or qs.get("start") or ["0"])[0]
    return vid, _parse_timestamp(tval)


def fetch_clip(video_id: str, seconds: float, out_path: Path,
               start_at: float = 0.0) -> Path:
    """Download a section and normalize to a clean mp4 of ~`seconds` length.
    yt-dlp grabs the section; ffmpeg normalizes codec/fps so it composites cleanly."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    raw = out_path.with_suffix(".raw.mp4")
    end_at = start_at + max(seconds, 1.0)
    cmd = [
        "yt-dlp",
        "-f", "bv*[height<=720][ext=mp4]+ba[ext=m4a]/b[height<=720][ext=mp4]/b[height<=720]",
        "--download-sections", f"*{start_at:.2f}-{end_at:.2f}",
        "--force-keyframes-at-cuts", "--no-playlist", "--quiet", "--no-warnings",
        "-o", str(raw), f"https://www.youtube.com/watch?v={video_id}",
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if res.returncode != 0 or not raw.exists():
        tail = (res.stderr or res.stdout).strip().splitlines()[-3:]
        raw.unlink(missing_ok=True)
        raise SourcingError(f"yt-dlp could not fetch {video_id}: {' '.join(tail)[:160]}",
                            "discard this candidate and try the next search result")
    # normalize to h264/yuv420p/30fps, trimmed to the needed length
    norm = subprocess.run([
        config.FFMPEG, "-y", "-i", str(raw), "-t", f"{seconds:.2f}",
        "-r", "30", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an",
        "-preset", "veryfast", "-crf", "23", str(out_path),
    ], capture_output=True, text=True)
    raw.unlink(missing_ok=True)
    if norm.returncode != 0 or not out_path.exists():
        tail = norm.stderr.strip().splitlines()[-3:]
        raise SourcingError(f"normalize failed for {video_id}: {' '.join(tail)[:160]}",
                            "discard this candidate and try the next search result")
    return out_path
