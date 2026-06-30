"""Runtime configuration. Everything is env-overridable; defaults target THIS box
(GTX 1080 Pascal 8GB -> faster-whisper large-v3 INT8) per notes/02-agents/tool-design.md."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

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
# Beats = visual units. Coalesce segments within a chapter to at least this long, so
# each beat is a clip-sized chunk reactive to the moment (a cut every ~N seconds).
BEAT_MIN_SECONDS = float(os.environ.get("LAZIER_BEAT_MIN_SECONDS", "5.0"))

# --- llm (OpenRouter, OpenAI-compatible) -------------------------------------
# Default to Nate's non-anthropic pick. Pass-2 section merge needs this; pass-1
# works without it. Missing key -> clear error at call time, never a fallback.
OPENROUTER_BASE_URL = os.environ.get("LAZIER_LLM_BASE_URL", "https://openrouter.ai/api/v1")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
LLM_MODEL = os.environ.get("LAZIER_LLM_MODEL", "moonshotai/kimi-k2.5")
# Vision model for clip verification (frame scoring). Fast + cheap + strong vision.
VLM_MODEL = os.environ.get("LAZIER_VLM_MODEL", "google/gemini-2.5-flash")

# --- sourcing (M2) -----------------------------------------------------------
YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "")
SERPER_API_KEY = os.environ.get("SERPER_API_KEY", "")
FAL_KEY = os.environ.get("FAL_KEY", "")
# Per section: how many queries, how many clips to actually fetch+verify.
SOURCE_MAX_QUERIES = int(os.environ.get("LAZIER_SOURCE_MAX_QUERIES", "2"))
SOURCE_MAX_CANDIDATES = int(os.environ.get("LAZIER_SOURCE_MAX_CANDIDATES", "3"))
SOURCE_MAX_CLIP_SECONDS = float(os.environ.get("LAZIER_SOURCE_MAX_CLIP_SECONDS", "12"))
SOURCE_CONCURRENCY = int(os.environ.get("LAZIER_SOURCE_CONCURRENCY", "2"))

# --- ffmpeg ------------------------------------------------------------------
FFMPEG = os.environ.get("LAZIER_FFMPEG", "ffmpeg")
FFPROBE = os.environ.get("LAZIER_FFPROBE", "ffprobe")
PROXY_HEIGHT = int(os.environ.get("LAZIER_PROXY_HEIGHT", "480"))

# --- canvas presets ----------------------------------------------------------
ASPECT_PRESETS: dict[str, tuple[int, int]] = {
    "16:9": (1920, 1080),
    "9:16": (1080, 1920),
    "1:1": (1080, 1080),
    "4:5": (1080, 1350),
}
