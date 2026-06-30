"""Vision verification: sample frames from a clip and score how well it fits a
section's visual brief, via an OpenRouter VLM. Fused sample+score (tool-design
principle 6): the agent gets a verdict, never the frames."""

from __future__ import annotations

import base64
import json
import subprocess
from pathlib import Path

from openai import OpenAI

from . import config


def _client() -> OpenAI:
    if not config.OPENROUTER_API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY not set (needed for vision verify)")
    return OpenAI(base_url=config.OPENROUTER_BASE_URL, api_key=config.OPENROUTER_API_KEY,
                  default_headers={"HTTP-Referer": "https://lazier.local", "X-Title": "lazier"})


def sample_frames(video_path: Path, out_dir: Path, n: int = 3) -> list[Path]:
    """Extract n frames spread across the clip. Returns saved jpg paths."""
    out_dir.mkdir(parents=True, exist_ok=True)
    # probe duration
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


def _data_url(p: Path) -> str:
    b64 = base64.b64encode(p.read_bytes()).decode()
    return f"data:image/jpeg;base64,{b64}"


_SYSTEM = (
    "You verify whether b-roll footage fits a narration moment. You are shown a few "
    "frames sampled from one video clip and a 'visual brief' describing what should be "
    "on screen. Score the fit and flag problems. Be strict: a clip that is only loosely "
    "related scores low."
)


def verify_fit(frames: list[Path], visual_brief: str) -> dict:
    """Returns {fit_score: 0..1, notes: str, flags: [..]}. flags from:
    has_watermark, has_burned_text, letterboxed, low_quality, off_topic, people_talking."""
    if not frames:
        return {"fit_score": 0.0, "notes": "no frames could be sampled", "flags": ["low_quality"]}
    content: list = [{
        "type": "text",
        "text": (f"Visual brief: {visual_brief}\n\n"
                 'Reply with JSON only: {"fit_score": 0..1, "notes": "<short>", '
                 '"flags": ["has_watermark"|"has_burned_text"|"letterboxed"|"low_quality"'
                 '|"off_topic"|"people_talking"...]}'),
    }]
    for fr in frames:
        content.append({"type": "image_url", "image_url": {"url": _data_url(fr)}})

    resp = _client().chat.completions.create(
        model=config.VLM_MODEL,
        messages=[{"role": "system", "content": _SYSTEM},
                  {"role": "user", "content": content}],
        response_format={"type": "json_object"},
        temperature=0.1,
    )
    data = json.loads(resp.choices[0].message.content or "{}")
    score = float(data.get("fit_score", 0.0))
    return {
        "fit_score": max(0.0, min(1.0, score)),
        "notes": str(data.get("notes", ""))[:300],
        "flags": [str(f) for f in data.get("flags", [])][:8],
    }
