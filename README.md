# lazier

Audio-driven autonomous video editor. Drop in audio, Whisper time-aligns it, the
timeline is sectioned by voice + topic, and you assemble a video against the audio
spine. M1 (the spine) is built; agent sourcing is M2+. See `notes/` for the plan.

## Requirements

- Python 3.11+, [uv](https://github.com/astral-sh/uv)
- Node 20+, npm
- ffmpeg + ffprobe on PATH (tested with ffmpeg 8.1)
- Whisper runs on **CPU by default** (no GPU libs needed). To use an NVIDIA GPU
  instead, install `nvidia-cublas-cu12` + `nvidia-cudnn-cu12` (~1GB) and set
  `LAZIER_WHISPER_DEVICE=cuda`. We never silently fall back between devices.

## Setup

```sh
# backend
cd backend
uv sync

# frontend
cd ../frontend
npm install
```

## Run

Two processes. Backend first:

```sh
cd backend
# pass-2 section merge uses an LLM over OpenRouter:
export OPENROUTER_API_KEY=sk-or-...        # PowerShell: $env:OPENROUTER_API_KEY="sk-or-..."
uv run uvicorn lazier.main:app --port 8000
```

Frontend:

```sh
cd frontend
npm run dev        # http://localhost:5173  (proxies /api, /files, /ws to :8000)
```

Open http://localhost:5173.

## What M1 does

1. Create a project (aspect ratio + rights posture chosen up front).
2. Upload audio. It becomes the timeline spine.
3. Transcribe → two-pass segmentation: pass 1 splits on silent gaps, pass 2 (LLM)
   merges into topic **sections**, each with a `visual_brief`. An `captions.srt` is
   written alongside.
4. Add your own clips/images to the media pool, select one, click a section to drop
   it onto the visual track at that section's timing.
5. Drag/resize clips on the multi-track timeline.
6. Render preview (low-res proxy) and Export (full-res mp4 + SRT), via ffmpeg, with
   background-music ducking under the voice when a music clip is on a ducked track.

## Config (env)

| Var | Default | Notes |
|---|---|---|
| `OPENROUTER_API_KEY` | — | required for pass-2 merge |
| `LAZIER_LLM_MODEL` | `moonshotai/kimi-k2.5` | any OpenRouter model |
| `LAZIER_WHISPER_MODEL` | `base` | ~1.3x realtime on CPU. `small`/`medium`/`large-v3` for accuracy, `tiny` for speed |
| `LAZIER_WHISPER_DEVICE` | `cpu` | `cuda` after installing the nvidia wheels |
| `LAZIER_WHISPER_COMPUTE` | `int8` | CPU-friendly |
| `LAZIER_WORKSPACE` | `../workspace` | per-project media + project.json |
| `LAZIER_SEGMENT_GAP` | `0.6` | pass-1 split threshold (s) |

## Status

- M1 verified: backend (project CRUD, ffmpeg export + proxy with ken-burns/fades/
  compositing/ducking) and frontend (React + xzdarcy timeline + wavesurfer, dark UI)
  both run. Whisper GPU path is wired but the cuDNN runtime on this box is unverified
  (no transcription run yet) — confirm cuDNN or use CPU on first transcribe.
