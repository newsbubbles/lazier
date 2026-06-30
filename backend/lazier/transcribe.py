"""Local Whisper transcription via faster-whisper (CTranslate2). Word-level
timestamps drive the whole timeline. Model is lazy-loaded and cached process-wide."""

from __future__ import annotations

import threading
from pathlib import Path

from . import config
from .models import Transcript, Word

_model = None
_lock = threading.Lock()


def _get_model():
    global _model
    if _model is None:
        with _lock:
            if _model is None:
                from faster_whisper import WhisperModel
                # No silent fallback: if CUDA/cuDNN isn't present this raises, and
                # the caller surfaces it. Set LAZIER_WHISPER_DEVICE=cpu to opt out.
                _model = WhisperModel(
                    config.WHISPER_MODEL,
                    device=config.WHISPER_DEVICE,
                    compute_type=config.WHISPER_COMPUTE,
                )
    return _model


def transcribe(audio_path: Path, on_progress=None) -> Transcript:
    """Transcribe with word timestamps. on_progress(frac, msg) is optional."""
    model = _get_model()
    segments, info = model.transcribe(
        str(audio_path),
        word_timestamps=True,
        vad_filter=True,
    )
    total = float(getattr(info, "duration", 0.0) or 0.0)

    words: list[Word] = []
    last_end = 0.0
    for seg in segments:  # generator: realized lazily as we iterate
        if seg.words:
            for w in seg.words:
                txt = (w.word or "").strip()
                if not txt:
                    continue
                words.append(Word(text=txt, start=round(w.start, 3), end=round(w.end, 3)))
                last_end = w.end
        else:
            words.append(Word(text=seg.text.strip(), start=round(seg.start, 3),
                              end=round(seg.end, 3)))
            last_end = seg.end
        if on_progress and total:
            on_progress(min(last_end / total, 0.99), f"transcribing… {last_end:.0f}s/{total:.0f}s")

    return Transcript(
        language=getattr(info, "language", "") or "",
        duration=total or last_end,
        words=words,
    )
