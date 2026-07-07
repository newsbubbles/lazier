# Changelog

All notable changes to lazier are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project aims to follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Work accumulates under **Unreleased** and is cut into a version when tagged.

## [Unreleased]

### Added
- **Sound design.** A **Sound Director** agent plans a sparse set of music beds + SFX cues
  over the whole video (tone-matched, ducked under the voice, aligned to beat boundaries),
  fed a deterministic quiet-moment map so swells land in the silences. Sourced via **yt-dlp
  audio** (no key, license-gated by `rights_posture`); Freesound/Pixabay are pluggable once
  keyed. Music + SFX get their own reduced-height timeline rows and a **SoundPanel** (waveform
  audition, Find sounds, paste-URL, per-clip level / duck / timing-nudge). Render mixes the
  extra tracks with per-clip gain, fades, align-offset, and optional **diegetic video audio**.
- **Animated GIF support.** GIFs drop into the timeline and render animated — looped to fill
  the beat, ken-burns auto-skipped so they don't freeze — in both the export and shorts paths.
  (Previously a GIF errored the whole render, since images used `-loop 1`, which ffmpeg rejects
  for the gif demuxer.)
- Spacebar toggles timeline play/pause (ignored while typing in a text field).
- Editor screenshot in the README.

### Changed
- **Voice-enhance retuned to "Clarity".** The old chain cut low-mid warmth and boosted 4k/10k,
  which made a warm/dark voice sound tinny, plus heavy denoise artifacts. The new default keeps
  the natural warmth and adds only a gentle 2.8k presence lift, a touch of air, light de-ess,
  gentle compression, and loudnorm. Picked by ear from an 8-preset A/B. Env-overridable via
  `LAZIER_VOICE_CHAIN`.

### Fixed
- **yt-dlp clip fetch** no longer hangs for minutes or fails on throttled videos: a fast
  `--download-sections` grab first (hard-capped at 25s via a real process-tree kill that reaps
  the ffmpeg child), then a full-download-and-trim fallback when YouTube throttles the ranged
  request.
- Preview playback was silent for placed music/SFX: the editor played the voice-only master
  through the waveform while the proxy video (which holds the full mix) was muted. Now a
  rendered proxy plays its own audio and the waveform is muted, so the preview matches the
  export.

## [0.1.0] - 2026-07-02

First working baseline: drop in audio, get an auto-assembled, transcript-aligned b-roll
video out, then refine it on a real timeline.

### Added
- **Audio-driven core.** Local Whisper transcription + time-alignment, two-pass segmentation
  into topic **chapters** and per-moment **beats** (the visual unit is a speech chunk).
- **Aligned multi-track timeline** where the audio is the spine: waveform, chapters band,
  and one clip slot per beat on a shared time axis, with ctrl+wheel zoom, wheel pan, and
  auto-paging.
- **Live proxy preview** slaved to the audio clock — scrub or play and the video follows.
- **Visual Director**: plans each section as a sequence (visual register, content type,
  shot brief, search terms, time window per beat) and drives sourcing.
- **Sourcing**: YouTube clips (search + trimmed download) and web **scroll-capture** of a
  page with the moment's words highlighted; a VLM verifies each candidate against the brief.
- **Manual per-beat sourcing**: paste a YouTube link (with `t=` timestamp) for a direct,
  quota-free clip; "Use my own" upload with **ken-burns slow zoom** on stills; a per-beat
  **guidance** box that steers Find clips for just that moment. Additions stack as candidates.
- **Live-playing candidate previews** in the suggestion panel, synced to the timeline cursor.
- **YouTube chapter export** (`chapters.txt` + a "YT chapters" button that copies to clipboard).
- **Render + export** via ffmpeg with a live progress bar and spinners; SRT captions written
  alongside exports.
- **Responsive mobile layout** (side panels become drawers); the last proxy is restored on
  reload.
- **Launchers** (`launch.sh` / `launch.ps1`) that free the ports and start backend + frontend.

### Changed
- **Search moved off the YouTube Data API to yt-dlp** — no API key, no 100-searches/day
  quota — with a 14-day on-disk result cache that also dedupes repeated queries.
- Proxy preview now renders at **360p / 18fps / ultrafast** for fast iteration (export is
  unchanged at full quality).
- Director default model is **grok-4.20**; all agents use pydantic-ai typed output.
- Director search terms constrained to lean keywords (broad→specific), and shot briefs may no
  longer request screen layouts/composites (one full-frame clip per beat).
- Chapters made **flush** so the timeline tiles with no black gaps between sections.
- Ports pinned: **frontend 5180 / backend 5181** with `strictPort` so they never drift.

### Fixed
- Intermittent OpenRouter `finish_reason='error'` — force `provider.require_parameters` so it
  only routes to backends that support our structured output.
- Render failing on large projects (Windows 32k command-line limit) — filtergraph now passed
  via `-filter_complex_script`.
- Render hang from an undrained ffmpeg stderr pipe during progress streaming.
- "No usable media found" caused by over-specific search terms — plus a deterministic
  broadening fallback (retry with the first few keywords).
- Web-capture grabbing login walls / cookie banners — domain blacklist, junk-frame rejection
  by the verifier, and a scroll that dwells before panning.
- Playwright capture on Windows — runs in its own Proactor-loop subprocess.
