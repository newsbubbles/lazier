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

    ua = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
          "Chrome/149.0.0.0 Safari/537.36")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=[
            "--no-sandbox", "--disable-blink-features=AutomationControlled",
        ])
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
        page = ctx.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(1400)

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
