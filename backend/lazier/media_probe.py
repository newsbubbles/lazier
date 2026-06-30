"""ffprobe helpers: duration + dimensions for ingested media."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from .config import FFPROBE


def probe(path: Path) -> dict:
    """Return {duration, width, height, has_video, has_audio}."""
    cmd = [
        FFPROBE, "-v", "error", "-print_format", "json",
        "-show_format", "-show_streams", str(path),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"ffprobe failed for {path.name}: {res.stderr.strip()}")
    data = json.loads(res.stdout or "{}")

    duration = 0.0
    fmt = data.get("format", {})
    if fmt.get("duration"):
        try:
            duration = float(fmt["duration"])
        except (TypeError, ValueError):
            duration = 0.0

    width = height = 0
    has_video = has_audio = False
    for s in data.get("streams", []):
        if s.get("codec_type") == "video":
            has_video = True
            width = int(s.get("width") or width)
            height = int(s.get("height") or height)
        elif s.get("codec_type") == "audio":
            has_audio = True
        if not duration and s.get("duration"):
            try:
                duration = float(s["duration"])
            except (TypeError, ValueError):
                pass

    return {
        "duration": duration, "width": width, "height": height,
        "has_video": has_video, "has_audio": has_audio,
    }
