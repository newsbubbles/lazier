# Manual per-beat sourcing — paste a YouTube URL, better image upload, additive clips

## Why
Two goals at once: (1) give the user direct manual control over a beat's visual, and
(2) sidestep the YouTube Data API search quota. Pasting a YouTube URL needs NO `search.list`
call — we already have the video ID — so it's a quota-free way to place YT clips (ties into
notes/09 + the yt-dlp-primary-search plan; both lean on `fetch_clip`, which already uses
yt-dlp). Bottleneck relief + control in one feature.

## What already exists (so this is mostly wiring, not new machinery)
- `youtube.fetch_clip(video_id, seconds, out_path, start_at=0.0)` — already downloads a
  SECTION starting at `start_at` for `seconds` and normalizes it. A timestamped URL just
  feeds `start_at`.
- Renderer already supports **ken-burns** on stills: `_build_command` runs `zoompan` when
  `clip.transforms.ken_burns` is true. The gap is only that the upload path never SETS it.
- `sourcing.capture_url()` is already **additive to candidates** (`[new] + existing`), then
  places the new one. Same pattern we reuse for URL/upload adds.
- Models need NO new fields: `MediaAsset.origin` includes `youtube`; `Clip` has
  `transforms.ken_burns`, `source_in/out`, `effects`. The YT trim happens at fetch time, so
  the asset IS the trimmed segment (source_in stays 0).

## Current beat panel (SuggestionPanel)
- **Find clips / Re-source** → `api.sourceBeat` (uses the Data API search — the quota sink).
- **Use my own** → `uploadMedia` then `placeClip(beat.start..beat.end)`. Places directly
  (not as a candidate); images get NO ken-burns (default `Transforms`).
- **Paste URL → Capture** → scroll-captures the page (`capture_url`), additive to candidates.

## Feature 1 — Unified "paste a URL" that auto-detects YouTube vs site
One input box; branch on the URL:
- **YouTube link** (`youtube.com/watch?v=`, `youtu.be/`, `/shorts/`, `/embed/`) → direct clip.
- **Anything else** → existing scroll-capture.

### YouTube URL parsing (deterministic, exact — not semantic)
Parse with `urllib.parse`:
- video_id from `v=`, `youtu.be/<id>`, `/shorts/<id>`, `/embed/<id>`.
- start time from `t` or `start` param; accept `90`, `90s`, `1m30s`, `1h2m3s` → seconds.
This is exact string parsing (fine to do deterministically; not an LLM judgment call).

### Backend
- New `sourcing.clip_youtube_url(project, beat, url)`:
  - parse `video_id` + `start_at`
  - `seconds = min(beat.end - beat.start, SOURCE_MAX_CLIP_SECONDS)`
  - `youtube.fetch_clip(video_id, seconds, out, start_at=start_at)`
  - probe + sample a thumb frame; build `MediaAsset(origin="youtube",
    license="youtube_uncleared", quarantined=True, source_url=url)`
  - build `Candidate` (fit ~0.85, verify=False — the USER chose it), additive to existing
    candidates (mirror `capture_url`); return Suggestion, place the new one.
- Endpoint: fold into the existing capture endpoint (auto-detect) OR add
  `/beats/{bid}/youtube`. Prefer folding: one box, backend routes YT vs site.
- **No `search.list`** → zero quota.

### Edge cases (fail loud with guidance, per the SourcingError pattern — no silent fallback)
- invalid / non-YT URL that looked like one → clear error.
- private / removed / age-restricted video → `fetch_clip` raises SourcingError; surface it.
- `start_at` beyond video length → yt-dlp yields nothing; error "timestamp past end".
- clip shorter than the beat (short source or near end) → black tail; see Feature 3 note.

## Feature 2 — Upload an image with slow zoom (ken-burns)
- When an uploaded asset is `kind == "image"`, set `clip.transforms.ken_burns = True` on
  placement (renderer already does the zoompan). Optionally a small fade-in via `effects`.
- UI: a "slow zoom" checkbox in the panel for image uploads, default ON.
- `place_clip` already spans the image across `beat.start..beat.end`; only the transform flag
  is missing today.

## Feature 3 — Additive model (what "multiple clips" means)
Recommended interpretation (cheap, consistent with today): **additive to the CANDIDATE
list.** Pasting a URL / uploading ADDS a candidate; the beat still has ONE active placed
clip you choose via "Use this". Nothing you added is destroyed — you can switch back. This
is exactly what `capture_url` already does.

Richer interpretation (future, flagged for a decision): **multiple clips placed IN SEQUENCE
within one beat** (e.g. a 15s beat filled by a 5s paste + a 10s clip). This needs a sub-beat
timing model — split the beat span among N clips and render each in its own
`enable=between(t,…)` window — plus UI to order/trim them. Bigger job; depends on the
incremental-proxy tiling (notes/10) since each sub-clip becomes its own tile. NOT in this
pass. Decision needed before building: do we want true in-beat sequencing, or is
"candidates you switch between" enough? (My rec: ship additive-candidates now, revisit
sequencing when tiling lands.)

## Feature 4 — Per-beat guidance text for "Find clips"
Today "Find clips" reuses the GLOBAL director-notes textarea: the Editor passes `notes` into
`api.sourceBeat` → `/beats/{bid}/source` → `direct_section(..., user_notes=notes)`, and the
director already folds `USER NOTES` into its context. So the plumbing to pass free-text
guidance PER SOURCE CALL already exists. The only gap is UI — there's no per-beat box, so a
beat can't get guidance distinct from the whole-project note (e.g. "use an actual clip of the
politician, not a metaphor" for just this one moment).

Add a small text input in the panel next to Find clips ("guidance for this beat…"):
- When filled, it's the guidance for THAT beat's source call.
- **Merge strategy (recommended): combine** the project-level notes (vibe/tone, applies to
  all) with the beat-specific line, e.g. `f"{global_notes}\n\nThis beat: {beat_notes}"`, so
  the beat guidance SHARPENS rather than discards the global intent. (Alternative:
  beat-note-only when present — but merge keeps global tone in play.)
- Persistence: v1 ephemeral (panel state for the session). Later could store the note on the
  Beat/Suggestion so a re-source remembers it and the Inspector can show what was asked.
- Effort ~1 hr: pure UI + threading the string; `direct_section` already consumes it.

## UI changes (SuggestionPanel)
- Relabel the URL box: "paste a YouTube link or any site URL…"; help text explains YT =
  direct clip at its timestamp, site = scroll-capture.
- Image uploads: "slow zoom" toggle (default on).
- A small "guidance for this beat…" input next to Find clips (Feature 4).
- Keep the additive candidate cards; the newly added URL/upload shows up as a card and is
  auto-placed.

## Sequencing / effort
Small-to-medium, because the hard parts exist:
1. YT URL parse + `clip_youtube_url` + endpoint routing (~half day). Biggest value +
   quota relief.
2. Image ken-burns flag + toggle (~1 hr).
3. Per-beat "Find clips" guidance input (~1 hr; plumbing already exists).
4. Panel relabel/wiring (~1 hr).
Defer: true in-beat multi-clip sequencing (needs tiling + a design decision).

## Ties to other notes
- notes/09 web-capture hardening (the site branch of the same URL box).
- notes/10 incremental proxy (prereq for real in-beat sequencing).
- yt-dlp-primary search plan (shares `fetch_clip`; both remove the Data API from the hot path).
