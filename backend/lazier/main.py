"""FastAPI app: project lifecycle, audio ingest, transcription + segmentation,
manual clip placement, and ffmpeg proxy/export. The M1 spine, fully wired."""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import (config, direction, render, segmentation, sounddirection, soundsourcing,
               sourcing, storage, transcribe, youtube)
from .media_probe import probe
from .models import (Beat, BeatPlan, Candidate, Clip, Effects, MediaAsset, Project, Section,
                     SoundCandidate, SoundCue, SoundSuggestion, Suggestion, Transforms)

_apply_lock = asyncio.Lock()

app = FastAPI(title="lazier", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5180", "http://127.0.0.1:5180"],
    allow_methods=["*"], allow_headers=["*"],
)
app.mount("/files", StaticFiles(directory=str(config.WORKSPACE)), name="files")


def _reconcile_orphaned_sourcing() -> int:
    """A 'sourcing' status is only valid while a job runs in THIS process. On a fresh start
    nothing is running, so any suggestion still marked 'sourcing' on disk is orphaned — its
    job died with a previous process or an interrupted restart. Reset those to 'error' so the
    beat's buttons re-enable instead of staying wedged forever."""
    fixed = 0
    for meta in storage.list_projects():
        try:
            p = storage.load(meta["id"])
        except Exception:
            continue
        changed = False
        for sug in p.suggestions.values():
            if sug.status == "sourcing":
                sug.status = "error"
                sug.error = "sourcing was interrupted (server restarted) — hit Re-source"
                changed = True
                fixed += 1
        if changed:
            storage.save(p)
    return fixed


@app.on_event("startup")
def _startup_reconcile() -> None:
    n = _reconcile_orphaned_sourcing()
    if n:
        print(f"[startup] reset {n} orphaned 'sourcing' suggestion(s)")


# --- websocket progress ------------------------------------------------------
class Hub:
    def __init__(self) -> None:
        self.peers: dict[str, set[WebSocket]] = {}

    async def join(self, pid: str, ws: WebSocket) -> None:
        await ws.accept()
        self.peers.setdefault(pid, set()).add(ws)

    def leave(self, pid: str, ws: WebSocket) -> None:
        self.peers.get(pid, set()).discard(ws)

    async def send(self, pid: str, msg: dict) -> None:
        for ws in list(self.peers.get(pid, set())):
            try:
                await ws.send_json(msg)
            except Exception:
                self.leave(pid, ws)


hub = Hub()


@app.websocket("/ws/{pid}")
async def ws_endpoint(ws: WebSocket, pid: str):
    await hub.join(pid, ws)
    try:
        while True:
            await ws.receive_text()  # keepalive; client never needs to send
    except WebSocketDisconnect:
        hub.leave(pid, ws)


# --- request bodies ----------------------------------------------------------
class CreateProject(BaseModel):
    name: str
    aspect_ratio: str = "16:9"
    fps: int = 30
    budget_cap: float = 5.0
    rights_posture: str = "anything_goes"
    media_pool_path: Optional[str] = None
    tone: str = ""
    reference_date: str = ""


class PlaceClip(BaseModel):
    track_id: str
    asset_id: str
    timeline_start: float
    timeline_end: Optional[float] = None
    source_in: float = 0.0
    source_out: Optional[float] = None
    ken_burns: Optional[bool] = None   # stills: slow zoom (default on for images)
    beat_id: Optional[str] = None      # link the clip to a beat so it shows in that slot
    section_id: Optional[str] = None


class UpdateClip(BaseModel):
    timeline_start: Optional[float] = None
    timeline_end: Optional[float] = None
    source_in: Optional[float] = None
    source_out: Optional[float] = None
    fade_in: Optional[float] = None
    fade_out: Optional[float] = None
    ken_burns: Optional[bool] = None
    gain: Optional[float] = None            # audio clip: per-clip linear gain
    duck: Optional[bool] = None             # audio clip: override track ducking
    align_offset: Optional[float] = None    # audio clip: manual timing nudge (s)
    audio_enabled: Optional[bool] = None    # video clip: play its own (diegetic) audio


# --- helpers -----------------------------------------------------------------
def _load(pid: str) -> Project:
    if not storage.exists(pid):
        raise HTTPException(404, f"no project {pid}")
    return storage.load(pid)


_IMG_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff"}


def _kind_for(filename: str, info: dict) -> str:
    # ffprobe reports a still image as a single-frame VIDEO stream, so trust the extension
    # for known image types first — otherwise every uploaded jpg/png becomes a "video".
    if Path(filename).suffix.lower() in _IMG_EXTS:
        return "image"
    if info.get("has_video"):
        return "video"
    if info.get("has_audio"):
        return "audio"
    return "image"


# --- project lifecycle -------------------------------------------------------
@app.get("/api/health")
def health():
    return {"ok": True, "whisper": f"{config.WHISPER_MODEL}/{config.WHISPER_DEVICE}/{config.WHISPER_COMPUTE}"}


@app.post("/api/projects")
def create_project(body: CreateProject):
    if body.aspect_ratio not in config.ASPECT_PRESETS:
        raise HTTPException(400, f"unknown aspect_ratio {body.aspect_ratio}")
    w, h = config.ASPECT_PRESETS[body.aspect_ratio]
    p = Project(name=body.name, aspect_ratio=body.aspect_ratio, width=w, height=h,
                fps=body.fps, budget_cap=body.budget_cap,
                rights_posture=body.rights_posture, media_pool_path=body.media_pool_path,
                tone=body.tone, reference_date=body.reference_date)
    p.ensure_default_tracks()
    storage.save(p)
    return p


@app.get("/api/projects")
def list_projects():
    return storage.list_projects()


@app.get("/api/projects/{pid}")
def get_project(pid: str):
    return _load(pid)


@app.delete("/api/projects/{pid}")
def delete_project(pid: str):
    if not storage.exists(pid):
        raise HTTPException(404, f"no project {pid}")
    shutil.rmtree(storage.project_dir(pid), ignore_errors=True)
    return {"ok": True}


# --- audio ingest ------------------------------------------------------------
@app.post("/api/projects/{pid}/audio")
async def upload_audio(pid: str, file: UploadFile = File(...)):
    p = _load(pid)
    storage.ensure_layout(pid)
    dest = storage.abs_path(pid, f"audio/{Path(file.filename).name}")
    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    info = probe(dest)
    if not info["has_audio"]:
        dest.unlink(missing_ok=True)
        raise HTTPException(400, "file has no audio stream")
    asset = MediaAsset(kind="audio", origin="upload", name=dest.name,
                       local_path=f"audio/{dest.name}", duration=info["duration"])
    p.assets[asset.id] = asset
    p.audio_asset_id = asset.id
    p.ensure_default_tracks()
    storage.save(p)
    return p


# --- transcription + segmentation -------------------------------------------
@app.post("/api/projects/{pid}/transcribe")
async def transcribe_project(pid: str, merge: bool = True):
    p = _load(pid)
    if not p.audio_asset_id:
        raise HTTPException(400, "upload audio first")
    loop = asyncio.get_running_loop()
    audio_path = storage.abs_path(pid, p.audio_asset().local_path)

    async def job():
        try:
            await hub.send(pid, {"stage": "transcribe", "status": "start"})

            def progress(frac: float, msg: str):
                asyncio.run_coroutine_threadsafe(
                    hub.send(pid, {"stage": "transcribe", "progress": frac, "msg": msg}), loop)

            transcript = await asyncio.to_thread(transcribe.transcribe, audio_path, progress)
            p.transcript = transcript
            await hub.send(pid, {"stage": "segment", "status": "running",
                                 "msg": "pass 1 (timing) + pass 2 (chapters) + beats"})
            segs, sections, beats = await asyncio.to_thread(segmentation.segment, transcript, merge)
            p.segments = segs
            p.sections = sections
            p.beats = beats
            # video summary (thesis + tone) for the director's context hierarchy
            await hub.send(pid, {"stage": "segment", "status": "running", "msg": "summarizing"})
            try:
                full_text = " ".join(w.text for w in transcript.words)
                summ = await asyncio.to_thread(direction.summarize_video, full_text)
                p.video_summary = summ.summary
                if not p.tone:
                    p.tone = summ.tone
            except Exception as e:  # optional director context; surface but don't block
                await hub.send(pid, {"stage": "source", "msg": f"summary skipped: {type(e).__name__}"})
            # re-transcription invalidates old sourcing: drop suggestions + sourced clips
            p.suggestions = {}
            for t in p.tracks:
                if t.kind == "visual":
                    t.clips = [c for c in t.clips if not c.beat_id and not c.section_id]
            render.write_srt(p)
            storage.save(p)
            await hub.send(pid, {"stage": "done", "segments": len(segs),
                                 "sections": len(sections), "beats": len(beats)})
        except Exception as e:  # surfaced with state, no silent fallback
            await hub.send(pid, {"stage": "error", "error": f"{type(e).__name__}: {e}"})

    asyncio.create_task(job())
    return {"status": "started"}


@app.post("/api/projects/{pid}/resegment")
async def resegment(pid: str, merge: bool = True):
    """Re-run chapters + beats on the existing transcript (no Whisper). For iterating on
    segmentation/beat logic. Clears suggestions and any sourced clips (beat ids change)."""
    p = _load(pid)
    if not p.segments:
        raise HTTPException(400, "transcribe first")
    loop = asyncio.get_running_loop()

    async def job():
        try:
            await hub.send(pid, {"stage": "segment", "status": "running", "msg": "re-segmenting chapters + beats"})
            sections, beats = await asyncio.to_thread(segmentation.chapters_and_beats, p.segments, merge)
            p.sections = sections
            p.beats = beats
            p.suggestions = {}
            for t in p.tracks:
                if t.kind == "visual":
                    t.clips = [c for c in t.clips if not c.beat_id and not c.section_id]
            render.write_srt(p)
            storage.save(p)
            await hub.send(pid, {"stage": "done", "sections": len(sections), "beats": len(beats)})
        except Exception as e:
            await hub.send(pid, {"stage": "error", "error": f"{type(e).__name__}: {e}"})

    asyncio.create_task(job())
    return {"status": "started"}


# --- own media ---------------------------------------------------------------
@app.post("/api/projects/{pid}/media")
async def upload_media(pid: str, file: UploadFile = File(...)):
    p = _load(pid)
    storage.ensure_layout(pid)
    dest = storage.abs_path(pid, f"media/{Path(file.filename).name}")
    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    info = probe(dest)
    kind = _kind_for(dest.name, info)
    asset = MediaAsset(kind=kind, origin="upload", name=dest.name,
                       local_path=f"media/{dest.name}", duration=info["duration"],
                       width=info["width"], height=info["height"])
    p.assets[asset.id] = asset
    storage.save(p)
    return asset


# --- clips -------------------------------------------------------------------
@app.post("/api/projects/{pid}/clips")
def place_clip(pid: str, body: PlaceClip):
    p = _load(pid)
    track = p.track(body.track_id)
    if not track:
        raise HTTPException(404, f"no track {body.track_id}")
    asset = p.assets.get(body.asset_id)
    if not asset:
        raise HTTPException(404, f"no asset {body.asset_id}")

    start = max(body.timeline_start, 0.0)
    if body.timeline_end is not None:
        end = body.timeline_end
    elif asset.kind == "image":
        end = start + 5.0
    elif asset.duration:
        end = start + asset.duration
    else:
        end = start + 5.0
    if end <= start:
        raise HTTPException(400, "timeline_end must be after timeline_start")

    clip = Clip(track_id=track.id, asset_id=asset.id, beat_id=body.beat_id,
                section_id=body.section_id, timeline_start=start, timeline_end=end,
                source_in=body.source_in, source_out=body.source_out)
    if asset.kind == "image":   # slow zoom on stills unless explicitly turned off
        clip.transforms.ken_burns = True if body.ken_burns is None else body.ken_burns
    if body.beat_id:            # a beat holds one clip — replace whatever was there
        track.clips = [c for c in track.clips if c.beat_id != body.beat_id]
        beat = p.beat(body.beat_id)   # reflect it as a candidate so the panel shows it, like URL paste
        if beat:
            thumb = asset.local_path if asset.kind == "image" else ""
            cand = Candidate(asset_id=asset.id, source=(asset.origin or "upload"),
                             title=asset.name or "your upload", rationale="your upload",
                             fit_score=0.85, thumb=thumb, flags=[])
            prev = p.suggestions.get(body.beat_id)
            keep = [c for c in prev.candidates if c.asset_id != asset.id] if prev else []
            plan = prev.plan if (prev and prev.plan) else BeatPlan(
                visual_register="literal", content_type="youtube", shot_brief=beat.text)
            p.suggestions[body.beat_id] = Suggestion(
                beat_id=body.beat_id, status="ready", plan=plan,
                candidates=[cand] + keep, recommended_index=0)
    track.clips.append(clip)
    _prune_orphan_clips(p)
    storage.save(p)
    return clip


@app.patch("/api/projects/{pid}/clips/{clip_id}")
def update_clip(pid: str, clip_id: str, body: UpdateClip):
    p = _load(pid)
    _, clip = p.find_clip(clip_id)
    if not clip:
        raise HTTPException(404, f"no clip {clip_id}")
    if body.timeline_start is not None:
        clip.timeline_start = max(body.timeline_start, 0.0)
    if body.timeline_end is not None:
        clip.timeline_end = body.timeline_end
    if body.source_in is not None:
        clip.source_in = body.source_in
    if body.source_out is not None:
        clip.source_out = body.source_out
    if body.fade_in is not None:
        clip.effects.fade_in = body.fade_in
    if body.fade_out is not None:
        clip.effects.fade_out = body.fade_out
    if body.ken_burns is not None:
        clip.transforms.ken_burns = body.ken_burns
    if body.gain is not None:
        clip.gain = max(body.gain, 0.0)
    if body.duck is not None:
        clip.duck = body.duck
    if body.align_offset is not None:
        clip.align_offset = body.align_offset
    if body.audio_enabled is not None:
        clip.audio_enabled = body.audio_enabled
    if clip.timeline_end <= clip.timeline_start:
        raise HTTPException(400, "timeline_end must be after timeline_start")
    storage.save(p)
    return clip


@app.delete("/api/projects/{pid}/clips/{clip_id}")
def delete_clip(pid: str, clip_id: str):
    p = _load(pid)
    track, clip = p.find_clip(clip_id)
    if not clip:
        raise HTTPException(404, f"no clip {clip_id}")
    track.clips = [c for c in track.clips if c.id != clip_id]
    storage.save(p)
    return {"ok": True}


# --- render ------------------------------------------------------------------
def _render_emitter(pid: str, kind: str, loop):
    """Push ffmpeg's 0..1 progress to the project's websocket from the render worker thread."""
    def emit(frac: float):
        asyncio.run_coroutine_threadsafe(
            hub.send(pid, {"stage": "render", "kind": kind, "progress": frac}), loop)
    return emit


@app.post("/api/projects/{pid}/render/proxy")
async def render_proxy(pid: str):
    p = _load(pid)
    loop = asyncio.get_running_loop()
    try:
        out = await asyncio.to_thread(render.render_proxy, p, _render_emitter(pid, "proxy", loop))
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    await hub.send(pid, {"stage": "render_done", "kind": "proxy"})
    return {"url": f"/files/{pid}/proxies/{out.name}"}


@app.post("/api/projects/{pid}/render/export")
async def render_export(pid: str):
    p = _load(pid)
    loop = asyncio.get_running_loop()
    try:
        res = await asyncio.to_thread(render.render_export, p, _render_emitter(pid, "export", loop))
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    await hub.send(pid, {"stage": "render_done", "kind": "export"})
    return {"video": f"/files/{pid}/{res['video']}", "srt": f"/files/{pid}/captions.srt"}


class VoiceEnhanceBody(BaseModel):
    enabled: bool


@app.post("/api/projects/{pid}/voice-enhance")
def set_voice_enhance(pid: str, body: VoiceEnhanceBody):
    """Toggle the podcast vocal chain — applied to the voice at render/export time."""
    p = _load(pid)
    p.voice_enhance = body.enabled
    storage.save(p)
    return p


@app.post("/api/projects/{pid}/shorts")
def make_short(pid: str):
    """Pick the best ~30s window (agent) and render one 9:16 captioned short to
    exports/shorts/. Synchronous — runs in the threadpool; a short is quick to render."""
    from . import shorts
    p = _load(pid)
    if not p.transcript or not p.transcript.words:
        raise HTTPException(400, "no word-level transcript for this project; re-transcribe first")
    try:
        plan = shorts.find_short(p)
        res = render.render_short(p, plan)
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    return {
        "video": f"/files/{pid}/{res['video']}",
        "caption_url": f"/files/{pid}/{res['caption']}",
        "hook": plan.hook_title, "social_caption": plan.social_caption,
        "start": res["start"], "end": res["end"], "duration": res["duration"],
        "style": plan.caption_style.model_dump(),
    }


@app.get("/api/projects/{pid}/chapters")
def get_chapters(pid: str):
    """YouTube-description chapters (M:SS Title per line) from the project's topic sections.
    Writes chapters.txt into the project folder and returns the text for copy-paste."""
    p = _load(pid)
    if not p.sections:
        raise HTTPException(400, "no sections yet; transcribe + segment first")
    path = render.write_chapters(p)
    return {"text": path.read_text(encoding="utf-8"), "file": f"/files/{pid}/{path.name}"}


# --- M2: sourcing (per BEAT) -------------------------------------------------
class AcceptBody(BaseModel):
    candidate_index: int = 0


class CaptureBody(BaseModel):
    url: str
    highlight: Optional[str] = None


class SourceBody(BaseModel):
    notes: str = ""   # Nate's optional direction for this run (user notes for the director)


def _beat_filled(project: Project, bid: str) -> bool:
    vt = project.visual_track()
    return bool(vt and any(c.beat_id == bid for c in vt.clips))


def _prune_orphan_clips(project: Project) -> None:
    """Drop visual clips NOT tied to a beat that overlap a beat-linked clip — leftovers from
    older placements that would double up on a beat's window. An orphan sitting on an
    otherwise-empty beat is kept (it's the only visual there)."""
    vt = project.visual_track()
    if not vt:
        return
    linked = [c for c in vt.clips if c.beat_id]
    vt.clips = [c for c in vt.clips if c.beat_id or not any(
        c.timeline_start < L.timeline_end and c.timeline_end > L.timeline_start for L in linked)]


def _place_candidate(project: Project, beat: Beat, cand: Candidate) -> None:
    vt = project.visual_track()
    if not vt:
        return
    vt.clips = [c for c in vt.clips if c.beat_id != beat.id]  # replace any existing
    asset = project.assets.get(cand.asset_id)
    beat_len = beat.end - beat.start
    so = min(asset.duration, beat_len) if asset and asset.duration else None
    clip = Clip(track_id=vt.id, asset_id=cand.asset_id, beat_id=beat.id,
                section_id=beat.section_id, timeline_start=beat.start,
                timeline_end=beat.end, source_in=0.0, source_out=so)
    if asset and asset.kind == "image":   # stills get slow zoom so they aren't dead frames
        clip.transforms.ken_burns = True
    vt.clips.append(clip)
    _prune_orphan_clips(project)


async def _apply(pid: str, sug: Suggestion, assets: list[MediaAsset], place: bool) -> None:
    """Merge a beat's sourcing result into the project under a lock (concurrency-safe)."""
    async with _apply_lock:
        p = storage.load(pid)
        for a in assets:
            p.assets[a.id] = a
        p.suggestions[sug.beat_id] = sug
        if place and sug.status == "ready" and sug.candidates:
            beat = p.beat(sug.beat_id)
            if beat:
                _place_candidate(p, beat, sug.candidates[sug.recommended_index])
        storage.save(p)


def _emitter(pid: str, loop):
    def ev(d: dict):
        asyncio.run_coroutine_threadsafe(hub.send(pid, {"stage": "source", **d}), loop)
    return ev


async def _source_section_beats(pid: str, section: Section, beat_ids: list[str],
                                notes: str, loop, sem: asyncio.Semaphore):
    """Run the Visual Director for one section, then source each planned beat."""
    ev = _emitter(pid, loop)
    p = storage.load(pid)
    await hub.send(pid, {"stage": "source", "msg": f"directing '{section.topic_label}'…"})
    try:
        plans = await asyncio.to_thread(direction.direct_section, p, section, beat_ids, notes)
    except Exception as e:
        for bid in beat_ids:
            await _apply(pid, Suggestion(beat_id=bid, status="error",
                                         error=f"director: {type(e).__name__}: {e}"), [], place=False)
            await hub.send(pid, {"stage": "error", "beat_id": bid, "error": f"director: {e}"})
        return

    async def one(bid: str):
        async with sem:
            beat, plan = p.beat(bid), plans.get(bid)
            if not beat or not plan:
                await _apply(pid, Suggestion(beat_id=bid, status="error", plan=plan,
                                             error="director produced no plan for this beat"),
                             [], place=False)
                return
            try:
                sug, assets = await asyncio.to_thread(sourcing.source_from_plan, p, beat, plan, ev)
                await _apply(pid, sug, assets, place=True)
                await hub.send(pid, {"stage": "source_done", "beat_id": bid,
                                     "status": sug.status, "candidates": len(sug.candidates)})
            except Exception as e:
                await _apply(pid, Suggestion(beat_id=bid, status="error", plan=plan,
                                             error=f"{type(e).__name__}: {e}"), [], place=False)
                await hub.send(pid, {"stage": "error", "beat_id": bid, "error": f"{type(e).__name__}: {e}"})

    await asyncio.gather(*[one(bid) for bid in beat_ids])


@app.post("/api/projects/{pid}/beats/{bid}/source")
async def source_one_beat(pid: str, bid: str, body: SourceBody = SourceBody()):
    p = _load(pid)
    beat = p.beat(bid)
    if not beat:
        raise HTTPException(404, f"no beat {bid}")
    section = p.section(beat.section_id)
    if not section:
        raise HTTPException(400, "beat has no section")
    p.suggestions[bid] = Suggestion(beat_id=bid, status="sourcing")
    storage.save(p)
    loop = asyncio.get_running_loop()
    sem = asyncio.Semaphore(config.SOURCE_CONCURRENCY)
    asyncio.create_task(_source_section_beats(pid, section, [bid], body.notes, loop, sem))
    return {"status": "started"}


@app.post("/api/projects/{pid}/source-all")
async def source_all(pid: str, body: SourceBody = SourceBody(), section_id: Optional[str] = None):
    """Direct + source every empty beat (optionally limited to one chapter)."""
    p = _load(pid)
    targets = [b for b in p.beats if not _beat_filled(p, b.id)
               and (section_id is None or b.section_id == section_id)]
    for b in targets:
        p.suggestions[b.id] = Suggestion(beat_id=b.id, status="sourcing")
    storage.save(p)
    loop = asyncio.get_running_loop()
    sem = asyncio.Semaphore(config.SOURCE_CONCURRENCY)

    by_section: dict[str, list[str]] = {}
    for b in targets:
        by_section.setdefault(b.section_id, []).append(b.id)

    async def job():
        await hub.send(pid, {"stage": "source_all_start", "count": len(targets)})
        for sid, bids in by_section.items():
            sec = p.section(sid)
            if sec:
                await _source_section_beats(pid, sec, bids, body.notes, loop, sem)
        await hub.send(pid, {"stage": "source_all_done"})

    asyncio.create_task(job())
    return {"status": "started", "beats": len(targets)}


@app.post("/api/projects/{pid}/beats/{bid}/capture")
async def capture_site(pid: str, bid: str, body: CaptureBody):
    p = _load(pid)
    beat = p.beat(bid)
    if not beat:
        raise HTTPException(404, f"no beat {bid}")
    p.suggestions[bid] = Suggestion(beat_id=bid, status="sourcing",
                                    candidates=(p.suggestions.get(bid).candidates if p.suggestions.get(bid) else []))
    storage.save(p)
    loop = asyncio.get_running_loop()

    async def job():
        ev = _emitter(pid, loop)
        try:
            sug, assets = await asyncio.to_thread(
                sourcing.capture_from_url, p, beat, body.url, body.highlight, ev)
            await _apply(pid, sug, assets, place=True)
            await hub.send(pid, {"stage": "source_done", "beat_id": bid,
                                 "status": sug.status, "candidates": len(sug.candidates)})
        except Exception as e:
            # reset the beat's suggestion to error (NOT left at 'sourcing') so Find/Add re-enable
            prev = p.suggestions.get(bid)
            await _apply(pid, Suggestion(beat_id=bid, status="error",
                                         plan=(prev.plan if prev else None),
                                         candidates=(prev.candidates if prev else []),
                                         error=f"{type(e).__name__}: {e}"), [], place=False)
            await hub.send(pid, {"stage": "error", "beat_id": bid, "error": f"{type(e).__name__}: {e}"})

    asyncio.create_task(job())
    return {"status": "started"}


@app.post("/api/projects/{pid}/beats/{bid}/accept")
def accept_candidate(pid: str, bid: str, body: AcceptBody):
    p = _load(pid)
    sug = p.suggestions.get(bid)
    if not sug or not sug.candidates:
        raise HTTPException(404, "no suggestions for this beat")
    if not (0 <= body.candidate_index < len(sug.candidates)):
        raise HTTPException(400, "candidate_index out of range")
    sug.recommended_index = body.candidate_index
    beat = p.beat(bid)
    _place_candidate(p, beat, sug.candidates[body.candidate_index])
    storage.save(p)
    return p


class LucyBody(BaseModel):
    prompt: str


@app.post("/api/projects/{pid}/beats/{bid}/lucy")
async def make_lucy(pid: str, bid: str, body: LucyBody):
    """Generate an animated explainer clip (Lucy) for this beat from a prompt. Additive
    candidate, like a URL paste. Starts Lucy's server on demand."""
    p = _load(pid)
    beat = p.beat(bid)
    if not beat:
        raise HTTPException(404, f"no beat {bid}")
    if not body.prompt.strip():
        raise HTTPException(400, "prompt is required")
    prev = p.suggestions.get(bid)
    p.suggestions[bid] = Suggestion(beat_id=bid, status="sourcing",
                                    candidates=(prev.candidates if prev else []))
    storage.save(p)
    loop = asyncio.get_running_loop()

    async def job():
        ev = _emitter(pid, loop)
        try:
            plan = BeatPlan(visual_register="motif", content_type="lucy",
                            shot_brief=body.prompt.strip())
            sug, assets = await asyncio.to_thread(sourcing.source_lucy, p, beat, plan, ev)
            # keep any earlier candidates alongside the generated one (additive)
            if sug.status == "ready" and prev and prev.candidates:
                sug.candidates = sug.candidates + [c for c in prev.candidates
                                                   if c.asset_id != sug.candidates[0].asset_id]
            await _apply(pid, sug, assets, place=True)
            await hub.send(pid, {"stage": "source_done", "beat_id": bid,
                                 "status": sug.status, "candidates": len(sug.candidates)})
        except Exception as e:
            pv = p.suggestions.get(bid)
            await _apply(pid, Suggestion(beat_id=bid, status="error",
                                         candidates=(pv.candidates if pv else []),
                                         error=f"{type(e).__name__}: {e}"), [], place=False)
            await hub.send(pid, {"stage": "error", "beat_id": bid, "error": f"{type(e).__name__}: {e}"})

    asyncio.create_task(job())
    return {"status": "started"}


# --- sound design (music + SFX cues on the audio tracks) ---------------------
# Default placement gains: a music bed sits well under the voice; an SFX one-shot a bit louder.
_MUSIC_GAIN, _SFX_GAIN = 0.45, 0.8


def _cue_placed(project: Project, cue_id: str) -> bool:
    return any(c.cue_id == cue_id for t in project.tracks if t.kind == "audio" for c in t.clips)


def _place_sound_candidate(project: Project, cue: SoundCue, cand: SoundCandidate) -> None:
    """Place one sound candidate onto the Music or SFX track (by cue.kind), replacing whatever
    filled this cue. Starts at the cue's beat boundary (v1 alignment); align_offset nudges it."""
    music, sfx = project.audio_tracks()
    track = music if cue.kind == "music" else sfx
    for t in (music, sfx):                       # a cue lives on exactly one track
        t.clips = [c for c in t.clips if c.cue_id != cue.id]
    asset = project.assets.get(cand.asset_id)
    span = max(cue.end - cue.start, 0.2)
    so = min(asset.duration, span) if asset and asset.duration else span
    clip = Clip(track_id=track.id, asset_id=cand.asset_id, cue_id=cue.id,
                timeline_start=cue.start, timeline_end=cue.start + so,
                source_in=0.0, source_out=so, duck=cue.duck,
                gain=_MUSIC_GAIN if cue.kind == "music" else _SFX_GAIN)
    if cue.kind == "music" and so >= 1.0:        # ease beds in/out so they don't pop
        clip.effects.fade_in = min(1.0, so / 3)
        clip.effects.fade_out = min(1.5, so / 3)
    track.clips.append(clip)


async def _apply_sound(pid: str, sug: SoundSuggestion, assets: list[MediaAsset], place: bool) -> None:
    async with _apply_lock:
        p = storage.load(pid)
        for a in assets:
            p.assets[a.id] = a
        p.sound_suggestions[sug.cue_id] = sug
        if place and sug.status == "ready" and sug.candidates:
            cue = p.cue(sug.cue_id)
            if cue:
                _place_sound_candidate(p, cue, sug.candidates[sug.recommended_index])
        storage.save(p)


def _sound_emitter(pid: str, loop):
    def ev(d: dict):
        asyncio.run_coroutine_threadsafe(hub.send(pid, {"stage": "sound", **d}), loop)
    return ev


@app.post("/api/projects/{pid}/sound/plan")
async def plan_sound(pid: str, body: SourceBody = SourceBody()):
    """Run the Sound Director over the whole video → a sparse set of SoundCues. Async
    (one LLM call); results arrive over the websocket. Clears prior cues + their clips."""
    p = _load(pid)
    if not p.beats:
        raise HTTPException(400, "no beats yet; transcribe + segment first")
    loop = asyncio.get_running_loop()

    async def job():
        try:
            await hub.send(pid, {"stage": "sound", "status": "planning", "msg": "sound director…"})
            cues = await asyncio.to_thread(sounddirection.plan_sound, p, body.notes)
            async with _apply_lock:
                fresh = storage.load(pid)
                fresh.audio_tracks()                     # ensure Music + SFX exist
                for t in fresh.tracks:                   # drop old cue-linked clips
                    if t.kind == "audio":
                        t.clips = [c for c in t.clips if not c.cue_id]
                fresh.sound_cues = cues
                fresh.sound_suggestions = {}
                storage.save(fresh)
            await hub.send(pid, {"stage": "sound_planned", "cues": len(cues)})
        except Exception as e:
            await hub.send(pid, {"stage": "error", "error": f"sound director: {type(e).__name__}: {e}"})

    asyncio.create_task(job())
    return {"status": "started"}


async def _source_cue(pid: str, cue: SoundCue, loop, sem: asyncio.Semaphore) -> None:
    ev = _sound_emitter(pid, loop)
    async with sem:
        p = storage.load(pid)
        try:
            sug, assets = await asyncio.to_thread(soundsourcing.source_cue, p, cue, ev)
            await _apply_sound(pid, sug, assets, place=True)
            await hub.send(pid, {"stage": "sound_done", "cue_id": cue.id,
                                 "status": sug.status, "candidates": len(sug.candidates)})
        except Exception as e:
            await _apply_sound(pid, SoundSuggestion(cue_id=cue.id, status="error",
                                                    error=f"{type(e).__name__}: {e}"), [], place=False)
            await hub.send(pid, {"stage": "error", "cue_id": cue.id, "error": f"{type(e).__name__}: {e}"})


@app.post("/api/projects/{pid}/cues/{cid}/source")
async def source_one_cue(pid: str, cid: str):
    p = _load(pid)
    cue = p.cue(cid)
    if not cue:
        raise HTTPException(404, f"no cue {cid}")
    p.sound_suggestions[cid] = SoundSuggestion(cue_id=cid, status="sourcing")
    storage.save(p)
    loop = asyncio.get_running_loop()
    sem = asyncio.Semaphore(config.SOURCE_CONCURRENCY)
    asyncio.create_task(_source_cue(pid, cue, loop, sem))
    return {"status": "started"}


@app.post("/api/projects/{pid}/sound/source-all")
async def sound_source_all(pid: str, body: SourceBody = SourceBody()):
    """Plan (if no cues yet) then fetch audio for every cue that isn't already filled."""
    p = _load(pid)
    if not p.beats:
        raise HTTPException(400, "no beats yet; transcribe + segment first")
    loop = asyncio.get_running_loop()
    sem = asyncio.Semaphore(config.SOURCE_CONCURRENCY)

    async def job():
        try:
            proj = storage.load(pid)
            if not proj.sound_cues:
                await hub.send(pid, {"stage": "sound", "status": "planning", "msg": "sound director…"})
                cues = await asyncio.to_thread(sounddirection.plan_sound, proj, body.notes)
                async with _apply_lock:
                    fresh = storage.load(pid)
                    fresh.audio_tracks()
                    for t in fresh.tracks:
                        if t.kind == "audio":
                            t.clips = [c for c in t.clips if not c.cue_id]
                    fresh.sound_cues = cues
                    fresh.sound_suggestions = {}
                    storage.save(fresh)
                await hub.send(pid, {"stage": "sound_planned", "cues": len(cues)})
                proj = storage.load(pid)
            targets = [c for c in proj.sound_cues if not _cue_placed(proj, c.id)]
            for c in targets:
                proj.sound_suggestions[c.id] = SoundSuggestion(cue_id=c.id, status="sourcing")
            storage.save(proj)
            await hub.send(pid, {"stage": "sound_all_start", "count": len(targets)})
            await asyncio.gather(*[_source_cue(pid, c, loop, sem) for c in targets])
            await hub.send(pid, {"stage": "sound_all_done"})
        except Exception as e:
            await hub.send(pid, {"stage": "error", "error": f"{type(e).__name__}: {e}"})

    asyncio.create_task(job())
    return {"status": "started"}


@app.post("/api/projects/{pid}/cues/{cid}/accept")
def accept_sound_candidate(pid: str, cid: str, body: AcceptBody):
    p = _load(pid)
    sug = p.sound_suggestions.get(cid)
    if not sug or not sug.candidates:
        raise HTTPException(404, "no sound suggestions for this cue")
    if not (0 <= body.candidate_index < len(sug.candidates)):
        raise HTTPException(400, "candidate_index out of range")
    sug.recommended_index = body.candidate_index
    cue = p.cue(cid)
    _place_sound_candidate(p, cue, sug.candidates[body.candidate_index])
    storage.save(p)
    return p


class SoundUrlBody(BaseModel):
    url: str


@app.post("/api/projects/{pid}/cues/{cid}/capture")
async def capture_sound_url(pid: str, cid: str, body: SoundUrlBody):
    """Paste a YouTube URL for a cue: pull its audio at the ?t= timestamp as a candidate."""
    p = _load(pid)
    cue = p.cue(cid)
    if not cue:
        raise HTTPException(404, f"no cue {cid}")
    if not youtube.parse_youtube_url(body.url):
        raise HTTPException(400, "not a YouTube URL")
    p.sound_suggestions[cid] = SoundSuggestion(cue_id=cid, status="sourcing",
                                               candidates=(p.sound_suggestions.get(cid).candidates
                                                           if p.sound_suggestions.get(cid) else []))
    storage.save(p)
    loop = asyncio.get_running_loop()

    async def job():
        ev = _sound_emitter(pid, loop)
        try:
            sug, assets = await asyncio.to_thread(soundsourcing.capture_sound_url, p, cue, body.url, ev)
            await _apply_sound(pid, sug, assets, place=True)
            await hub.send(pid, {"stage": "sound_done", "cue_id": cid,
                                 "status": sug.status, "candidates": len(sug.candidates)})
        except Exception as e:
            prev = p.sound_suggestions.get(cid)
            await _apply_sound(pid, SoundSuggestion(cue_id=cid, status="error",
                                                    candidates=(prev.candidates if prev else []),
                                                    error=f"{type(e).__name__}: {e}"), [], place=False)
            await hub.send(pid, {"stage": "error", "cue_id": cid, "error": f"{type(e).__name__}: {e}"})

    asyncio.create_task(job())
    return {"status": "started"}
