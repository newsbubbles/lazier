"""Sound direction. The audio-side sibling of direction.py.

The Sound Director plans a SPARSE set of music/SFX cues over the whole video, given the
transcript word-timing, the beats (+ the visual register already chosen for each), the
thesis/tone, and a deterministic quiet-moment map. The voice is always the protagonist —
sound supports, it never fills every gap. It does NOT fetch; soundsourcing.py does that.

Beat-boundary alignment (v1, locked): the director works in beat INDICES (models mangle
long ids and free-floating float times), and we convert those to timeline seconds here, so
every cue snaps to real beat boundaries by construction. Fine hand-nudging is the per-clip
align_offset later, not the director's job."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel

from . import config
from .agents import run_agent
from .models import Beat, Project, SoundCue

# A silent gap between spoken words longer than this is a "quiet moment" the director can
# score with a swell/bed without fighting the voice. Deterministic (exact timing, not judgment).
QUIET_GAP_SECONDS = 0.8


def quiet_moments(project: Project, limit: int = 24) -> list[tuple[float, float, float]]:
    """Speech gaps over QUIET_GAP_SECONDS as (start, end, duration), longest first. Derived
    from transcript words, not stored — the raw material for tension builds and music beds."""
    words = project.transcript.words if project.transcript else []
    gaps: list[tuple[float, float, float]] = []
    for a, b in zip(words, words[1:]):
        g = b.start - a.end
        if g > QUIET_GAP_SECONDS:
            gaps.append((round(a.end, 2), round(b.start, 2), round(g, 2)))
    gaps.sort(key=lambda x: x[2], reverse=True)
    return gaps[:limit]


class _Cue(BaseModel):
    start_beat: int              # beat index where the sound enters
    end_beat: int                # beat index where it leaves (inclusive)
    anchor_beat: int             # beat whose START the climax should land on
    kind: str                    # music | effect
    intent: str                  # build suspense | mystery | impact | warmth | comic beat
    brief: str
    search_terms: list[str]
    dynamics: str                # swell | stinger | bed | hit | drone
    duck: bool = True
    rationale: str = ""


class _Cues(BaseModel):
    cues: list[_Cue]


_SYS = (
    "You are the SOUND DIRECTOR for a faceless narrated video. Over the WHOLE piece you plan a "
    "SPARSE set of music and sound-effect cues that ride under the narration. The spoken VOICE "
    "is the protagonist — sound supports it and never competes. This is not a soundtrack that "
    "plays wall-to-wall; it is a handful of deliberate moments.\n\n"
    "HARD RULES:\n"
    "- Be SPARSE. A ~8 minute video wants maybe 8-16 cues total, not one per beat. Silence is a "
    "tool; leave most beats bare. If you fill everything you have failed.\n"
    "- Every cue is one of kind='music' (a bed/swell/drone that sits under a stretch) or "
    "kind='effect' (a short stinger/hit/whoosh punctuating one moment).\n"
    "- MUSIC beds span several beats and should duck=true (sit under the voice). Use the QUIET "
    "MOMENTS for swells and tension builds — that's where music breathes without fighting words.\n"
    "- EFFECTS are short. A stinger/hit lands ON a beat boundary (its anchor_beat) — a punchline, "
    "a reveal, a turn. A punchy one-shot can duck=false so it cuts through; a whoosh under speech "
    "ducks.\n"
    "- Match the video's TONE. Build across a section toward its payoff beat, then breathe.\n"
    "- dynamics: swell (music rising into a moment), bed (steady underscore), drone (tense "
    "sustained), stinger (sharp musical/percussive punctuation), hit (a single impact/whoosh).\n\n"
    "For EACH cue give: start_beat + end_beat (the beat-index range it covers; a stinger has "
    "start==end), anchor_beat (the beat whose START its climax lands on — usually within the "
    "range), kind, intent, a concrete BRIEF of the sound (what it is: 'low ominous brass swell', "
    "'medieval court fanfare', 'metallic sword unsheathe', 'comedic record-scratch'), 2-3 SHORT "
    "search_terms a person would type to FIND that sound (e.g. 'ominous brass swell', 'sword "
    "unsheathe sound effect'), dynamics, duck, and a one-line rationale. Use the beats' visual "
    "registers as hints: a 'reaction' beat may want a comic stinger; a 'metaphor' or a payoff "
    "wants a swell; keep 'data'/'evidence' beats mostly dry."
)


def _beat_register(project: Project, beat: Beat) -> str:
    sug = project.suggestions.get(beat.id)
    if sug and sug.plan and sug.plan.visual_register:
        return sug.plan.visual_register
    return "-"


def plan_sound(project: Project, notes: str = "") -> list[SoundCue]:
    beats = sorted(project.beats, key=lambda b: b.start)
    if not beats:
        return []
    beat_lines = [
        f"[{i}] {b.start:6.1f}-{b.end:5.1f}s ({_beat_register(project, b)}) {b.text[:80]}"
        for i, b in enumerate(beats)
    ]
    quiet = quiet_moments(project)
    quiet_lines = [f"  {s:.1f}-{e:.1f}s ({d:.1f}s of silence)" for s, e, d in quiet] or ["  (none)"]

    parts = [
        f"VIDEO: {project.name}",
        f"THESIS: {project.video_summary or '(none)'}",
        f"TONE: {project.tone or '(infer from the words)'}",
        f"DURATION: {project.duration:.0f}s",
        f"USER NOTES: {notes.strip() or '(none — your call)'}",
        "",
        "BEATS in order, shown as [index] start-end (visual register) text:",
        "\n".join(beat_lines),
        "",
        "QUIET MOMENTS (speech gaps you can score without fighting the voice):",
        "\n".join(quiet_lines),
        "",
        "Return a SPARSE list of cues. Reference beats by their [index]. anchor_beat is where "
        "the sound's climax lands. Do NOT cover every beat.",
    ]
    out = run_agent(_SYS, "\n".join(parts), _Cues, model_name=config.SHORTS_MODEL)

    n = len(beats)
    cues: list[SoundCue] = []
    for c in out.cues:
        i0 = max(0, min(c.start_beat, n - 1))
        i1 = max(i0, min(c.end_beat, n - 1))
        ai = max(0, min(c.anchor_beat, n - 1))
        kind = "music" if c.kind.strip().lower().startswith("mus") else "effect"
        dyn = c.dynamics.strip().lower()
        if dyn not in ("swell", "stinger", "bed", "hit", "drone"):
            dyn = "bed" if kind == "music" else "hit"
        start, end = beats[i0].start, beats[i1].end
        # a stinger/hit shouldn't hold for the whole beat span — cap short effects to a few
        # seconds around the anchor so we don't stretch a one-shot into a drone.
        anchor = beats[ai].start
        if kind == "effect":
            end = min(end, anchor + 3.0)
            start = min(start, anchor)
        cues.append(SoundCue(
            start=round(start, 2), end=round(end, 2), kind=kind,
            intent=c.intent.strip(), brief=c.brief.strip(),
            search_terms=[t.strip() for t in c.search_terms if t.strip()][:3],
            anchor=round(anchor, 2), dynamics=dyn, duck=bool(c.duck),
            rationale=c.rationale.strip(),
        ))
    cues.sort(key=lambda c: c.start)
    return cues
