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
import sys
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


def _run_bounded(cmd: list[str], timeout: int) -> tuple[int | None, str]:
    """Run cmd, HARD-killing the whole process tree on timeout. `--download-sections` makes
    yt-dlp spawn an ffmpeg child that a plain subprocess timeout can't reap — it holds the
    pipe open, so a 25s cap turns into a multi-minute hang. taskkill /T (Windows) / killpg
    (POSIX) kills the tree so the cap is real. Returns (returncode|None, output); None = timed
    out."""
    kw = {} if sys.platform == "win32" else {"start_new_session": True}
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, **kw)
    try:
        out, _ = proc.communicate(timeout=timeout)
        return proc.returncode, out
    except subprocess.TimeoutExpired:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
        else:
            import os
            import signal
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                proc.kill()
        try:
            out, _ = proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            out = ""
        return None, out


def _vfmt(h: int) -> str:
    return (f"bv*[height<={h}][ext=mp4]+ba[ext=m4a]/b[height<={h}][ext=mp4]/"
            f"bv*[height<={h}]+ba/b[height<={h}]/b")


def _trim(src: Path, out: Path, seconds: float, seek: float, audio: bool) -> None:
    """Trim `seconds` from `src` (optionally seeking to `seek`) and normalize for clean
    compositing. Video -> h264/yuv420p/30fps (no audio); audio -> 48k stereo aac."""
    cmd = [config.FFMPEG, "-y"]
    if seek > 0:
        cmd += ["-ss", f"{seek:.2f}"]
    cmd += ["-i", str(src), "-t", f"{seconds:.2f}"]
    if audio:
        cmd += ["-vn", "-ac", "2", "-ar", "48000", "-c:a", "aac", "-b:a", "192k"]
    else:
        cmd += ["-r", "30", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an",
                "-preset", "veryfast", "-crf", "20"]
    res = subprocess.run(cmd + [str(out)], capture_output=True, text=True, timeout=120)
    if res.returncode != 0 or not out.exists():
        tail = " ".join(res.stderr.strip().splitlines()[-3:])[:160]
        raise SourcingError(f"trim failed: {tail}", "discard this candidate, try the next")


def _fetch(video_id: str, seconds: float, out_path: Path, start_at: float,
           section_fmt: str, full_fmt: str, audio: bool) -> Path:
    """Two-tier fetch. PRIMARY: the fast `--download-sections` grab (only the needed slice),
    hard-capped at SOURCE_SECTION_TIMEOUT so a throttled/hung attempt can't stall. FALLBACK
    (only if that fails): download the FULL source once and trim locally — reliable when
    YouTube throttles the ranged section request. Errors loudly if BOTH fail."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    url = f"https://www.youtube.com/watch?v={video_id}"
    end_at = start_at + max(seconds, 1.0)
    raw = out_path.with_suffix(".raw" + out_path.suffix)

    # 1) fast section grab at native resolution (what worked before), tree-killed at the cap
    raw.unlink(missing_ok=True)
    section = ["yt-dlp", "-f", section_fmt, "--download-sections", f"*{start_at:.2f}-{end_at:.2f}",
               "--no-playlist", "--quiet", "--no-warnings", "-o", str(raw), url]
    if not audio:
        section.insert(3, "--force-keyframes-at-cuts")   # frame-accurate cut for video
    rc, _ = _run_bounded(section, config.SOURCE_SECTION_TIMEOUT)
    if rc == 0 and raw.exists():
        try:
            _trim(raw, out_path, seconds, seek=0.0, audio=audio)  # section already starts at start_at
            return out_path
        finally:
            raw.unlink(missing_ok=True)
    raw.unlink(missing_ok=True)   # timed out (rc None) or failed -> fall back

    # 2) fallback: full download at a bounded resolution, then trim the window locally
    full = out_path.with_suffix(".full" + out_path.suffix)
    full.unlink(missing_ok=True)
    rc, out = _run_bounded(["yt-dlp", "-f", full_fmt, "--no-playlist", "--quiet", "--no-warnings",
                            "-o", str(full), url], config.SOURCE_FULL_TIMEOUT)
    if rc != 0 or not full.exists():
        full.unlink(missing_ok=True)
        detail = "download timed out" if rc is None else " ".join(out.strip().splitlines()[-3:])[:160]
        raise SourcingError(f"yt-dlp could not fetch {video_id}: {detail}",
                            "try the next search result")
    try:
        _trim(full, out_path, seconds, seek=start_at, audio=audio)
        return out_path
    finally:
        full.unlink(missing_ok=True)


def fetch_clip(video_id: str, seconds: float, out_path: Path,
               start_at: float = 0.0) -> Path:
    """Fetch a video clip. Fast section grab at native res first; full-download-and-trim
    fallback (bounded resolution) only if the section is throttled/fails. See _fetch."""
    return _fetch(video_id, seconds, out_path, start_at,
                  section_fmt=_vfmt(config.SOURCE_MAX_HEIGHT),
                  full_fmt=_vfmt(config.SOURCE_FALLBACK_HEIGHT), audio=False)


def fetch_audio(video_id: str, seconds: float, out_path: Path,
                start_at: float = 0.0) -> Path:
    """Fetch an audio clip (music/SFX cue). Same two-tier fetch as fetch_clip, audio-only."""
    return _fetch(video_id, seconds, out_path, start_at,
                  section_fmt="ba[ext=m4a]/ba/bestaudio",
                  full_fmt="ba[ext=m4a]/ba/bestaudio", audio=True)
    return out_path
