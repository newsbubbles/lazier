"""Web capture: scroll-record a URL in headless Chromium (via a subprocess worker that
uses the ProactorEventLoop — Playwright can't launch a browser under the SelectorEventLoop
we set process-wide for pydantic-ai on Windows), then normalize to a clean mp4."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from . import config
from .youtube import SourcingError

_WORKER = Path(__file__).resolve().parent / "webcapture_worker.py"


def capture_scroll(url: str, out_path: Path, seconds: float,
                   highlight: str | None = None,
                   width: int = 1280, height: int = 720) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    rec_dir = out_path.parent / "_webrec"
    rec_dir.mkdir(parents=True, exist_ok=True)
    seconds = max(seconds, 2.0)

    res = subprocess.run(
        [sys.executable, str(_WORKER), url, str(rec_dir), str(width), str(height),
         f"{seconds:.2f}", highlight or ""],
        capture_output=True, text=True, timeout=180,
    )
    if res.returncode != 0:
        tail = " ".join((res.stderr or res.stdout).strip().splitlines()[-3:])
        raise SourcingError(f"web capture failed: {tail[:180]}",
                            "discard this URL; try another search result")

    webm = max(rec_dir.glob("*.webm"), key=lambda p: p.stat().st_mtime, default=None)
    if not webm:
        raise SourcingError("web capture produced no recording", "discard this URL")

    norm = subprocess.run([
        config.FFMPEG, "-y", "-i", str(webm), "-t", f"{seconds:.2f}",
        "-r", "30", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an",
        "-preset", "veryfast", "-crf", "23", str(out_path),
    ], capture_output=True, text=True)
    webm.unlink(missing_ok=True)
    if norm.returncode != 0 or not out_path.exists():
        tail = " ".join(norm.stderr.strip().splitlines()[-3:])
        raise SourcingError(f"normalize failed: {tail[:160]}", "discard this URL")
    return out_path
