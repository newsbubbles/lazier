"""Two-pass segmentation.

Pass 1 (deterministic): split words into segments wherever the silent gap between
consecutive words exceeds SEGMENT_GAP_SECONDS.

Pass 2 (LLM): read the pass-1 segments and merge adjacent ones into coherent topic
sections, each with a topic label and a 'visual brief' describing what should be on
screen. The section is the unit later milestones source visuals for."""

from __future__ import annotations

from pydantic import BaseModel

from . import config
from .agents import run_agent
from .models import Beat, Section, Segment, Transcript


def pass1_segments(transcript: Transcript, gap: float | None = None) -> list[Segment]:
    gap = config.SEGMENT_GAP_SECONDS if gap is None else gap
    segments: list[Segment] = []
    cur_words: list = []

    def flush():
        if cur_words:
            segments.append(Segment(
                start=cur_words[0].start,
                end=cur_words[-1].end,
                text=" ".join(w.text for w in cur_words).strip(),
            ))

    prev_end = None
    for w in transcript.words:
        if prev_end is not None and (w.start - prev_end) > gap and cur_words:
            flush()
            cur_words = []
        cur_words.append(w)
        prev_end = w.end
    flush()
    return segments


_SYSTEM = (
    "You are the segmenter for a video editor. You group a narration's small speech "
    "segments into a few coherent TOPIC CHAPTERS. A chapter is a stretch of narration "
    "that shares one visual idea on screen. For each chapter write a short 'visual_brief': "
    "a concrete, search-friendly description of the b-roll/image that would illustrate it "
    "(subjects, setting, mood). Never drop or reorder segments; every input index appears "
    "in exactly one chapter, and chapters are contiguous ranges that tile the whole input."
)


def _ranges_from_starts(items: list[tuple[int, object]], n: int) -> list[tuple[int, int, object]]:
    """Turn ascending START boundaries into contiguous ranges tiling [0..n-1]. Dedupes,
    clamps, and forces the first boundary to 0, so the tiling is VALID BY CONSTRUCTION —
    the LLM only picks where each chapter/beat begins (semantic); coverage is deterministic."""
    seen: set[int] = set()
    clean: list[tuple[int, object]] = []
    for s, payload in sorted(items, key=lambda x: x[0]):
        s = max(0, min(int(s), n - 1))
        if s not in seen:
            seen.add(s)
            clean.append((s, payload))
    if not clean:
        return [(0, n - 1, None)]
    if clean[0][0] != 0:
        clean.insert(0, (0, clean[0][1]))
    ranges: list[tuple[int, int, object]] = []
    for idx, (s, payload) in enumerate(clean):
        e = (clean[idx + 1][0] - 1) if idx + 1 < len(clean) else (n - 1)
        if e >= s:
            ranges.append((s, e, payload))
    return ranges


class _Chapter(BaseModel):
    start_index: int
    topic_label: str = ""
    visual_brief: str = ""


class _Chapters(BaseModel):
    chapters: list[_Chapter]


def pass2_sections(segments: list[Segment]) -> list[Section]:
    if not segments:
        return []
    n = len(segments)
    numbered = "\n".join(f"[{i}] {s.text}" for i, s in enumerate(segments))
    user = (f"Group these {n} narration phrases (indices 0..{n - 1}) into topic chapters. "
            f"For each chapter give its start_index (the phrase where it begins; the first "
            f"chapter starts at 0, indices strictly ascending), a topic_label, and a concrete "
            f"search-friendly visual_brief.\n\n{numbered}")
    out = run_agent(_SYSTEM, user, _Chapters)

    sections: list[Section] = []
    for i0, i1, c in _ranges_from_starts([(c.start_index, c) for c in out.chapters], n):
        members = segments[i0:i1 + 1]
        if not members:
            continue
        sections.append(Section(
            start=members[0].start, end=members[-1].end,
            text=" ".join(m.text for m in members).strip(),
            topic_label=(c.topic_label.strip() if c else ""),
            visual_brief=(c.visual_brief.strip() if c else ""),
            segment_ids=[m.id for m in members],
        ))
    return sections


def _one_section_per_segment(segments: list[Segment]) -> list[Section]:
    return [
        Section(start=s.start, end=s.end, text=s.text, topic_label="",
                visual_brief=s.text, segment_ids=[s.id])
        for s in segments
    ]


def _phrase_beats(section: Section, members: list[Segment]) -> list[Beat]:
    """Pass A (deterministic, speech-timing): one beat per phrase, made FLUSH so the
    beats tile the whole chapter with no gaps (silences fold into the preceding beat)."""
    n = len(members)
    beats: list[Beat] = []
    for i, seg in enumerate(members):
        start = section.start if i == 0 else seg.start
        end = section.end if i == n - 1 else members[i + 1].start
        beats.append(Beat(section_id=section.id, start=start, end=end, text=seg.text))
    return beats


_BEATSYS = (
    "You group a narration's short phrases into VISUAL BEATS. Each beat becomes ONE b-roll "
    "clip, so a beat must hold a single visual idea and enough context that a search for "
    "footage makes sense. You get the phrases of one chapter, in order, each with an index "
    "and its duration. MERGE only ADJACENT phrases that share the same on-screen visual; "
    "leave a phrase on its own when its visual differs from its neighbors. Aim for beats "
    "around the target length, and NEVER propose a group whose combined duration exceeds "
    "the max. Keep order; every phrase belongs to exactly one beat (contiguous ranges that "
    "tile the whole chapter)."
)


class _Beat(BaseModel):
    start_index: int


class _Beats(BaseModel):
    beats: list[_Beat]


def _merge_beats(section: Section, phrase_beats: list[Beat]) -> list[Beat]:
    """Pass B (agent): merge adjacent phrase-beats that share a visual. The agent picks each
    beat's START phrase; the tiling is built by construction (_ranges_from_starts), and
    BEAT_MAX_SECONDS is enforced deterministically — a run over max is split down to fit."""
    n = len(phrase_beats)
    if n <= 1:
        return phrase_beats
    mn, mx = config.BEAT_MIN_SECONDS, config.BEAT_MAX_SECONDS
    theme = section.visual_brief or section.topic_label or ""
    lines = "\n".join(f"[{i}] ({b.end - b.start:.1f}s) {b.text}" for i, b in enumerate(phrase_beats))
    user = (f"Chapter theme: {theme}\n\nPhrases (index, duration, text):\n{lines}\n\n"
            f"Group adjacent phrases that share ONE on-screen visual into beats of about "
            f"{mn:.0f}-{mx:.0f}s (hard max {mx:.0f}s); leave a standalone visual on its own. "
            f"For each beat give its start_index (the phrase where it begins; the first beat "
            f"starts at 0, indices strictly ascending).")
    result = run_agent(_BEATSYS, user, _Beats)

    out: list[Beat] = []
    for i0, i1, _ in _ranges_from_starts([(b.start_index, None) for b in result.beats], n):
        k = i0
        while k <= i1:  # greedily accept the longest run that stays <= max (the guardrail)
            j = k
            while j + 1 <= i1 and (phrase_beats[j + 1].end - phrase_beats[k].start) <= mx:
                j += 1
            grp = phrase_beats[k:j + 1]
            out.append(Beat(section_id=section.id, start=grp[0].start, end=grp[-1].end,
                            text=" ".join(b.text for b in grp).strip()))
            k = j + 1
    return out


def build_beats(sections: list[Section], segments: list[Segment],
                llm: bool = True) -> list[Beat]:
    by_id = {s.id: s for s in segments}
    chapters: list[tuple[Section, list[Beat]]] = []
    for sec in sections:
        members = [by_id[sid] for sid in sec.segment_ids if sid in by_id]
        if members:
            chapters.append((sec, _phrase_beats(sec, members)))
    if not llm:
        return [b for _, phrases in chapters for b in phrases]

    # Chapters are independent -> merge them concurrently. Each _merge_beats runs its own
    # run_sync in a worker thread (own loop + fresh model), so this is safe under fan-out.
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=min(6, len(chapters) or 1)) as ex:
        merged = list(ex.map(lambda cp: _merge_beats(cp[0], cp[1]), chapters))
    return [b for group in merged for b in group]


def make_sections_flush(sections: list[Section], beats: list[Beat]) -> None:
    """Close the black gaps between chapters IN PLACE: section N-1's end meets section N's
    start (the inter-chapter silence joins the preceding chapter), the first section starts
    at 0, and each chapter's beats are re-flushed to its new bounds. So the whole timeline
    tiles with no holes. Deterministic — no LLM, safe to run on an existing project."""
    if not sections:
        return
    secs = sorted(sections, key=lambda s: s.start)
    secs[0].start = 0.0
    for i in range(len(secs) - 1):
        secs[i].end = secs[i + 1].start
    for i in range(1, len(secs)):
        secs[i].start = secs[i - 1].end
    for sec in secs:
        sb = sorted([b for b in beats if b.section_id == sec.id], key=lambda b: b.start)
        if not sb:
            continue
        sb[0].start = sec.start
        for k in range(len(sb) - 1):
            sb[k].end = sb[k + 1].start
        sb[-1].end = sec.end


def chapters_and_beats(segments: list[Segment],
                       llm_merge: bool = True) -> tuple[list[Section], list[Beat]]:
    sections = pass2_sections(segments) if llm_merge else _one_section_per_segment(segments)
    beats = build_beats(sections, segments, llm=llm_merge)
    make_sections_flush(sections, beats)
    return sections, beats


def segment(transcript: Transcript,
            llm_merge: bool = True) -> tuple[list[Segment], list[Section], list[Beat]]:
    segs = pass1_segments(transcript)
    sections, beats = chapters_and_beats(segs, llm_merge)
    return segs, sections, beats
