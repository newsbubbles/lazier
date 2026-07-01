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
         f"{seconds:.2f}", highlight or "", "1" if config.CAPTURE_HEADED else "0"],
        capture_output=True, text=True, timeout=180,
    )
    if res.returncode == 2:  # bot-block / error page, not real content
        tail = " ".join(res.stderr.strip().splitlines()[-2:])
        raise SourcingError(f"site blocked the capture: {tail[:160]}",
                            "this site blocks bots; try a different source URL")
    if res.returncode != 0:
        tail = " ".join((res.stderr or res.stdout).strip().splitlines()[-3:])
        raise SourcingError(f"web capture failed: {tail[:180]}",
                            "discard this URL; try another search result")

    # worker prints "TRIM <seconds>" = the offset where the shot (post-load) begins
    trim = 0.0
    for line in res.stdout.splitlines():
        if line.startswith("TRIM "):
            try:
                trim = max(0.0, float(line.split()[1]))
            except (ValueError, IndexError):
                trim = 0.0

    webm = max(rec_dir.glob("*.webm"), key=lambda p: p.stat().st_mtime, default=None)
    if not webm:
        raise SourcingError("web capture produced no recording", "discard this URL")

    norm = subprocess.run([
        config.FFMPEG, "-y", "-i", str(webm), "-ss", f"{trim:.2f}", "-t", f"{seconds:.2f}",
        "-r", "30", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an",
        "-preset", "veryfast", "-crf", "23", str(out_path),
    ], capture_output=True, text=True)
    webm.unlink(missing_ok=True)
    if norm.returncode != 0 or not out_path.exists():
        tail = " ".join(norm.stderr.strip().splitlines()[-3:])
        raise SourcingError(f"normalize failed: {tail[:160]}", "discard this URL")
    return out_path
