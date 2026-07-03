"""Shorts: pick one ~30s vertical clip from a finished project and build its captions.

- find_short: an agent reads the transcript beats + thesis/tone and picks the single best
  self-contained ~30s window (a contiguous run of beats), plus a hook, a social caption, and
  a caption style tuned to the content.
- build_caption_ass: turns the window's word-level Whisper timing into a styled ASS subtitle
  (TikTok-style, word-by-word karaoke highlight). The MECHANICS are ported from MemeCat; the
  STYLE is chosen by the LLM instead of MemeCat's embedding buckets. See notes/12-shorts/plan.md.

The 9:16 reframe + burn-in happen in render.render_short."""

from __future__ import annotations

from pydantic import BaseModel, Field

from . import config
from .agents import run_agent
from .models import Project, Word


# --- agent output ------------------------------------------------------------
class CaptionStyle(BaseModel):
    font: str = "Arial Black"
    base_size: int = 96                 # px on a 1080-wide vertical frame
    primary_color: str = "#FFFFFF"      # base text
    highlight_color: str = "#FFE600"    # spoken / emphasis
    outline: int = Field(default=5, ge=0, le=12)
    shadow: int = Field(default=2, ge=0, le=8)
    words_per_line: int = Field(default=2, ge=1, le=5)
    highlight_mode: str = "word"        # none | word | line
    emphasis_keywords: list[str] = Field(default_factory=list)
    position: str = "center"            # center | lower
    vibe: str = ""                      # one line: why this style fits


class ShortPlan(BaseModel):
    start_index: int                    # first beat [i] in the short
    end_index: int                      # last beat [i] (inclusive)
    hook_title: str = ""                # the on-screen hook / opening line
    social_caption: str = ""            # suggested post caption + hashtags
    rationale: str = ""
    caption_style: CaptionStyle = Field(default_factory=CaptionStyle)


_SYS = (
    "You are a short-form video editor. From a longer narrated video you pick the SINGLE best "
    "~30-second vertical short (YouTube Shorts / Reels / TikTok). You get the video's thesis + "
    "tone and its BEATS in order (each a speech chunk with an index and time). Choose a "
    "CONTIGUOUS run of beats that stands completely on its own.\n"
    "WHAT MAKES A GREAT SHORT:\n"
    "- Opens with a HOOK in the first 1-2 seconds: a question, a bold or contrarian claim, a "
    "number. The first beat must grab.\n"
    "- ONE self-contained idea or takeaway that needs none of the rest of the video.\n"
    "- Starts on a sentence boundary; ends on a payoff or punch, never mid-thought.\n"
    "- The intellectual or emotional peak; a quotable line.\n"
    "- Aim ~30s of speech (roughly 18-45s). Do NOT pad to hit 30 — stop where the thought "
    "closes. Never exceed 60s.\n"
    "Pick a CAPTION STYLE that fits the content/tone: words_per_line (1 = punchy one-word pop; "
    "2-3 = calmer lines), highlight_mode (word = karaoke pop as each word is spoken; line = the "
    "whole line pops; none = plain), colors, and emphasis_keywords worth accenting. Write a "
    "HOOK_TITLE (the on-screen hook) and a SOCIAL_CAPTION (a post caption with 3-6 hashtags)."
)


def find_short(project: Project) -> ShortPlan:
    beats = project.beats
    if not beats:
        raise RuntimeError("project has no beats; transcribe + segment first")
    listing = "\n".join(f"[{i}] ({b.start:.0f}-{b.end:.0f}s) {b.text}" for i, b in enumerate(beats))
    user = (
        f"VIDEO: {project.name}\n"
        f"THESIS: {project.video_summary or '(none)'}\n"
        f"TONE: {project.tone or '(infer)'}\n\n"
        f"BEATS (index, time, text):\n{listing}\n\n"
        f"Return start_index and end_index (inclusive) of the best ~30s short, a hook_title, a "
        f"social_caption, and a caption_style."
    )
    plan = run_agent(_SYS, user, ShortPlan, model_name=config.SHORTS_MODEL)

    # clamp indices, then enforce the length window deterministically
    n = len(beats)
    si = max(0, min(plan.start_index, n - 1))
    ei = max(si, min(plan.end_index, n - 1))
    while ei > si and (beats[ei].end - beats[si].start) > config.SHORTS_MAX_SECONDS:
        ei -= 1                                   # trim trailing beats if over the hard cap
    while ei < n - 1 and (beats[ei].end - beats[si].start) < config.SHORTS_MIN_SECONDS:
        ei += 1                                   # extend if far too short
    plan.start_index, plan.end_index = si, ei
    return plan


def window_bounds(project: Project, plan: ShortPlan) -> tuple[float, float]:
    beats = project.beats
    return beats[plan.start_index].start, beats[plan.end_index].end


# --- ASS caption builder (ported mechanics from MemeCat) ---------------------
def _ass_color(hex_color: str, alpha: str = "00") -> str:
    """#RRGGBB -> ASS &HAABBGGRR& (ASS colour order is BGR)."""
    h = hex_color.lstrip("#")
    if len(h) != 6:
        h = "FFFFFF"
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H{alpha}{b}{g}{r}&".upper()


def _hms(t: float) -> str:
    t = max(0.0, t)
    return f"{int(t // 3600)}:{int((t % 3600) // 60):02d}:{t % 60:05.2f}"


def build_caption_ass(words: list[Word], style: CaptionStyle, w: int, h: int) -> str:
    """Build a styled ASS file (string) from window-relative word timings. `words` must already
    be re-based so the first word starts near 0."""
    base = _ass_color(style.primary_color)
    hi = _ass_color(style.highlight_color)
    if style.highlight_mode == "word":            # karaoke: unsung=Secondary, sung=Primary
        primary, secondary = hi, base
    elif style.highlight_mode == "line":
        primary = secondary = hi
    else:
        primary = secondary = base

    align = 5 if style.position == "center" else 2   # 5 = middle-center, 2 = bottom-center
    margin_v = int(h * 0.10)
    header = (
        "[Script Info]\n"
        f"ScriptType: v4.00+\nPlayResX: {w}\nPlayResY: {h}\nWrapStyle: 2\n\n"
        "[V4+ Styles]\n"
        "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,"
        "Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,"
        "Alignment,MarginL,MarginR,MarginV,Encoding\n"
        f"Style: Default,{style.font},{style.base_size},{primary},{secondary},&H00000000&,"
        f"&H64000000&,1,0,0,0,100,100,0,0,1,{style.outline},{style.shadow},{align},"
        f"80,80,{margin_v},1\n\n"
        "[Events]\n"
        "Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n"
    )
    wpl = max(1, style.words_per_line)
    emph = {k.strip().lower() for k in style.emphasis_keywords if k.strip()}
    events = []
    for i in range(0, len(words), wpl):
        group = words[i:i + wpl]
        if not group:
            continue
        start, end = group[0].start, max(group[-1].end, group[0].start + 0.4)
        parts = []
        for wd in group:
            token = wd.text.strip()
            if not token:
                continue
            bare = token.strip(".,!?—-\"'").lower()
            seg = f"{{\\kf{max(1, int(round((wd.end - wd.start) * 100)))}}}{token} " \
                if style.highlight_mode == "word" else f"{token} "
            if bare in emph:
                seg = f"{{\\fscx118\\fscy118}}{seg}{{\\r}}"
            parts.append(seg)
        text = "".join(parts).strip()
        if text:
            events.append(f"Dialogue: 0,{_hms(start)},{_hms(end)},Default,,0,0,0,,{text}")
    return header + "\n".join(events) + "\n"
