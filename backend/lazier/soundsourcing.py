"""Sound fetcher: execute a SoundCue from the Sound Director. The director decides kind +
intent + brief + search_terms (see sounddirection.py); this module fetches audio candidates
for that cue and returns them. No placement judgement here — the caller places one under a
lock, mirroring sourcing.py for the visual side.

v1 source = yt-dlp AUDIO (no API key, no quota) — reuses youtube.fetch_audio. Freesound
(SFX, CC0) + Pixabay Audio (music) are the key-gated additive sources once keys land in
.env; the license gate follows project.rights_posture exactly like the video sourcer."""

from __future__ import annotations

import subprocess
from typing import Callable, Optional

from . import config, storage, youtube
from .media_probe import probe
from .models import MediaAsset, Project, SoundCandidate, SoundCue, SoundSuggestion

Event = Callable[[dict], None]

# How much of a music bed / effect to actually fetch. Beds fill the cue span; effects are short.
_EFFECT_MAX_SECONDS = 6.0
_MUSIC_MAX_SECONDS = 30.0


def _emit(on_event: Optional[Event], **kw) -> None:
    if on_event:
        on_event(kw)


def _fetch_seconds(cue: SoundCue) -> float:
    span = max(cue.end - cue.start, 1.0)
    cap = _EFFECT_MAX_SECONDS if cue.kind == "effect" else _MUSIC_MAX_SECONDS
    return min(span, cap)


def _waveform(project: Project, asset_id: str, media_path) -> str:
    """Render a small waveform png so the panel can show the sound without playing it."""
    rel = f"media/waveforms/{asset_id}.png"
    out = storage.project_dir(project.id) / rel
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [config.FFMPEG, "-y", "-i", str(media_path),
           "-filter_complex", "aformat=channel_layouts=mono,"
           "showwavespic=s=480x80:colors=#8ab4f8", "-frames:v", "1", str(out)]
    res = subprocess.run(cmd, capture_output=True, text=True)
    return rel if res.returncode == 0 and out.exists() else ""


def source_cue(project: Project, cue: SoundCue,
               on_event: Optional[Event] = None) -> tuple[SoundSuggestion, list[MediaAsset]]:
    """Fetch audio candidates for one cue. Returns (SoundSuggestion, new assets)."""
    cid = cue.id
    if project.rights_posture == "commercial_safe":
        return (SoundSuggestion(cue_id=cid, status="error",
                                error="commercial_safe: yt-dlp audio is uncleared and no CC0 "
                                      "stock source is wired yet. Switch to anything_goes or add "
                                      "a Freesound/Pixabay key."), [])

    pdir = storage.project_dir(project.id)
    terms = cue.search_terms or [cue.brief or cue.intent]
    # broaden an over-specific query to its first 3 words, same trick as the video sourcer
    queries = list(terms)
    for q in terms:
        b = " ".join(q.split()[:3])
        if b and b != q and b not in queries:
            queries.append(b)

    want = _fetch_seconds(cue)
    _emit(on_event, cue_id=cid, msg=f"[{cue.kind}/{cue.dynamics}] {cue.brief[:48]}")

    assets: list[MediaAsset] = []
    candidates: list[SoundCandidate] = []
    seen: set[str] = set()
    for q in queries:
        if len(candidates) >= config.SOURCE_MAX_CANDIDATES:
            break
        try:
            results = youtube.search(q, max_results=4)
        except youtube.SourcingError as e:
            _emit(on_event, cue_id=cid, msg=f"search failed: {e.reason}")
            continue
        for r in results:
            if len(candidates) >= config.SOURCE_MAX_CANDIDATES:
                break
            vid = r["video_id"]
            if vid in seen:
                continue
            seen.add(vid)
            asset = MediaAsset(kind="audio", origin="youtube", name=r["title"],
                               source_url=r["url"], license="youtube_uncleared", quarantined=True)
            rel = f"media/sounds/{asset.id}.m4a"
            _emit(on_event, cue_id=cid, msg=f"fetching: {r['title'][:44]}")
            try:
                youtube.fetch_audio(vid, want, pdir / rel)
            except youtube.SourcingError as e:
                _emit(on_event, cue_id=cid, msg=f"skip: {e.reason}")
                continue
            info = probe(pdir / rel)
            if not info["has_audio"] or info["duration"] < 0.3:
                continue
            asset.local_path = rel
            asset.duration = info["duration"]
            wf = _waveform(project, asset.id, pdir / rel)
            assets.append(asset)
            candidates.append(SoundCandidate(
                asset_id=asset.id, source="youtube", title=r["title"],
                rationale=f"{cue.intent}", fit_score=0.8, duration=info["duration"],
                waveform=wf, license="youtube_uncleared", flags=["uncleared"]))
            _emit(on_event, cue_id=cid, msg=f"got {info['duration']:.1f}s: {r['title'][:40]}")

    if candidates:
        return SoundSuggestion(cue_id=cid, status="ready", candidates=candidates,
                               recommended_index=0, queries=terms), assets
    return SoundSuggestion(cue_id=cid, status="error", queries=terms,
                           error="no usable audio found for this cue; tweak the brief or "
                                 "paste a YouTube URL"), assets


def capture_sound_url(project: Project, cue: SoundCue, url: str,
                      on_event: Optional[Event] = None) -> tuple[SoundSuggestion, list[MediaAsset]]:
    """Pull audio from a pasted YouTube URL (at its ?t= start) as an additive cue candidate."""
    parsed = youtube.parse_youtube_url(url)
    if not parsed:
        raise youtube.SourcingError("not a valid YouTube URL", "paste a YouTube link")
    vid, start_at = parsed
    pdir = storage.project_dir(project.id)
    want = _fetch_seconds(cue)
    asset = MediaAsset(kind="audio", origin="youtube", name=f"YouTube {vid}",
                       source_url=url, license="youtube_uncleared", quarantined=True)
    rel = f"media/sounds/{asset.id}.m4a"
    _emit(on_event, cue_id=cue.id, msg=f"pulling audio {vid} @ {start_at:.0f}s")
    youtube.fetch_audio(vid, want, pdir / rel, start_at=start_at)
    info = probe(pdir / rel)
    asset.local_path = rel
    asset.duration = info["duration"]
    wf = _waveform(project, asset.id, pdir / rel)
    cand = SoundCandidate(asset_id=asset.id, source="youtube", title=asset.name,
                          rationale=f"pasted by you (from {start_at:.0f}s)", fit_score=0.85,
                          duration=info["duration"], waveform=wf, license="youtube_uncleared")
    existing = project.sound_suggestions.get(cue.id)
    cands = ([cand] + existing.candidates) if existing else [cand]
    return SoundSuggestion(cue_id=cue.id, status="ready", candidates=cands,
                           recommended_index=0), [asset]
