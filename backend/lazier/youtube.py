"""YouTube sourcing: search via the Data API, fetch+trim via yt-dlp.
Two separate tools per the design — API for discovery, yt-dlp for the clip."""

from __future__ import annotations

import subprocess
from pathlib import Path

import httpx

from . import config

SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"


class SourcingError(RuntimeError):
    """Carries forward-pointing guidance (tool-design principle 9)."""
    def __init__(self, reason: str, nxt: str):
        super().__init__(f"{reason} — next: {nxt}")
        self.reason = reason
        self.next = nxt


def search(query: str, max_results: int = 5, duration: str = "short") -> list[dict]:
    """Return lightweight candidate handles, never media. duration: short|medium|any."""
    if not config.YOUTUBE_API_KEY:
        raise SourcingError("YOUTUBE_API_KEY not set",
                            "add the key to D:\\lazier\\.env, or source from stock (M4)")
    params = {
        "key": config.YOUTUBE_API_KEY, "q": query, "part": "snippet", "type": "video",
        "maxResults": max_results, "videoEmbeddable": "true", "safeSearch": "moderate",
    }
    if duration in ("short", "medium", "long"):
        params["videoDuration"] = duration
    r = httpx.get(SEARCH_URL, params=params, timeout=20)
    if r.status_code == 403:
        raise SourcingError(f"YouTube API rejected the request ({r.text[:120]})",
                            "likely daily quota exhausted (100 searches/day) — retry tomorrow or raise quota")
    r.raise_for_status()
    out = []
    for item in r.json().get("items", []):
        vid = item.get("id", {}).get("videoId")
        sn = item.get("snippet", {})
        if not vid:
            continue
        out.append({
            "video_id": vid,
            "title": sn.get("title", ""),
            "channel": sn.get("channelTitle", ""),
            "thumb_url": sn.get("thumbnails", {}).get("medium", {}).get("url", ""),
            "url": f"https://www.youtube.com/watch?v={vid}",
        })
    return out


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
