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
    """Pass 2: an LLM merges adjacent segments into coherent topic sections.
    This is the unit the sourcing agents will work on in later milestones."""
    id: str = Field(default_factory=lambda: _id("sec"))
    start: float
    end: float
    text: str
    topic_label: str = ""
    visual_brief: str = ""
    segment_ids: list[str] = Field(default_factory=list)


# --- media + timeline --------------------------------------------------------
AssetKind = Literal["video", "image", "audio"]
AssetOrigin = Literal["upload", "pool", "youtube", "pexels", "pixabay", "openverse",
                      "internet_archive", "mixkit", "imgflip", "coverr", "giphy",
                      "reddit", "imgur", "fal"]


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
    section_id: Optional[str] = None   # set when a clip fills a transcript section
    timeline_start: float
    timeline_end: float
    source_in: float = 0.0
    source_out: Optional[float] = None   # None -> use full asset / clip length
    transforms: Transforms = Field(default_factory=Transforms)
    effects: Effects = Field(default_factory=Effects)
    z_order: int = 0


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


class Suggestion(BaseModel):
    id: str = Field(default_factory=lambda: _id("sug"))
    section_id: str
    status: Literal["sourcing", "ready", "error", "empty"] = "empty"
    candidates: list[Candidate] = Field(default_factory=list)
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

    assets: dict[str, MediaAsset] = Field(default_factory=dict)
    transcript: Optional[Transcript] = None
    segments: list[Segment] = Field(default_factory=list)
    sections: list[Section] = Field(default_factory=list)
    suggestions: dict[str, Suggestion] = Field(default_factory=dict)  # keyed by section_id
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
