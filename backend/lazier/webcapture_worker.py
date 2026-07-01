"""Standalone Playwright capture worker. Runs in its OWN process with the ProactorEvent
Loop (which SelectorEventLoop, set process-wide for pydantic-ai on Windows, cannot do —
it can't spawn subprocesses). The main process shells out to this via subprocess.run.

Self-contained: imports only playwright + stdlib, never lazier.config (which would flip
the loop policy back to Selector). Argv: url rec_dir width height seconds highlight."""

import sys
import asyncio

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

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
    return 3 * p * p - 2 * p * p * p


def main() -> None:
    url, rec_dir, width, height, seconds, highlight = sys.argv[1:7]
    width, height, seconds = int(width), int(height), float(seconds)
    highlight = highlight or None
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
        ctx = browser.new_context(
            viewport={"width": width, "height": height},
            record_video_dir=rec_dir,
            record_video_size={"width": width, "height": height},
        )
        page = ctx.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(900)

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
            page.evaluate(f"window.scrollTo(0, {end_y * _ease(i / steps)})")
            page.wait_for_timeout(int(1000 / 25))
        page.wait_for_timeout(400)
        ctx.close()
        browser.close()
    print("OK")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)
