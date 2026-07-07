"""Runtime configuration. Everything is env-overridable; defaults target THIS box
(GTX 1080 Pascal 8GB -> faster-whisper large-v3 INT8) per notes/02-agents/tool-design.md."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# On Windows the default ProactorEventLoop throws "WinError 6: handle is invalid" when
# torn down after each pydantic-ai run_sync (overlapped-I/O cleanup bug), which hangs the
# many-call segmentation/sourcing pipeline. SelectorEventLoop has no such teardown bug and
# handles httpx fine. Set the policy at import (before any loop is created).
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# --- paths -------------------------------------------------------------------
BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_DIR.parent  # D:\lazier

# Load consolidated keys: D:\lazier\.env first, then backend/.env (overrides), then
# any real process env wins (we never override an explicitly-set var).
load_dotenv(PROJECT_ROOT / ".env")
load_dotenv(BACKEND_DIR / ".env", override=True)

WORKSPACE = Path(os.environ.get("LAZIER_WORKSPACE", PROJECT_ROOT / "workspace"))
WORKSPACE.mkdir(parents=True, exist_ok=True)

# --- whisper -----------------------------------------------------------------
# Running on CPU by choice (this box has only the NVIDIA driver, no CUDA libs, and
# we're not installing the ~1GB cuBLAS/cuDNN wheels). CPU int8 needs no GPU libs.
# Benchmarked on this 8-thread CPU: base ~1.3x realtime (default), small ~0.45x,
# tiny ~2.3x. 'base' is the sweet spot of speed + word-timing accuracy. Bump
# LAZIER_WHISPER_MODEL to 'small'/'medium'/'large-v3' for accuracy if you'll wait,
# or 'tiny' for speed. Threads stay auto (forcing 8 oversubscribed and got slower).
# To switch to the GPU later: install nvidia-cublas-cu12 + nvidia-cudnn-cu12 and set
# LAZIER_WHISPER_DEVICE=cuda. We never silently fall back between devices.
WHISPER_MODEL = os.environ.get("LAZIER_WHISPER_MODEL", "base")
WHISPER_DEVICE = os.environ.get("LAZIER_WHISPER_DEVICE", "cpu")
WHISPER_COMPUTE = os.environ.get("LAZIER_WHISPER_COMPUTE", "int8")

# Pass-1 segmentation: split when the silent gap between words exceeds this (seconds).
SEGMENT_GAP_SECONDS = float(os.environ.get("LAZIER_SEGMENT_GAP", "0.6"))
# Beats = visual units. Pass A makes flush speech-timing beats (one per phrase); an
# agent then MERGES adjacent phrases that share one visual, guarded by max: a merge is
# rejected if the resulting beat would exceed BEAT_MAX_SECONDS. min is the target size,
# max the hard ceiling (forced to at least 2x min so merges are always possible).
BEAT_MIN_SECONDS = float(os.environ.get("LAZIER_BEAT_MIN_SECONDS", "5.0"))
BEAT_MAX_SECONDS = max(float(os.environ.get("LAZIER_BEAT_MAX_SECONDS", "12.0")),
                       2 * BEAT_MIN_SECONDS)

# --- llm (OpenRouter, OpenAI-compatible) -------------------------------------
# Default to Nate's non-anthropic pick. Pass-2 section merge needs this; pass-1
# works without it. Missing key -> clear error at call time, never a fallback.
OPENROUTER_BASE_URL = os.environ.get("LAZIER_LLM_BASE_URL", "https://openrouter.ai/api/v1")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
# All lazier agents are structural extraction (segment/query/web-intent/scoring), not
# open reasoning — so a fast model with reliable native structured output wins. Measured:
# gemini-2.5-flash pass-2 = 9s + consistent; kimi-k2.5 = 35-98s + inconsistent chapter
# counts. Override with LAZIER_LLM_MODEL to force kimi/grok if you prefer.
LLM_MODEL = os.environ.get("LAZIER_LLM_MODEL", "google/gemini-2.5-flash")
VLM_MODEL = os.environ.get("LAZIER_VLM_MODEL", "google/gemini-2.5-flash")
# The Visual Director is the one agent where reasoning quality beats speed. A/B on one
# Neurocracy section: grok-4.20 = 5s + 4/5 register variety + metaphor (fastest of all);
# gemini-flash = 10s + 5/5; kimi-k2-thinking = 21s + 3/5; kimi-k2.5 = 59s + 1/5 (unusable).
# grok-4.20 wins on speed+quality (and it's Nate's vendor). Override via env.
DIRECTOR_MODEL = os.environ.get("LAZIER_DIRECTOR_MODEL", "x-ai/grok-4.20")

# --- sourcing (M2) -----------------------------------------------------------
YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "")
# Clip fetch is two-tier (see youtube._fetch): a fast --download-sections grab first, then a
# full-download-and-trim fallback only if that's throttled/fails.
# SECTION_TIMEOUT hard-caps the fast attempt (tree-killed) so a throttled section can't hang.
SOURCE_SECTION_TIMEOUT = int(os.environ.get("LAZIER_SOURCE_SECTION_TIMEOUT", "25"))
SOURCE_FULL_TIMEOUT = int(os.environ.get("LAZIER_SOURCE_FULL_TIMEOUT", "300"))
# Section grab uses native res (it's only the slice); the full-download fallback is capped
# lower to bound the whole-file download size.
SOURCE_MAX_HEIGHT = int(os.environ.get("LAZIER_SOURCE_MAX_HEIGHT", "1080"))
SOURCE_FALLBACK_HEIGHT = int(os.environ.get("LAZIER_SOURCE_FALLBACK_HEIGHT", "720"))
SERPER_API_KEY = os.environ.get("SERPER_API_KEY", "")
FAL_KEY = os.environ.get("FAL_KEY", "")
# Per section: how many queries, how many clips to actually fetch+verify.
SOURCE_MAX_QUERIES = int(os.environ.get("LAZIER_SOURCE_MAX_QUERIES", "2"))
SOURCE_MAX_CANDIDATES = int(os.environ.get("LAZIER_SOURCE_MAX_CANDIDATES", "3"))
SOURCE_MAX_CLIP_SECONDS = float(os.environ.get("LAZIER_SOURCE_MAX_CLIP_SECONDS", "12"))
SOURCE_CONCURRENCY = int(os.environ.get("LAZIER_SOURCE_CONCURRENCY", "2"))
# Web capture (Playwright): auto-offer a site scroll-through when a beat references
# an article/paper/news. Manual per-beat capture is always available.
WEB_CAPTURE_AUTO = os.environ.get("LAZIER_WEB_CAPTURE_AUTO", "1") not in ("0", "false", "")
# Headed Chromium (off-screen window) is harder for bot-walls to detect than headless.
CAPTURE_HEADED = os.environ.get("LAZIER_CAPTURE_HEADED", "0") not in ("0", "false", "")

# --- ffmpeg ------------------------------------------------------------------
FFMPEG = os.environ.get("LAZIER_FFMPEG", "ffmpeg")
FFPROBE = os.environ.get("LAZIER_FFPROBE", "ffprobe")
PROXY_HEIGHT = int(os.environ.get("LAZIER_PROXY_HEIGHT", "360"))
PROXY_FPS = int(os.environ.get("LAZIER_PROXY_FPS", "18"))   # preview only; lower = faster encode

# shorts (vertical clips for Shorts / Reels / TikTok)
SHORTS_W = int(os.environ.get("LAZIER_SHORTS_W", "1080"))
SHORTS_H = int(os.environ.get("LAZIER_SHORTS_H", "1920"))
SHORTS_TARGET_SECONDS = float(os.environ.get("LAZIER_SHORTS_TARGET", "30"))
SHORTS_MIN_SECONDS = float(os.environ.get("LAZIER_SHORTS_MIN", "15"))
SHORTS_MAX_SECONDS = float(os.environ.get("LAZIER_SHORTS_MAX", "60"))
SHORTS_MODEL = os.environ.get("LAZIER_SHORTS_MODEL", DIRECTOR_MODEL)

# Vocal chain — applied to the voice spine at render when project.voice_enhance. This is the
# "Clarity" preset Nate picked from the A/B test, tuned for a WARM/DARK voice (energy in
# 120-1k, weak natural presence): rumble filter -> a gentle presence lift at 2.8k for
# intelligibility + a touch of air -> light de-ess -> gentle compression -> loudnorm -> limiter.
# Deliberately NO low-mid cut and NO aggressive denoise/high boost — those made it tinny.
AUDIO_LUFS = float(os.environ.get("LAZIER_AUDIO_LUFS", "-14"))   # YouTube/shorts target
_DEFAULT_VOICE_CHAIN = (
    "highpass=f=80,"
    "equalizer=f=2800:t=q:w=1.6:g=2.5,highshelf=f=11000:g=1.5,"
    "deesser=i=0.2,"
    "acompressor=threshold=-20dB:ratio=2.5:attack=20:release=180:makeup=3,"
    f"loudnorm=I={AUDIO_LUFS}:TP=-1.5:LRA=10,alimiter=limit=0.96")
VOICE_CHAIN = os.environ.get("LAZIER_VOICE_CHAIN", _DEFAULT_VOICE_CHAIN)

# --- canvas presets ----------------------------------------------------------
ASPECT_PRESETS: dict[str, tuple[int, int]] = {
    "16:9": (1920, 1080),
    "9:16": (1080, 1920),
    "1:1": (1080, 1080),
    "4:5": (1080, 1350),
}
