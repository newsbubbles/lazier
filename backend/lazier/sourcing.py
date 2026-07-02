"""Sourcer: execute a BeatPlan from the Visual Director. The director decides register +
content_type + shot_brief + search_terms + time_window (see direction.py); this module
just fetches candidates for that shot and verifies them AGAINST THE SHOT BRIEF (so a
metaphor that fulfills the brief scores high even if it doesn't match the words).

Heavy IO runs here and RETURNS results; the caller applies them to the project under a
lock, so concurrent source-all runs don't race on project.json."""

from __future__ import annotations

import datetime as _dt
from typing import Callable, Optional

from . import config, serper, storage, vision, webcapture, youtube
from .media_probe import probe
from .models import Beat, BeatPlan, Candidate, MediaAsset, Project, Suggestion

Event = Callable[[dict], None]


def _emit(on_event: Optional[Event], **kw) -> None:
    if on_event:
        on_event(kw)


# --- time scoping ------------------------------------------------------------
def _time_bounds(tw: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """A YYYY / YYYY-MM / YYYY-MM-DD window -> (published_after, published_before) RFC3339."""
    if not tw:
        return None, None
    tw = tw.strip()
    try:
        if len(tw) == 4:
            y = int(tw); start, end = _dt.date(y, 1, 1), _dt.date(y, 12, 31)
        elif len(tw) == 7:
            y, m = map(int, tw.split("-"))
            start = _dt.date(y, m, 1)
            nm = _dt.date(y + (m == 12), 1 if m == 12 else m + 1, 1)
            end = nm - _dt.timedelta(days=1)
        elif len(tw) == 10:
            d = _dt.date.fromisoformat(tw)
            start, end = d - _dt.timedelta(days=3), d + _dt.timedelta(days=3)
        else:
            return None, None
    except (ValueError, TypeError):
        return None, None
    return start.isoformat() + "T00:00:00Z", end.isoformat() + "T23:59:59Z"


def _tbs(tw: Optional[str]) -> Optional[str]:
    a, b = _time_bounds(tw)
    if not a or not b:
        return None
    sa, sb = _dt.date.fromisoformat(a[:10]), _dt.date.fromisoformat(b[:10])
    return f"cdr:1,cd_min:{sa.month}/{sa.day}/{sa.year},cd_max:{sb.month}/{sb.day}/{sb.year}"


# --- web capture candidate ---------------------------------------------------
def _capture_candidate(project: Project, beat: Beat, url: str, title: str,
                       highlight: Optional[str], on_event: Optional[Event],
                       verify: bool, brief: str) -> tuple[Candidate, MediaAsset]:
    pdir = storage.project_dir(project.id)
    clip_len = min(beat.end - beat.start, config.SOURCE_MAX_CLIP_SECONDS)
    asset = MediaAsset(kind="video", origin="web", name=title or url,
                       source_url=url, license="web_capture")
    clip_rel = f"media/sourced/{asset.id}.mp4"
    _emit(on_event, beat_id=beat.id, msg=f"capturing site: {url[:50]}")
    webcapture.capture_scroll(url, pdir / clip_rel, clip_len, highlight=highlight)
    info = probe(pdir / clip_rel)
    frames = vision.sample_frames(pdir / clip_rel, pdir / "media/frames", n=3)
    if verify:
        v = vision.verify_fit(frames, brief)
        score, notes, flags = v["fit_score"], v["notes"], v["flags"]
    else:
        score, notes, flags = 0.85, "page you chose", []
    asset.local_path = clip_rel
    asset.duration = clip_len
    asset.width, asset.height = info["width"], info["height"]
    asset.verify_score = score
    thumb_rel = f"media/frames/{frames[0].name}" if frames else ""
    cand = Candidate(asset_id=asset.id, source="web", title=title or url, rationale=notes,
                     fit_score=score, thumb=thumb_rel, flags=flags, quarantined=False)
    return cand, asset


# --- execute a plan ----------------------------------------------------------
def source_from_plan(project: Project, beat: Beat, plan: BeatPlan,
                     on_event: Optional[Event] = None) -> tuple[Suggestion, list[MediaAsset]]:
    bid = beat.id
    if project.rights_posture == "commercial_safe":
        return (Suggestion(beat_id=bid, status="error", plan=plan,
                           error="commercial_safe: YouTube/web are uncleared and no stock "
                                 "sources are wired yet. Switch to anything_goes."), [])

    pdir = storage.project_dir(project.id)
    clip_len = min(beat.end - beat.start, config.SOURCE_MAX_CLIP_SECONDS)
    brief = plan.shot_brief or beat.text
    terms = plan.search_terms or [beat.text[:60]]
    _emit(on_event, beat_id=bid, msg=f"[{plan.visual_register}/{plan.content_type}] {brief[:50]}")

    assets: list[MediaAsset] = []
    candidates: list[Candidate] = []

    if plan.content_type == "web":
        tbs = _tbs(plan.time_window)
        for q in terms:
            if candidates:
                break
            try:
                results = serper.search(q, num=4, tbs=tbs)
            except Exception as e:
                _emit(on_event, beat_id=bid, msg=f"web search failed: {e}")
                continue
            for r in results:
                try:
                    cand, asset = _capture_candidate(project, beat, r["url"], r["title"],
                                                     brief, on_event, verify=True, brief=brief)
                    candidates.append(cand); assets.append(asset)
                    break
                except youtube.SourcingError as e:
                    _emit(on_event, beat_id=bid, msg=f"skip site: {e.reason}")
                    continue
    else:  # youtube
        after, before = _time_bounds(plan.time_window)
        seen: set[str] = set()
        for q in terms:
            if len(candidates) >= config.SOURCE_MAX_CANDIDATES:
                break
            try:
                results = youtube.search(q, max_results=4, duration="short",
                                         published_after=after, published_before=before)
            except youtube.SourcingError as e:
                _emit(on_event, beat_id=bid, msg=f"search failed: {e.reason}")
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
                _emit(on_event, beat_id=bid, msg=f"fetching: {r['title'][:44]}")
                try:
                    youtube.fetch_clip(vid, clip_len, pdir / clip_rel)
                except youtube.SourcingError as e:
                    _emit(on_event, beat_id=bid, msg=f"skip: {e.reason}")
                    continue
                info = probe(pdir / clip_rel)
                frames = vision.sample_frames(pdir / clip_rel, pdir / "media/frames", n=3)
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
                    thumb=thumb_rel, flags=verdict["flags"], quarantined=True))
                _emit(on_event, beat_id=bid, msg=f"fit={verdict['fit_score']:.2f}: {r['title'][:40]}")

    candidates.sort(key=lambda c: c.fit_score, reverse=True)
    if candidates:
        return Suggestion(beat_id=bid, status="ready", plan=plan, candidates=candidates,
                          recommended_index=0, queries=terms), assets
    return Suggestion(beat_id=bid, status="error", plan=plan, queries=terms,
                      error="no usable media found for this shot; tweak notes or re-source"), assets


# --- manual per-beat: paste a YouTube URL (quota-free, direct clip) -----------
def clip_youtube_url(project: Project, beat: Beat, url: str,
                     on_event: Optional[Event] = None) -> tuple[Suggestion, list[MediaAsset]]:
    """Clip a pasted YouTube URL directly at its timestamp — NO search.list call, so no
    quota. Additive to the beat's candidates (like capture_url); verify is skipped because
    the user chose it. `fetch_clip` already supports the start offset."""
    parsed = youtube.parse_youtube_url(url)
    if not parsed:
        raise youtube.SourcingError("not a valid YouTube URL",
                                    "check the link, or paste a site URL to scroll-capture it")
    video_id, start_at = parsed
    pdir = storage.project_dir(project.id)
    clip_len = min(beat.end - beat.start, config.SOURCE_MAX_CLIP_SECONDS)
    asset = MediaAsset(kind="video", origin="youtube", name=f"YouTube {video_id}",
                       source_url=url, license="youtube_uncleared", quarantined=True)
    clip_rel = f"media/sourced/{asset.id}.mp4"
    _emit(on_event, beat_id=beat.id, msg=f"clipping youtube {video_id} @ {start_at:.0f}s")
    youtube.fetch_clip(video_id, clip_len, pdir / clip_rel, start_at=start_at)
    info = probe(pdir / clip_rel)
    frames = vision.sample_frames(pdir / clip_rel, pdir / "media/frames", n=1)
    asset.local_path = clip_rel
    asset.duration = clip_len
    asset.width, asset.height = info["width"], info["height"]
    asset.verify_score = 0.85
    thumb_rel = f"media/frames/{frames[0].name}" if frames else ""
    cand = Candidate(asset_id=asset.id, source="youtube", title=asset.name,
                     rationale=f"pasted by you (from {start_at:.0f}s)", fit_score=0.85,
                     thumb=thumb_rel, flags=[], quarantined=True)
    existing = project.suggestions.get(beat.id)
    cands = ([cand] + existing.candidates) if existing else [cand]
    plan = (existing.plan if existing and existing.plan
            else BeatPlan(visual_register="literal", content_type="youtube", shot_brief=beat.text))
    sug = Suggestion(beat_id=beat.id, status="ready", plan=plan, candidates=cands,
                     recommended_index=0)
    return sug, [asset]


def capture_from_url(project: Project, beat: Beat, url: str, highlight: Optional[str] = None,
                     on_event: Optional[Event] = None) -> tuple[Suggestion, list[MediaAsset]]:
    """One paste box, two behaviors: a YouTube link is clipped directly at its timestamp;
    anything else is scroll-captured as a page."""
    if youtube.parse_youtube_url(url):
        return clip_youtube_url(project, beat, url, on_event)
    return capture_url(project, beat, url, highlight)


# --- manual per-beat URL capture ---------------------------------------------
def capture_url(project: Project, beat: Beat, url: str,
                highlight: Optional[str] = None) -> tuple[Suggestion, list[MediaAsset]]:
    cand, asset = _capture_candidate(project, beat, url, url, highlight, None,
                                     verify=False, brief=beat.text)
    existing = project.suggestions.get(beat.id)
    cands = ([cand] + existing.candidates) if existing else [cand]
    plan = (existing.plan if existing and existing.plan
            else BeatPlan(visual_register="evidence", content_type="web", shot_brief=beat.text))
    sug = Suggestion(beat_id=beat.id, status="ready", plan=plan, candidates=cands,
                     recommended_index=0)
    return sug, [asset]
