"""Web capture: load a URL in headless Chromium, smoothly scroll through it (optionally
highlighting the sentence that matches the narration), record it, and hand back a clean
mp4 — the "scroll through the article" look. A clip source alongside YouTube."""

from __future__ import annotations

import subprocess
from pathlib import Path

from . import config
from .youtube import SourcingError

# JS: find the first text node containing the phrase, wrap it in a highlighted <mark>,
# scroll it to center, return its absolute Y (or null if not found).
_HIGHLIGHT_JS = r"""
(phrase) => {
  const needle = (phrase || "").toLowerCase().trim().slice(0, 60);
  if (!needle) return null;
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  let node;
  while ((node = walker.nextNode())) {
    const val = node.nodeValue;
    if (!val) continue;
    const idx = val.toLowerCase().indexOf(needle);
    if (idx === -1) continue;
    try {
      const mark = document.createElement("mark");
      mark.style.background = "#ffe600";
      mark.style.color = "#000";
      const range = document.createRange();
      range.setStart(node, idx);
      range.setEnd(node, Math.min(idx + needle.length, val.length));
      range.surroundContents(mark);
      const r = mark.getBoundingClientRect();
      return r.top + window.scrollY;
    } catch (e) { return null; }
  }
  return null;
}
"""


def _ease(p: float) -> float:
    return 3 * p * p - 2 * p * p * p  # smoothstep


def capture_scroll(url: str, out_path: Path, seconds: float,
                   highlight: str | None = None,
                   width: int = 1280, height: int = 720) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    rec_dir = out_path.parent / "_webrec"
    rec_dir.mkdir(parents=True, exist_ok=True)
    seconds = max(seconds, 2.0)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise SourcingError("playwright not installed",
                            "run `uv add playwright && uv run playwright install chromium`")

    webm: Path | None = None
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
            ctx = browser.new_context(
                viewport={"width": width, "height": height},
                record_video_dir=str(rec_dir),
                record_video_size={"width": width, "height": height},
            )
            page = ctx.new_page()
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
            except Exception as e:
                ctx.close(); browser.close()
                raise SourcingError(f"could not load {url}: {str(e)[:100]}",
                                    "discard this URL; try another search result")
            page.wait_for_timeout(900)  # let layout/fonts settle

            target_y = None
            if highlight:
                try:
                    target_y = page.evaluate(_HIGHLIGHT_JS, highlight)
                except Exception:
                    target_y = None

            page_h = page.evaluate("document.body.scrollHeight") or height
            end_y = (max(0, target_y - height / 2) if target_y
                     else max(0, min(page_h - height, page_h)))
            steps = max(int(seconds * 25), 12)
            for i in range(steps + 1):
                y = end_y * _ease(i / steps)
                page.evaluate(f"window.scrollTo(0, {y})")
                page.wait_for_timeout(int(1000 / 25))
            page.wait_for_timeout(400)
            ctx.close()  # finalizes the .webm
            browser.close()
    except SourcingError:
        raise
    except Exception as e:
        raise SourcingError(f"web capture failed: {str(e)[:120]}",
                            "discard this URL; try another search result")

    webm = next(iter(rec_dir.glob("*.webm")), None)
    if not webm:
        raise SourcingError("no recording produced", "discard this URL")

    norm = subprocess.run([
        config.FFMPEG, "-y", "-i", str(webm), "-t", f"{seconds:.2f}",
        "-r", "30", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an",
        "-preset", "veryfast", "-crf", "23", str(out_path),
    ], capture_output=True, text=True)
    webm.unlink(missing_ok=True)
    if norm.returncode != 0 or not out_path.exists():
        tail = norm.stderr.strip().splitlines()[-3:]
        raise SourcingError(f"normalize failed: {' '.join(tail)[:140]}", "discard this URL")
    return out_path
