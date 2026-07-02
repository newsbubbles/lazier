# lazier

**Audio-driven, mostly-autonomous video editing.** Drop in an audio track (a script you
recorded, a VO, a podcast cut). lazier transcribes and time-aligns it locally, breaks it
into the moments you actually speak, and a fleet of background agents finds and places a
matching visual for each moment, on a real multi-track timeline where the **audio is the
spine and the transcript drives the clips**. You refine a finished draft instead of
building from a blank timeline.

It's the lazy path to a properly-edited faceless / explainer / b-roll video: the least
work for you, the highest-quality cut out.

## The problem it solves

Editing a talking video is mostly grunt work: transcribing, chopping the audio into
beats, hunting stock/YouTube/AI footage for each line, trimming clips to length, and
lining everything up to the words. Tools today either repurpose existing video (Opus
Clip), fill templates (InVideo), or just add captions (Submagic). None give you a real
NLE timeline **plus** autonomous, transcript-aligned source-gathering. lazier automates
the grunt work and leaves you the creative calls (swap this clip, keep that one).

## How it works

```
audio ─▶ Whisper (local, word-aligned)
      ─▶ pass 1: split on silences ─▶ pass 2 (LLM): merge into topic CHAPTERS
      ─▶ BEATS: coalesce into ~5s speech chunks (the visual unit)
      ─▶ per beat, agents source a clip:
           • research the moment's words ─▶ search queries
           • YouTube Data API search ─▶ yt-dlp trims the clip
           • web-capture: scroll-record a cited article/paper (Playwright)
           • vision-LLM verifies each candidate (fit score + flags)
           • rank ─▶ recommend one, keep alternates
      ─▶ aligned timeline: chapters band + beats as clip slots + waveform spine
      ─▶ ffmpeg renders proxy preview + final export (with music ducking) + SRT
```

Two ideas make it intuitive:

- **The transcript is the timeline.** Waveform, transcript ribbon, and the visual track
  share one time axis. A clip sits directly under the words it illustrates.
- **Beats, not chapters, are the visual unit.** A chapter is a topic; within it, each
  short speech chunk gets its own clip, reactive to what's being said at that moment, the
  way real edits cut every few seconds.

## Features

- **Local transcription** via faster-whisper (CPU by default, GPU optional), word-level
  timing, SRT always written.
- **Two-pass segmentation**: deterministic silence split, then an LLM merges into topic
  chapters with a per-chapter visual brief.
- **Autonomous sourcing per beat**, with sources:
  - **YouTube** — Data API search + yt-dlp section download/trim.
  - **Web-capture** — headless Chromium scroll-through of a cited page, highlighting the
    sentence you're saying. Auto-offered when a beat cites a source, or paste a URL.
  - **Your own media** — upload a clip/image for any beat.
- **Vision verification**: a VLM samples frames and scores each candidate's fit, flagging
  watermarks, burned-in text, off-topic, etc., so junk gets down-ranked.
- **Suggestion cards**: recommended pick + alternates per beat; Use / swap / re-source /
  upload-your-own.
- **One-click auto-assemble**: source every empty beat and watch the video fill in.
- **Aligned NLE timeline**: chapters + beats + waveform on one axis; click a beat or
  chapter to scrub the audio there; ctrl+wheel zoom, wheel-pan, auto-paging playhead.
- **Render**: ffmpeg proxy preview and full export (h264 + AAC), background-music ducking
  under the voice, ken-burns/fades.
- **Rights posture** per project: `anything_goes` (uncleared sources labeled) or
  `commercial_safe`.

## Stack

FastAPI + faster-whisper + ffmpeg + Playwright, agents on **OpenRouter**
(`moonshotai/kimi-k2.5` for text, `google/gemini-2.5-flash` for vision — no Anthropic
models). React + TypeScript frontend with a custom aligned timeline (wavesurfer.js for the
waveform). State is a `project.json` per project plus media on disk under `workspace/`.

## Requirements

- Python 3.11+, [uv](https://github.com/astral-sh/uv)
- Node 20+, npm
- ffmpeg + ffprobe on PATH (tested with ffmpeg 8.1)
- Playwright Chromium for web-capture: `uv run playwright install chromium` (~200MB)
- Whisper runs on **CPU by default** (no GPU libs needed). For an NVIDIA GPU, install
  `nvidia-cublas-cu12` + `nvidia-cudnn-cu12` (~1GB) and set `LAZIER_WHISPER_DEVICE=cuda`.
  We never silently fall back between devices.

## Setup

```sh
cd backend && uv sync && uv run playwright install chromium
cd ../frontend && npm install
```

Put your keys in `D:\lazier\.env` (auto-loaded; gitignored):

```
OPENROUTER_API_KEY=sk-or-...
YOUTUBE_API_KEY=AIza...       # YouTube Data API
SERPER_API_KEY=...            # web-capture URL discovery
FAL_KEY=...                   # reserved for AI image gen (later)
```

## Run

```sh
cd backend && uv run uvicorn lazier.main:app --port 5181      # API
cd frontend && npm run dev                                    # http://localhost:5180

# or just use the launcher (frees ports first, starts both):
./launch.sh            # bash (Git Bash / Linux / macOS)
.\launch.ps1           # Windows PowerShell
```

Open the frontend, create a project (pick aspect ratio + rights posture), upload audio,
Transcribe, then Auto-source (or click a beat and Find clips / paste a URL). Render
preview, then Export.

## Config (env)

| Var | Default | Notes |
|---|---|---|
| `OPENROUTER_API_KEY` | — | required (text + vision agents) |
| `LAZIER_LLM_MODEL` | `moonshotai/kimi-k2.5` | text agents |
| `LAZIER_VLM_MODEL` | `google/gemini-2.5-flash` | clip verifier |
| `YOUTUBE_API_KEY` | — | YouTube search (100 searches/day free quota) |
| `SERPER_API_KEY` | — | web-capture URL discovery |
| `LAZIER_WHISPER_MODEL` | `base` | ~1.3x realtime on CPU; `small`/`large-v3` for accuracy, `tiny` for speed |
| `LAZIER_WHISPER_DEVICE` | `cpu` | `cuda` after installing the nvidia wheels |
| `LAZIER_BEAT_MIN_SECONDS` | `5.0` | min beat length (cut cadence) |
| `LAZIER_WEB_CAPTURE_AUTO` | `1` | auto-offer a site capture when a beat cites a source |
| `LAZIER_WORKSPACE` | `../workspace` | per-project media + project.json (gitignored) |

## Status

Built and verified: M1 (transcribe → two-pass segmentation → aligned timeline → ffmpeg
export), M2 (per-beat YouTube + web-capture sourcing, vision verification, suggestion
cards, auto-assemble), and M3 (proxy preview synced live to the audio clock — scrub or
play the timeline and the muted proxy video follows; dense-keyframe proxy for snappy
seeks). Next: incremental chunked proxy cache (re-render only edited regions).

See `notes/` for the architecture and design decisions.
