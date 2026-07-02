"""Visual direction. Two agents (see notes/06-direction/visual-direction.md):

- summarize_video: one-time thesis/throughline + inferred tone, so the director has the
  top of the context hierarchy.
- direct_section: the Visual DIRECTOR. Given the video summary, tone, the full section (a
  scene), its beats in order, what's already placed, and Nate's optional user notes, it
  plans the shot sequence — register + content_type + shot_brief + search_terms +
  time_window per beat — enforcing variety, flow and no repetition ACROSS the section."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel

from . import config
from .agents import run_agent
from .models import BeatPlan, Project, Section

REGISTERS = ("literal", "evidence", "data", "metaphor", "reaction", "archival", "ambient", "motif")


# --- summarizer --------------------------------------------------------------
class _Summary(BaseModel):
    summary: str
    tone: str = ""


_SUM_SYS = (
    "You prep a narration script for a video editor. In 2-3 sentences state the video's "
    "THESIS / throughline (what it's really about and its argument). Also name the overall "
    "TONE in a few words (e.g. 'dry comedic essay', 'earnest documentary', 'meme-heavy rant')."
)


def summarize_video(transcript_text: str) -> _Summary:
    return run_agent(_SUM_SYS, f"Transcript:\n{transcript_text}\n\nGive the thesis + tone.",
                     _Summary)


# --- director ----------------------------------------------------------------
class _Directive(BaseModel):
    beat_index: int              # the [i] index of the beat in the section listing
    visual_register: str         # literal|evidence|data|metaphor|reaction|archival|ambient|motif
    content_type: str            # youtube | web  (image/meme/gen come later)
    shot_brief: str
    search_terms: list[str]
    time_window: Optional[str] = None
    rationale: str = ""


class _Directions(BaseModel):
    beats: list[_Directive]


_DIRECTOR_SYS = (
    "You are the VISUAL DIRECTOR for a faceless video. You plan the b-roll for one SECTION "
    "(a scene) as a sequence, the way a human editor does a paper edit — not shot by shot in "
    "a vacuum. The audio/voice is the A-roll; you choose the B-roll that rides over it.\n\n"
    "For EACH beat you plan, choose:\n"
    f"- register: one of {', '.join(REGISTERS)}. literal=show the thing; evidence=the actual "
    "article/tweet/paper; data=a chart/number; metaphor=a visual analogy (e.g. a carnival "
    "strength-tester bell shattering = prices exploding); reaction=a meme/cartoon reaction; "
    "archival=old footage; ambient=mood b-roll; motif=a recurring callback.\n"
    "- content_type: 'web' for evidence/data (we scroll-capture the actual page), else "
    "'youtube' (for literal, metaphor, reaction, archival, ambient). Only these two for now.\n"
    "- shot_brief: a concrete description of the SHOT to find (subjects, action, framing, "
    "mood). This is what the searcher and the verifier judge against, so make it visual and "
    "specific, not a paraphrase of the words. Describe ONE single full-frame clip only — "
    "never a screen LAYOUT or composite (no split-screen, side-by-side, picture-in-picture, "
    "montage, or 'one side / the other'); we place exactly one clip per beat, so pick the "
    "single strongest image. Use consecutive beats for contrast instead of splitting a frame.\n"
    "- search_terms: 2-3 SHORT keyword queries a person would actually type into YouTube "
    "(2-4 plain words each: core subject + action). NO mood/flavor adjectives like 'smirk', "
    "'ominous', 'close up' — those kill search. Range them BROAD to specific so at least one "
    "returns results (e.g. 'magician misdirection' then 'sleight of hand trick'). The "
    "shot_brief holds the nuance; the queries stay lean.\n"
    "- time_window: for evidence/news, the date scope as YYYY-MM or YYYY-MM-DD (else null).\n\n"
    "DIRECT LIKE AN EDITOR: vary the register — never repeat the same register or type "
    "back-to-back (two articles in a row is death). Build toward a payoff. Use contrast for "
    "punchlines (serious setup -> comedic metaphor). Hold continuity when the subject stays "
    "put, cut away when it moves. Short beats want punchy single images; long beats can hold "
    "a developing clip. Match tone. It is not literal matching — a metaphor that captures the "
    "MEANING beats a literal clip. Respect what's ALREADY placed in the section and Nate's "
    "USER NOTES above all."
)


def _placed_line(project: Project, bid: str) -> str:
    vt = project.visual_track()
    if not vt:
        return "unplanned"
    clip = next((c for c in vt.clips if c.beat_id == bid), None)
    if not clip:
        return "unplanned"
    asset = project.assets.get(clip.asset_id)
    return f"PLACED [{asset.origin if asset else '?'}]: {asset.name[:50] if asset else ''}"


def direct_section(project: Project, section: Section, target_beat_ids: list[str],
                   user_notes: str = "") -> dict[str, BeatPlan]:
    beats = [b for b in project.beats if b.section_id == section.id]
    if not beats:
        return {}
    idx = {s.id: s for s in project.sections}
    order = [s.id for s in project.sections]
    pos = order.index(section.id) if section.id in order else 0
    prev_topic = idx[order[pos - 1]].topic_label if pos > 0 else "(start)"
    next_topic = idx[order[pos + 1]].topic_label if pos + 1 < len(order) else "(end)"

    target_idx = {i for i, b in enumerate(beats) if b.id in target_beat_ids}
    beat_lines = []
    for i, b in enumerate(beats):
        tag = "  <<< PLAN THIS" if i in target_idx else f"  ({_placed_line(project, b.id)})"
        beat_lines.append(f"[{i}] ({b.end - b.start:.1f}s) {b.text}{tag}")

    ref = project.reference_date or "(none given — infer from the words if they cite a date)"
    parts = [
        f"VIDEO: {project.name}",
        f"THESIS: {project.video_summary or '(none)'}",
        f"TONE: {project.tone or '(infer)'}",
        f"REFERENCE DATE: {ref}",
        f"USER NOTES: {user_notes.strip() or '(none — your call)'}",
        "",
        f"THIS SECTION (chapter '{section.topic_label}'), prev='{prev_topic}' next='{next_topic}':",
        section.text,
        "",
        "BEATS in order, shown as [index]. Plan only the ones marked PLAN THIS; the rest",
        "are context (surrounding shots you must NOT clash with or repeat):",
        "\n".join(beat_lines),
        "",
        "Return one directive per beat marked PLAN THIS, using its [index] as beat_index, "
        "considering the whole section flow.",
    ]
    out = run_agent(_DIRECTOR_SYS, "\n".join(parts), _Directions,
                    model_name=config.DIRECTOR_MODEL)

    plans: dict[str, BeatPlan] = {}
    for d in out.beats:
        i = d.beat_index
        if i < 0 or i >= len(beats) or i not in target_idx:
            continue
        b = beats[i]
        ct = d.content_type.strip().lower()
        reg = d.visual_register.strip()
        if ct not in ("youtube", "web"):
            ct = "web" if reg.lower() in ("evidence", "data") else "youtube"
        plans[b.id] = BeatPlan(
            visual_register=reg, content_type=ct, shot_brief=d.shot_brief.strip(),
            search_terms=[t.strip() for t in d.search_terms if t.strip()][:3],
            time_window=(d.time_window or None), rationale=d.rationale.strip(),
        )
    # any target beat the director skipped: a minimal literal-youtube plan from the words
    for i in target_idx:
        b = beats[i]
        if b.id not in plans:
            plans[b.id] = BeatPlan(visual_register="literal", content_type="youtube",
                                   shot_brief=b.text, search_terms=[b.text[:60]],
                                   rationale="(director returned no directive for this beat; literal default)")
    return plans
