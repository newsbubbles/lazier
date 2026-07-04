# Podcast vocal chain — broadcast-quality narration, automatically

## Goal
Make the narration spine sound like a produced podcast: clean, present, warm, and at a
consistent loudness — so faceless videos + shorts sound professional with zero manual audio
work. Applied to the VOICE spine; music still mixes under it via the existing ducking.

## Approach: ONE ffmpeg `-af` chain (no new deps)
ffmpeg has every stage of a standard vocal chain natively, so the whole thing is a single
audio filtergraph. This matches lazier's ffmpeg-everything stack — no pedalboard/VST/py-audio
dependency. (Upgrade path later: swap `afftdn` for `arnndn` RNNoise, or move to `pedalboard`
if we ever want VST-grade processing.)

**Critical invariant: every stage is TIME-PRESERVING** (no time-stretch, no resample-drift).
The transcript's word timings + beats stay valid, so processing doesn't invalidate anything
downstream. (Ideally transcribe AFTER processing — clean audio = marginally better Whisper
timing — but order is safe either way.)

## The chain (the "Podcast" preset, in order)
1. **High-pass ~85Hz** (`highpass`) — kill rumble, AC hum, plosive thumps below the voice.
2. **Broadband denoise** (`afftdn`, gentle/voice-safe) — reduce hiss/room tone.
3. **De-ess** (`deesser`) — tame 5–8kHz sibilance.
4. **EQ** (`equalizer` + shelves): cut mud ~200–400Hz, presence boost ~3–5kHz, air shelf
   ~10kHz. Subtle, corrective.
5. **Compressor** (`acompressor`, ~3:1, voice attack/release) — even out dynamics. Optionally
   2-stage (a slow leveler + a faster glue comp).
6. *(optional)* subtle saturation for warmth.
7. **Loudness normalize** (`loudnorm`, **two-pass** — measure then apply) to a target, then
   `alimiter` as a true-peak safety.

Concrete starting graph (params live in config, tunable):
```
highpass=f=85,
afftdn=nr=12:nf=-25,
deesser=i=0.35,
equalizer=f=250:t=q:w=1.0:g=-3,
equalizer=f=4000:t=q:w=1.5:g=3,
highshelf=f=10000:g=2,
acompressor=threshold=-18dB:ratio=3:attack=15:release=160:makeup=5,
loudnorm=I=-14:TP=-1:LRA=11,     # pass 2 uses measured_* from pass 1
alimiter=limit=0.95
```

## Where it fits in the pipeline
- **Process at ingest** into a derived master (`audio/processed.<ext>`), **keep the raw**.
  Point the project's `audio_asset_id` at the processed asset (raw stays in `assets` for
  revert). Then transcribe + proxy + export + shorts ALL use it automatically — they already
  read `project.audio_asset()`, so **no downstream code changes**.
- Non-destructive, re-runnable, and a toggle to flip back to raw. A/B preview (raw vs
  processed snippet) is a nice-to-have.
- Process the **voice-only spine**, not the final mix — so music sits under a clean, leveled
  voice (matches how real podcasts master the VO, then mix).

## Backend
- `audiochain.py`: `process_voice(in_path, out_path, preset)` → builds the `-af` graph, runs
  the two-pass loudnorm (measure → apply), returns the processed path. Preset dict in config.
- `POST /projects/{pid}/process-audio` (body: preset): process the raw master → new processed
  asset → set `audio_asset_id` → save → return project. Plus revert-to-raw.
- Config: `VOCAL_PRESETS` (param sets), `AUDIO_LUFS_TARGET=-14`, `AUDIO_TP=-1`.

## UI (Audio spine panel)
- "Enhance voice" toggle + preset dropdown + re-process button; show which master is active
  (raw / processed). Optional small A/B play of a snippet.

## Decisions to confirm (Nate)
1. **Loudness target**: **-14 LUFS** (YouTube/shorts normalize here — recommend) vs -16 LUFS
   (classic podcast). Output is YT + shorts, so -14.
2. **Denoise engine**: `afftdn` (built-in, no model file — recommend to start) vs `arnndn`
   (RNNoise, better, needs a bundled model).
3. **When**: explicit toggle (default ON, visible + reversible — recommend) vs silent
   auto-process on upload.
4. **Presets**: ship one solid "Podcast" first; add Warm/Bright/Aggressive later.

## Smoke test
Process an existing project's audio (e.g. "Apps are Dead" `home_cooked_apps.mp3`), A/B
before/after, confirm integrated loudness lands ~-14 LUFS (read `loudnorm`/`ebur128` output),
verify no timing drift (duration identical), and that proxy/export use the processed master.

## Effort
Small–medium. The chain is one ffmpeg call; the rest is a processing step + asset swap + a
toggle. ~½–1 day, no new dependencies.
```
