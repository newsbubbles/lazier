"""Lucy adapter: generate an animated explainer clip via the local Lucy service
(D:\\lucy, :5190). Lucy is prompt -> Director + Designer agents -> self-contained animated
HTML -> headless-browser frame capture -> mp4. It's purpose-built to make the little
motion-graphic clips that go INSIDE a lazier video (charts, frameworks, concept diagrams).

We start Lucy's server on demand, POST a clip, poll it to `done`, and hand back the rendered
mp4 for the sourcer to normalize + composite. Same SourcingError contract as youtube.py so the
caller's error handling is uniform. Routed to from a director-chosen content_type='lucy' (rare)
and from the manual per-beat 'Make explainer'."""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path
from typing import Callable, Optional

import httpx

from . import config
from .youtube import SourcingError

Event = Callable[[dict], None]
_RUNNING = {"queued", "directing", "designing", "rendering", "assembling"}


def _health() -> bool:
    try:
        r = httpx.get(f"{config.LUCY_URL}/api/health", timeout=3)
        return r.status_code == 200 and bool(r.json().get("ok"))
    except Exception:
        return False


def ensure_server(on_event: Optional[Event] = None) -> None:
    """Bring Lucy up if it isn't already. Launches it detached (own hidden process) from
    LUCY_DIR and waits for /api/health. Raises SourcingError with guidance if it won't start."""
    if _health():
        return
    if on_event:
        on_event({"msg": "starting Lucy server…"})
    flags = 0x08000000 if sys.platform == "win32" else 0  # CREATE_NO_WINDOW
    try:
        subprocess.Popen(
            ["uv", "run", "uvicorn", "lucy.main:app", "--host", "127.0.0.1", "--port", "5190"],
            cwd=config.LUCY_DIR, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=flags,
        )
    except FileNotFoundError:
        raise SourcingError("could not launch Lucy (uv not on PATH)",
                            f"start it manually: cd {config.LUCY_DIR} && uv run uvicorn lucy.main:app --port 5190")
    for _ in range(45):
        if _health():
            return
        time.sleep(1)
    raise SourcingError("Lucy server did not come up in 45s",
                        f"check it runs standalone from {config.LUCY_DIR}")


def make_clip(prompt: str, aspect: str = "16:9", seconds: float = 8.0,
              resolution: str = "1080p", fps: int = 30,
              on_event: Optional[Event] = None, poll_timeout: int = 360) -> Path:
    """Generate one Lucy clip and return the path to its rendered mp4 (in Lucy's workspace).
    Blocking: starts the server, POSTs, and polls to done/failed. Runs in a worker thread."""
    ensure_server(on_event)
    # Lucy's /api/clips takes multipart/form-data (Form fields + an optional image), NOT JSON.
    # Send form-encoded so the `prompt` field populates; surface Lucy's real error body on reject.
    form = {"prompt": prompt, "aspect_ratio": aspect,
            "duration_seconds": str(round(seconds, 2)), "resolution": resolution, "fps": str(fps)}
    try:
        r = httpx.post(f"{config.LUCY_URL}/api/clips", data=form, timeout=30)
    except Exception as e:
        raise SourcingError(f"Lucy create request failed: {str(e)[:120]}", "check the Lucy server logs")
    if r.status_code != 200:
        raise SourcingError(f"Lucy rejected the clip ({r.status_code}): {r.text[:160]}",
                            "check the Lucy /api/clips schema or the prompt")
    cid = r.json()["id"]

    if on_event:
        on_event({"msg": f"Lucy building {cid[:8]}…"})
    t0, last = time.time(), ""
    while time.time() - t0 < poll_timeout:
        try:
            c = httpx.get(f"{config.LUCY_URL}/api/clips/{cid}", timeout=10).json()
        except Exception:
            time.sleep(2)
            continue
        st = c.get("status", "")
        if st != last:
            last = st
            if on_event:
                on_event({"msg": f"Lucy: {st}"})
        if st == "done":
            mp4 = Path(config.LUCY_DIR) / "workspace" / cid / "final.mp4"
            if mp4.exists():
                return mp4
            raise SourcingError("Lucy reported done but produced no mp4", "retry the clip")
        if st == "failed":
            raise SourcingError(f"Lucy failed: {str(c.get('error', ''))[:120]}",
                                "simplify or reword the prompt and retry")
        time.sleep(2)
    raise SourcingError(f"Lucy build timed out (>{poll_timeout}s)",
                        "the scene may be too complex; shorten or simplify the prompt")
