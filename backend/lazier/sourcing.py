"""M2 sourcing pipeline: turn a section's visual brief into ranked clip suggestions.

Per section: research queries (LLM) -> YouTube search -> fetch+trim top results ->
vision-verify each -> rank by fit -> Suggestion (recommended + alternates).

Heavy IO (search/fetch/verify) runs here and RETURNS results; the caller applies
them to the project under a lock and saves. That keeps concurrent source-all runs
from racing on project.json."""

from __future__ import annotations

from typing import Callable, Optional

from . import config, storage, vision, youtube
from .llm import json_chat
from .media_probe import probe
from .models import Candidate, MediaAsset, Project, Section, Suggestion

Event = Callable[[dict], None]


def _emit(on_event: Optional[Event], **kw) -> None:
    if on_event:
        on_event(kw)


_QSYS = (
    "You write YouTube search queries to find b-roll for a narration moment. Given the "
    "narration text and a visual brief, return short, concrete search queries (2-5 words) "
    "that would surface illustrative footage. Prefer visual nouns and scenes over abstract "
    "words. No punctuation, no quotes."
)


def research_queries(section: Section) -> list[str]:
    brief = section.visual_brief or section.text
    user = (f"Narration: {section.text}\nVisual brief: {brief}\n\n"
            f'Return JSON {{"queries": ["...", ...]}} with up to {config.SOURCE_MAX_QUERIES} queries.')
    data = json_chat(_QSYS, user)
    queries = [str(q).strip() for q in data.get("queries", []) if str(q).strip()]
    return queries[:config.SOURCE_MAX_QUERIES] or [brief]


def source_section(project: Project, section: Section,
                   on_event: Optional[Event] = None) -> tuple[Suggestion, list[MediaAsset]]:
    sid = section.id
    if project.rights_posture == "commercial_safe":
        return (Suggestion(section_id=sid, status="error",
                           error="commercial_safe: YouTube is uncleared and no stock sources "
                                 "are wired yet (M4). Switch the project to anything_goes."),
                [])

    pdir = storage.project_dir(project.id)
    sec_len = section.end - section.start
    clip_len = min(sec_len, config.SOURCE_MAX_CLIP_SECONDS)
    brief = section.visual_brief or section.text

    _emit(on_event, section_id=sid, msg="researching queries")
    queries = research_queries(section)
    _emit(on_event, section_id=sid, msg=f"queries: {', '.join(queries)}")

    assets: list[MediaAsset] = []
    candidates: list[Candidate] = []
    seen: set[str] = set()

    for q in queries:
        if len(candidates) >= config.SOURCE_MAX_CANDIDATES:
            break
        try:
            results = youtube.search(q, max_results=4, duration="short")
        except youtube.SourcingError as e:
            _emit(on_event, section_id=sid, msg=f"search failed: {e.reason}")
            continue

        for r in results:
            if len(candidates) >= config.SOURCE_MAX_CANDIDATES:
                break
            vid = r["video_id"]
            if vid in seen:
                continue
            seen.add(vid)

            asset = MediaAsset(kind="video", origin="youtube", name=r["title"],
                               source_url=r["url"], license="youtube_uncleared", quarantined=True)
            clip_rel = f"media/sourced/{asset.id}.mp4"
            _emit(on_event, section_id=sid, msg=f"fetching: {r['title'][:50]}")
            try:
                youtube.fetch_clip(vid, clip_len, pdir / clip_rel)
            except youtube.SourcingError as e:
                _emit(on_event, section_id=sid, msg=f"skip: {e.reason}")
                continue

            info = probe(pdir / clip_rel)
            frames = vision.sample_frames(pdir / clip_rel, pdir / "media/frames", n=3)
            _emit(on_event, section_id=sid, msg=f"verifying: {r['title'][:50]}")
            verdict = vision.verify_fit(frames, brief)

            asset.local_path = clip_rel
            asset.duration = clip_len
            asset.width, asset.height = info["width"], info["height"]
            asset.verify_score = verdict["fit_score"]
            assets.append(asset)

            thumb_rel = f"media/frames/{frames[0].name}" if frames else ""
            candidates.append(Candidate(
                asset_id=asset.id, source="youtube", title=r["title"],
                rationale=verdict["notes"], fit_score=verdict["fit_score"],
                thumb=thumb_rel, flags=verdict["flags"], quarantined=True,
            ))
            _emit(on_event, section_id=sid,
                  msg=f"candidate fit={verdict['fit_score']:.2f}: {r['title'][:50]}")

    candidates.sort(key=lambda c: c.fit_score, reverse=True)
    if candidates:
        sug = Suggestion(section_id=sid, status="ready", candidates=candidates,
                         recommended_index=0, queries=queries)
    else:
        sug = Suggestion(section_id=sid, status="error", queries=queries,
                         error="no usable clips found; try editing the visual brief")
    return sug, assets
