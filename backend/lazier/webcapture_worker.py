"""Standalone Playwright capture worker. Runs in its OWN process with the ProactorEvent
Loop (which SelectorEventLoop, set process-wide for pydantic-ai on Windows, cannot do —
it can't spawn subprocesses). The main process shells out to this via subprocess.run.

Self-contained: imports only playwright + stdlib, never lazier.config (which would flip
the loop policy back to Selector). Argv: url rec_dir width height seconds highlight."""

import sys
import time
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
    headed = len(sys.argv) > 7 and sys.argv[7] == "1"
    width, height, seconds = int(width), int(height), float(seconds)
    highlight = highlight or None
    from playwright.sync_api import sync_playwright

    ua = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
          "Chrome/149.0.0.0 Safari/537.36")
    args = ["--no-sandbox", "--disable-blink-features=AutomationControlled"]
    if headed:
        args += ["--window-position=-2400,-2400"]  # off-screen so it doesn't disrupt the desktop
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not headed, args=args)
        ctx = browser.new_context(
            viewport={"width": width, "height": height},
            user_agent=ua, locale="en-US",
            extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
            record_video_dir=rec_dir,
            record_video_size={"width": width, "height": height},
        )
        # basic stealth: hide the automation tells most bot-walls check
        ctx.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
            "Object.defineProperty(navigator,'languages',{get:()=>['en-US','en']});"
            "Object.defineProperty(navigator,'plugins',{get:()=>[1,2,3,4,5]});"
            "window.chrome={runtime:{}};"
        )
        t_rec = time.monotonic()          # recording starts about here
        page = ctx.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        # let the page FULLY load before we start the shot (up to ~10s), so the clip
        # doesn't open on a blank white loading frame.
        for state, to in (("load", 10000), ("networkidle", 6000)):
            try:
                page.wait_for_load_state(state, timeout=to)
            except Exception:
                pass
        page.wait_for_timeout(500)

        # bail if the site served a bot-block / error page instead of content
        try:
            probe = (page.title() + " " + page.evaluate(
                "document.body ? document.body.innerText.slice(0,500) : ''")).lower()
        except Exception:
            probe = ""
        BLOCKS = ("access denied", "forbidden", "you don't have permission", "error 403",
                  "just a moment", "are you a robot", "verify you are human", "captcha",
                  "unusual traffic", "enable javascript and cookies")
        if any(k in probe for k in BLOCKS):
            ctx.close(); browser.close()
            print(f"BLOCKED (bot detection): {probe[:90].strip()}", file=sys.stderr)
            sys.exit(2)

        target_y = None
        if highlight:
            try:
                target_y = page.evaluate(_HIGHLIGHT_JS, highlight)
            except Exception:
                target_y = None

        page_h = page.evaluate("document.body.scrollHeight") or height
        # A gentle, bounded pan — NOT a blur through the whole page. If we found the
        # highlighted line, pan to center it starting ~0.8 viewport above; otherwise a
        # short pan from the top.
        if target_y is not None:
            end_scroll = max(0.0, target_y - height / 2)
            start_scroll = max(0.0, end_scroll - height * 0.8)
        else:
            start_scroll = 0.0
            end_scroll = min(float(page_h - height), height * 1.4)

        page.evaluate(f"window.scrollTo(0, {start_scroll})")
        page.wait_for_timeout(250)
        t_scroll = time.monotonic() - t_rec        # trim everything before the shot
        steps = max(int(seconds * 25), 12)
        for i in range(steps + 1):
            y = start_scroll + (end_scroll - start_scroll) * _ease(i / steps)
            page.evaluate(f"window.scrollTo(0, {y})")
            page.wait_for_timeout(int(1000 / 25))
        page.wait_for_timeout(300)
        ctx.close()
        browser.close()
    print(f"TRIM {t_scroll:.2f}")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)
