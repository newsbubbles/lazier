"""Two-pass segmentation.

Pass 1 (deterministic): split words into segments wherever the silent gap between
consecutive words exceeds SEGMENT_GAP_SECONDS.

Pass 2 (LLM): read the pass-1 segments and merge adjacent ones into coherent topic
sections, each with a topic label and a 'visual brief' describing what should be on
screen. The section is the unit later milestones source visuals for."""

from __future__ import annotations

from . import config
from .llm import json_chat
from .models import Section, Segment, Transcript


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
    "You are the segmenter for a video editor. You group a narration's small "
    "speech segments into a few coherent TOPIC SECTIONS. A section is a stretch of "
    "narration that should share one visual idea on screen. For each section also "
    "write a short 'visual_brief': a concrete description of the b-roll/image that "
    "would illustrate it (subjects, setting, mood), as a search-friendly phrase. "
    "Never drop or reorder segments; every input segment index must appear in exactly "
    "one section, and sections must be contiguous ranges in order."
)


class SegmentationError(RuntimeError):
    pass


def pass2_sections(segments: list[Segment]) -> list[Section]:
    if not segments:
        return []

    n = len(segments)
    numbered = "\n".join(f"[{i}] {s.text}" for i, s in enumerate(segments))
    user = (
        "Merge these narration segments into topic sections.\n\n"
        f"{numbered}\n\n"
        'Return JSON: {"sections": [{"start_index": int, "end_index": int, '
        '"topic_label": str, "visual_brief": str}, ...]}. Ranges are inclusive and '
        f"must tile [0..{n - 1}] with no gaps or overlaps."
    )
    data = json_chat(_SYSTEM, user)
    raw = data.get("sections", [])
    if not raw:
        raise SegmentationError("pass-2 LLM returned no sections")

    # Strict validation: the ranges must tile [0..n-1] exactly. No silent repair —
    # if the model produced a bad partition we surface it with the exact diff.
    ranges = [(int(it["start_index"]), int(it["end_index"])) for it in raw]
    covered = [False] * n
    for i0, i1 in ranges:
        if i0 > i1 or i0 < 0 or i1 >= n:
            raise SegmentationError(f"pass-2 produced out-of-range span [{i0},{i1}] for {n} segments")
        for k in range(i0, i1 + 1):
            if covered[k]:
                raise SegmentationError(f"pass-2 overlapped on segment index {k}")
            covered[k] = True
    missing = [k for k, c in enumerate(covered) if not c]
    if missing:
        raise SegmentationError(f"pass-2 left segment indices uncovered: {missing}")

    sections: list[Section] = []
    for (i0, i1), item in zip(ranges, raw):
        members = segments[i0:i1 + 1]
        sections.append(Section(
            start=members[0].start,
            end=members[-1].end,
            text=" ".join(m.text for m in members).strip(),
            topic_label=str(item.get("topic_label", "")).strip(),
            visual_brief=str(item.get("visual_brief", "")).strip(),
            segment_ids=[m.id for m in members],
        ))
    return sections


def _one_section_per_segment(segments: list[Segment]) -> list[Section]:
    return [
        Section(start=s.start, end=s.end, text=s.text, topic_label="",
                visual_brief=s.text, segment_ids=[s.id])
        for s in segments
    ]


def segment(transcript: Transcript, llm_merge: bool = True) -> tuple[list[Segment], list[Section]]:
    segs = pass1_segments(transcript)
    if not llm_merge:
        return segs, _one_section_per_segment(segs)
    return segs, pass2_sections(segs)
