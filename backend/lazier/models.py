"""Data model. The Project is the single source of truth, serialized to
workspace/{id}/project.json. Mirrors notes/01-architecture/overview.md section 2."""

from __future__ import annotations

import time
import uuid
from typing import Literal, Optional

from pydantic import BaseModel, Field


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


# --- transcription -----------------------------------------------------------
class Word(BaseModel):
    text: str
    start: float
    end: float


class Transcript(BaseModel):
    language: str = ""
    duration: float = 0.0
    words: list[Word] = Field(default_factory=list)


class Segment(BaseModel):
    """Pass 1: deterministic split on silent gaps in the voice."""
    id: str = Field(default_factory=lambda: _id("seg"))
    start: float
    end: float
    text: str


class Section(BaseModel):
    """Pass 2: an LLM merges segments into coherent topic CHAPTERS. A section is the
    thematic grouping + navigation unit, NOT the visual unit (that's the Beat)."""
    id: str = Field(default_factory=lambda: _id("sec"))
    start: float
    end: float
    text: str
    topic_label: str = ""
    visual_brief: str = ""
    segment_ids: list[str] = Field(default_factory=list)


class Beat(BaseModel):
    """The VISUAL unit: a short chunk of narration (a few seconds) that gets its own
    clip, reactive to what's being said at that moment. Beats are built from pass-1
    segments coalesced to a minimum length, and live inside one section (chapter)."""
    id: str = Field(default_factory=lambda: _id("beat"))
    section_id: str
    start: float
    end: float
    text: str


# --- media + timeline --------------------------------------------------------
AssetKind = Literal["video", "image", "audio"]
AssetOrigin = Literal["upload", "pool", "youtube", "web", "pexels", "pixabay", "openverse",
                      "internet_archive", "mixkit", "imgflip", "coverr", "giphy",
                      "reddit", "imgur", "fal", "lucy"]


class MediaAsset(BaseModel):
    id: str = Field(default_factory=lambda: _id("ast"))
    kind: AssetKind
    origin: AssetOrigin = "upload"
    name: str = ""
    local_path: str = ""          # relative to the project dir
    source_url: str = ""
    license: str = "user_provided"
    duration: float = 0.0         # 0 for stills
    width: int = 0
    height: int = 0
    verify_score: Optional[float] = None
    quarantined: bool = False     # uncleared third-party IP (see media-sources.md)


class Transforms(BaseModel):
    scale: float = 1.0
    x: int = 0
    y: int = 0
    ken_burns: bool = False       # slow zoom for stills


class Effects(BaseModel):
    fade_in: float = 0.0
    fade_out: float = 0.0


class Clip(BaseModel):
    id: str = Field(default_factory=lambda: _id("clip"))
    track_id: str
    asset_id: str
    beat_id: Optional[str] = None      # set when a clip fills a transcript beat
    section_id: Optional[str] = None   # the beat's parent chapter
    cue_id: Optional[str] = None       # set when an audio clip fills a SoundCue
    timeline_start: float
    timeline_end: float
    source_in: float = 0.0
    source_out: Optional[float] = None   # None -> use full asset / clip length
    transforms: Transforms = Field(default_factory=Transforms)
    effects: Effects = Field(default_factory=Effects)
    z_order: int = 0
    # audio-clip controls (also used for a video clip's diegetic audio)
    gain: float = 1.0                  # per-clip linear gain, on top of the track gain
    duck: Optional[bool] = None        # None -> inherit the track's duck; else override
    align_offset: float = 0.0          # manual nudge (s): shift the sound earlier(-)/later(+)
    audio_enabled: bool = False        # a VIDEO clip: play its own audio (interview soundbite)


class Candidate(BaseModel):
    """One sourced option for a section. Carries a handle (asset_id) + light metadata
    + the verifier's score, never media bytes (tool-design rule 0)."""
    asset_id: str
    source: AssetOrigin = "youtube"
    title: str = ""
    rationale: str = ""
    fit_score: float = 0.0
    thumb: str = ""            # relative path to a sampled frame
    flags: list[str] = Field(default_factory=list)
    quarantined: bool = False


class BeatPlan(BaseModel):
    """The Visual Director's decision for one beat: what shot to look for and where.
    See notes/06-direction/visual-direction.md."""
    visual_register: str = ""               # literal|evidence|data|metaphor|reaction|archival|ambient|motif
    content_type: str = "youtube"           # youtube|web (image/meme/gen later)
    shot_brief: str = ""                    # concrete description of the intended shot
    search_terms: list[str] = Field(default_factory=list)
    time_window: Optional[str] = None       # e.g. "2025-06" or "2025-06-30" for news/evidence
    rationale: str = ""                     # director's reasoning (kept for the UI/tuning)


class Suggestion(BaseModel):
    id: str = Field(default_factory=lambda: _id("sug"))
    beat_id: str
    status: Literal["sourcing", "ready", "error", "empty"] = "empty"
    plan: Optional[BeatPlan] = None
    candidates: list[Candidate] = Field(default_factory=list)
    recommended_index: int = 0
    error: str = ""
    queries: list[str] = Field(default_factory=list)


# --- sound design (a second/third audio track, planned by the Sound Director) ----
SoundKind = Literal["music", "effect"]
SoundDynamics = Literal["swell", "stinger", "bed", "hit", "drone"]


class SoundCue(BaseModel):
    """The Sound Director's plan unit for the audio track: a moment that wants music or an
    SFX. Analogous to a Beat, but it can span, overlap silence, and carries kind/intent/
    anchor/dynamics. The fetcher sources candidates for it; one gets placed on an audio track."""
    id: str = Field(default_factory=lambda: _id("cue"))
    start: float
    end: float
    kind: SoundKind = "effect"
    intent: str = ""                 # build suspense | mystery | impact | warmth | comic beat
    brief: str = ""                  # what the sound should BE (fetcher + ear judge against it)
    search_terms: list[str] = Field(default_factory=list)
    anchor: float = 0.0              # timeline time its CLIMAX should land on (a beat boundary)
    dynamics: SoundDynamics = "bed"
    duck: bool = True                # duck under the voice (music beds yes; a punchy stinger no)
    rationale: str = ""


class SoundCandidate(BaseModel):
    """One sourced audio option for a cue (mirrors Candidate; carries a handle + light meta)."""
    asset_id: str
    source: AssetOrigin = "youtube"
    title: str = ""
    rationale: str = ""
    fit_score: float = 0.0
    duration: float = 0.0
    waveform: str = ""               # relative path to a waveform png (optional)
    license: str = ""
    flags: list[str] = Field(default_factory=list)


class SoundSuggestion(BaseModel):
    id: str = Field(default_factory=lambda: _id("ssug"))
    cue_id: str
    status: Literal["sourcing", "ready", "error", "empty"] = "empty"
    candidates: list[SoundCandidate] = Field(default_factory=list)
    recommended_index: int = 0
    error: str = ""
    queries: list[str] = Field(default_factory=list)


TrackKind = Literal["visual", "audio", "caption", "overlay"]


class Track(BaseModel):
    id: str = Field(default_factory=lambda: _id("trk"))
    name: str
    kind: TrackKind
    clips: list[Clip] = Field(default_factory=list)
    # audio-track only
    gain: float = 1.0
    duck: bool = False            # duck under the master VO at export


# --- project -----------------------------------------------------------------
RightsPosture = Literal["anything_goes", "commercial_safe"]


class Project(BaseModel):
    id: str = Field(default_factory=lambda: _id("prj"))
    name: str
    aspect_ratio: str = "16:9"
    width: int = 1920
    height: int = 1080
    fps: int = 30
    created_at: float = Field(default_factory=time.time)

    audio_asset_id: Optional[str] = None
    budget_cap: float = 5.0
    rights_posture: RightsPosture = "anything_goes"
    media_pool_path: Optional[str] = None
    tone: str = ""                          # Nate's tone/style intent (director context)
    reference_date: str = ""                # optional "video is about <date>" (news time-scoping)
    video_summary: str = ""                 # thesis/throughline, generated after transcription
    voice_enhance: bool = False             # apply the podcast vocal chain to the voice at render

    assets: dict[str, MediaAsset] = Field(default_factory=dict)
    transcript: Optional[Transcript] = None
    segments: list[Segment] = Field(default_factory=list)
    sections: list[Section] = Field(default_factory=list)
    beats: list[Beat] = Field(default_factory=list)
    suggestions: dict[str, Suggestion] = Field(default_factory=dict)  # keyed by beat_id
    sound_cues: list[SoundCue] = Field(default_factory=list)
    sound_suggestions: dict[str, SoundSuggestion] = Field(default_factory=dict)  # keyed by cue_id
    tracks: list[Track] = Field(default_factory=list)

    # --- helpers ---
    @property
    def duration(self) -> float:
        if self.transcript and self.transcript.duration:
            return self.transcript.duration
        a = self.audio_asset()
        return a.duration if a else 0.0

    def audio_asset(self) -> Optional[MediaAsset]:
        if self.audio_asset_id:
            return self.assets.get(self.audio_asset_id)
        return None

    def track(self, track_id: str) -> Optional[Track]:
        return next((t for t in self.tracks if t.id == track_id), None)

    def section(self, section_id: str) -> Optional[Section]:
        return next((s for s in self.sections if s.id == section_id), None)

    def beat(self, beat_id: str) -> Optional["Beat"]:
        return next((b for b in self.beats if b.id == beat_id), None)

    def visual_track(self) -> Optional[Track]:
        return next((t for t in self.tracks if t.kind == "visual"), None)

    def find_clip(self, clip_id: str) -> tuple[Optional[Track], Optional[Clip]]:
        for t in self.tracks:
            for c in t.clips:
                if c.id == clip_id:
                    return t, c
        return None, None

    def ensure_default_tracks(self) -> None:
        if not self.tracks:
            self.tracks = [
                Track(name="Visuals", kind="visual"),
                Track(name="Music", kind="audio", duck=True),
            ]

    def cue(self, cue_id: str) -> Optional["SoundCue"]:
        return next((c for c in self.sound_cues if c.id == cue_id), None)

    def audio_tracks(self) -> tuple[Track, Track]:
        """Return the (Music, SFX) audio tracks, creating whichever is missing. Music beds duck
        under the voice by default; the SFX track carries stingers/hits (per-clip duck decides)."""
        self.ensure_default_tracks()
        music = next((t for t in self.tracks if t.kind == "audio" and t.name == "Music"), None)
        if music is None:
            music = next((t for t in self.tracks if t.kind == "audio"), None)
        if music is None:
            music = Track(name="Music", kind="audio", duck=True)
            self.tracks.append(music)
        sfx = next((t for t in self.tracks if t.kind == "audio" and t.name == "SFX"), None)
        if sfx is None:
            sfx = Track(name="SFX", kind="audio", duck=False)
            self.tracks.append(sfx)
        return music, sfx
