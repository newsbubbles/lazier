"""Vision verification: sample frames from a clip and score how well it fits a
section's visual brief, via an OpenRouter VLM through pydantic-ai. Fused sample+score
(tool-design principle 6): the agent gets a validated verdict, never the frames — and
the verdict is a Pydantic model, no JSON parsing."""

from __future__ import annotations

import subprocess
from pathlib import Path

from pydantic import BaseModel, Field

from . import config
from .agents import run_agent


def sample_frames(video_path: Path, out_dir: Path, n: int = 3) -> list[Path]:
    """Extract n frames spread across the clip. Returns saved jpg paths."""
    out_dir.mkdir(parents=True, exist_ok=True)
    pr = subprocess.run([config.FFPROBE, "-v", "error", "-show_entries", "format=duration",
                         "-of", "default=nw=1:nk=1", str(video_path)],
                        capture_output=True, text=True)
    try:
        dur = float(pr.stdout.strip())
    except ValueError:
        dur = 0.0
    stem = video_path.stem
    frames: list[Path] = []
    for i in range(n):
        t = (dur * (i + 1) / (n + 1)) if dur > 0 else i
        fp = out_dir / f"{stem}_f{i}.jpg"
        subprocess.run([config.FFMPEG, "-y", "-ss", f"{t:.2f}", "-i", str(video_path),
                        "-frames:v", "1", "-vf", "scale=320:-1", str(fp)],
                       capture_output=True, text=True)
        if fp.exists():
            frames.append(fp)
    return frames


_SYSTEM = (
    "You verify whether b-roll footage fits a narration moment. You are shown a few frames "
    "sampled from one video clip and a 'visual brief' describing what should be on screen. "
    "Score the fit 0..1 and flag problems. Be strict: a clip only loosely related scores low. "
    "HARD FAIL (fit_score at or near 0, flag 'not_content') when the frames are NOT real "
    "content but a login/sign-in wall, a cookie/consent banner, a paywall, an error or "
    "'access denied' page, a blank/placeholder, or mostly browser/UI chrome. "
    "Valid flags: has_watermark, has_burned_text, letterboxed, low_quality, off_topic, "
    "people_talking, not_content."
)


class Verdict(BaseModel):
    fit_score: float = Field(ge=0.0, le=1.0)
    notes: str = ""
    flags: list[str] = Field(default_factory=list)


def verify_fit(frames: list[Path], visual_brief: str) -> dict:
    """Returns {fit_score, notes, flags}. Runs the VLM via pydantic-ai with the frames as
    image parts; the Verdict model is validated (and retried) by pydantic-ai."""
    if not frames:
        return {"fit_score": 0.0, "notes": "no frames could be sampled", "flags": ["low_quality"]}
    from pydantic_ai import BinaryContent

    parts: list = [f"Visual brief: {visual_brief}\n\nScore how well these frames fit it."]
    for fr in frames:
        parts.append(BinaryContent(data=fr.read_bytes(), media_type="image/jpeg"))

    v = run_agent(_SYSTEM, parts, Verdict, model_name=config.VLM_MODEL)
    return {"fit_score": v.fit_score, "notes": v.notes[:300], "flags": [str(f) for f in v.flags][:8]}
