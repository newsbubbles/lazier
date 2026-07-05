# Sound design — music + SFX track driven by a Sound Director

Feedback-driven spike (a viewer literally asked for "sound effects with visuals to keep us
hooked"). Goal: a second **audio track** for music + SFX, planned by a **Sound Director**
agent, sourced + aligned like we do video clips, with the **voice spine always the
protagonist**.

## What already exists (so this is less new than it looks)
- Projects already have a **Music audio track** (`kind:"audio"`, `duck:true`) from
  `ensure_default_tracks`.
- `render._audio_clips` already composites **positioned audio clips with per-track gain +
  sidechain ducking under the voice** (`sidechaincompress` keyed off `0:a`). So the render
  foundation for "lay a sound at time T, duck it under speech" is DONE.
- `MediaAsset.license` field exists (for CC attribution tracking).
- yt-dlp fetch (`fetch_clip`) + manual URL paste (`capture_from_url`) — extend for AUDIO.
- The whole visual pipeline (director → sourcer → verify → candidates → place → edit) is the
  template; we mirror it for audio.

## Where to fetch sounds (the gap Nate flagged — researched)
- **SFX → Freesound API v2** (best fit). Huge CC library, filterable by license (incl. **CC0**,
  no attribution), free API key, official Python client, returns audio + analysis. Track the
  per-sound license on the asset; the license FILTER follows `project.rights_posture` (see Decisions).
- **Music → Pixabay Audio API** (primary): free for commercial use, **no attribution**,
  RESTful, 100 req/min. Alternates: **Jamendo** (600k tracks, CC/licensing API) and **Free
  Music Archive** (150k CC tracks).
- **YT audio / soundbites → yt-dlp** audio-only extraction (no quota) — reuse the manual-URL
  infra so you can paste a YouTube link and pull its audio (interview lines, a specific track).
- **Attribution artifact**: like `chapters.txt`, auto-emit `credits.txt` listing CC-BY sources
  used, so posting stays clean.

## The agent pipeline (mirrors the visual side)
### 1. Sound Director (`sounddirection.py`, ~ direction.py) — plans, does NOT fetch
Input context: transcript **word timing**, the **beats + their clip types** (register /
content_type — e.g. a "reaction" beat wants a sting; a "metaphor" wants a swell), the
video thesis/tone, the **quiet-moment map** (below), and Nate's optional notes.
Output: an ordered list of **SoundCues**:
```
SoundCue = { start, end, kind: music|effect, intent (build suspense/mystery/impact/warmth),
             brief (what it should be), search_terms, anchor (the moment its CLIMAX should
             land on — a beat boundary / word time), dynamics (swell|stinger|bed|hit),
             duck (bool), rationale }
```
Director rules baked into the prompt:
- **Voice is the protagonist** — sound supports, never competes. Sparse, not wall-to-wall.
- **Don't fill everything** — silence is a tool; leave beats bare.
- Use **quiet moments** for music swells / tension builds; land **stingers** on punch words
  (the anchor).
- Match emotion to the section tone; build across a section toward its payoff beat.

### 2. Sound Fetcher (~ sourcing.py youtube/web branch) — fetches candidates, doesn't judge placement
Per cue, search the right source by `kind` (effect→Freesound, music→Pixabay/Jamendo, or a
pasted YT URL), fetch **multiple candidates** (like video candidates), probe + store, tag
license. A light VLM-style check isn't needed; instead a cheap **audio fit** (duration fits
the cue, has real signal) + the director's brief. Candidates carry a waveform thumbnail.

### 3. Sound Prep / Alignment (mostly DETERMINISTIC DSP, not an LLM)
For a chosen sound, detect its **profile** — onset, peak/climax, RMS envelope — with ffmpeg
`astats`/`silencedetect` or librosa onset detection. Then **shift/trim so its climax hits the
cue's anchor** (the whoosh peaks on the word). Deterministic: peak-finding is exact; the
DECISION of what to anchor to comes from the director. LLM only if a sound has multiple
plausible peaks and we want it to pick. Also set fade in/out, gain, and duck.

## Data model
- **SoundCue** (new): the director's plan unit for the audio track (analogous to a Beat, but
  it can span, overlap silence, and carries `kind`/`intent`/`anchor`/`dynamics`).
- **Sound candidates**: reuse `Candidate`/`Suggestion` shape keyed by cue id; asset kind
  `audio`.
- **Placed sound clip**: an audio-track `Clip` (already supports `source_in/out`,
  `timeline_start/end`, gain via track, fade via `effects`). Add `align_offset` (climax
  anchor) + per-clip `gain`/`duck` if we want per-clip rather than per-track control.
- **Diegetic video audio**: add `Clip.audio_enabled` (+ gain) so a chosen VIDEO clip's own
  audio plays (an interview soundbite), ducked under / around the voice. **Voice stays the
  spine** — soundbites duck it briefly or sit under it; the director plans these moments.
- **Quiet-moment map** (derived, not stored): from `transcript.words`, the gaps with no
  speech > threshold. Deterministic. Feed to the director; Nate can deliberately record extra
  silence for buildups and the director will find it.

## Render (extend the existing audio graph)
- Already have: positioned audio clips + gain + sidechain duck. Extend for: **multiple audio
  tracks** (music track + sfx track), per-clip fades + align offset, and **diegetic video
  audio** (unmute selected video clips, duck under voice). The voice already runs through the
  optional vocal chain; the final mix is voice + music (ducked) + sfx (ducked) + diegetic
  (ducked).
- Pin audio out at 48k (already done).

## UI (mirror the video panel)
- **Two sound track rows** (music + SFX) under the beats row, rendered at **reduced height**
  (so mobile still fits), music/effect color-coded, waveform on placed clips.
- Click a cue → a **SoundPanel** (~ SuggestionPanel): candidates with waveform + play-preview,
  **Find sounds** (with per-cue guidance), **upload / paste URL / YouTube**, and per-clip edit
  controls: gain, duck on/off, fade, and a **start-offset field** (manual fine alignment,
  seconds). Multiple choices per cue; not every cue must be filled.
- A toggle on a video clip to **enable its audio** (diegetic), with a level.

## Nate's requirements → covered
paste-URL/upload/YT/refetch per sound ✓ · multiple choices per area ✓ · not fill-everything ✓
· per-cue instructions ✓ · director aware of transcript timing + beat types + quiet moments ✓
· climax alignment to beats/words ✓ · diegetic video audio (interview) ✓ · voice stays
protagonist ✓.

## Decisions (locked 2026-07-05)
1. **Two audio tracks** (music bed + SFX hits) so levels/ducking differ. On the timeline both
   render at **reduced height** vs the visual/beats rows so the **mobile layout still fits**.
2. **Licensing follows the project's `rights_posture`** (the existing anything_goes /
   commercial_safe set at project creation) — the SAME gate video sourcing already uses. The
   sound fetcher filters license by that setting: `anything_goes` = allow CC-BY + YT/uncleared
   (emit `credits.txt`); `commercial_safe` = CC0 / no-attribution royalty-free only. No
   separate audio licensing switch.
3. **Anchor = beat-boundary alignment for v1.** Each placed sound clip's right drawer also has
   a **manual start-offset** control (nudge in seconds) for fine hand-alignment — same idea as
   trimming a video clip. Word-level auto-anchor is a later refinement.

Still open (fine to defer): ducking model (music always ducks under voice; SFX stingers can
punch briefly without ducking — per-cue `duck` flag); whether audio needs a "matches the
brief" judge (v1: skip it, audition by ear).

## Effort / sequencing (spike)
1. Quiet-moment map + Sound Director agent (cues) — the brain.
2. Freesound + Pixabay fetchers + yt-dlp audio; candidates on cues.
3. Render: 2nd/3rd audio track mixing + diegetic video audio + alignment offset.
4. UI: sound track row + SoundPanel (candidates, preview, edit, guidance).
5. Deterministic climax alignment (onset/peak → anchor).
Ship v1 as "music bed + a few SFX stingers, ducked, aligned to beats"; refine to word-level.
