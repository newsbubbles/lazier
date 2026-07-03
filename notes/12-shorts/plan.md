# Shorts — auto-extract one ~30s vertical clip per video

## Goal
Auto-produce **one ~30s 9:16 short per finished project** for YouTube Shorts / Reels /
TikTok / X, to drive visibility + marketing. Reuse the finished project (beats, placed
clips, timeline, transcript); reframe to vertical; burn in TikTok-style captions (caption
engine ported from MemeCat at D:\MemeCat). Source projects are already published, so this
runs over existing project.json + assets on disk — no re-sourcing.

## 1. Shorts agent — pick the 30s window (pydantic-ai, NativeOutput)
- **Input**: transcript full text + word timings, `video_summary`/`tone`, section (chapter)
  labels, the beats and what clip is placed on each. `reference_date`.
- **Output** `ShortPlan`: `{ start, end, hook_title, social_caption, rationale, caption_style }`.
- **Snap [start,end] to BEAT boundaries** so we cut cleanly on speech and reuse the existing
  placed clips + a clean audio cut.
- **Length: target ~30s but let CONTENT pick the natural close.** `SHORTS_TARGET_SECONDS=30`,
  acceptable ~18-45s, **hard cap 60s** (to qualify as a YouTube Short and stay in the
  high-completion zone across TikTok/Reels/X). Completion rate rules the algorithm, so a
  tight 22s beats a padded 35s — the agent stops where the thought actually closes, it does
  not pad to hit 30. (30 is a good default anchor; the range is the real spec.)
- **One per video** for now; schema can carry a ranked list later for N shorts.
- **Tips baked into the system prompt** (what makes a good short):
  - Opens with a HOOK in the first 1-2s: a question, a bold/contrarian claim, a number.
  - ONE self-contained idea/takeaway that stands alone without the rest of the video.
  - Starts on a sentence boundary; ends on a payoff/punch, not mid-thought.
  - The intellectual/emotional peak; a quotable line.
  - ~30s of actual speech; skip slow setups.

## 2. Reframe to 9:16 (render)
Target canvas **1080x1920** (`SHORTS_W/H`). Per source:
- Project already 9:16 → scale-to-fit, no crop.
- 16:9 source → **crop-to-fill** 9:16, origin by asset TYPE:
  - video + image → **center** crop.
  - web-capture (`asset.origin == "web"`) → **left** crop (the reading/content side).
- ffmpeg per clip: `crop=ih*9/16:ih:X:0` (X=0 left, `(iw-ih*9/16)/2` center) → `scale=1080:1920`.
- Only clips/audio inside `[start,end]`, shifted to t=0; audio is the original narration for
  that window. Add `loudnorm` so platform loudness is consistent.

## 3. Captions — word-level engine (MemeCat mechanics + our word timing + LLM style)
**Word timing is already there.** `project.transcript.words` holds per-word start/end
(verified: 743 words on Neurocracy 2, persisted in project.json). So **no backfill, no
separate transcript.json needed** — the engine reads `project.transcript.words` directly.
`captions.srt` stays the segment-level artifact; the word timing is the sub-timing SRT lacks.
(Optional: also dump a `transcript.json` for external tools, but it's redundant with data we
already hold.)

Port the MECHANICAL parts of MemeCat (stdlib + ffmpeg), drop its ML stack (no Whisper /
sentence_transformers / transformers / prompt-owl — lazier already has the words):
- **ASS builder** (`generate_subtitles` + `seconds_to_hms` + the Style/Format header) +
  **burn-in** via the ffmpeg `ass=<file>` filter (`write`), positioned in the vertical safe
  zone (centered, above the bottom ~15% platform UI, clear of the right-side buttons).

Then BUILD PROPERLY the parts MemeCat left unfinished, driven by the word timing:
- **Words-per-line**: configurable (1 = punchy one-word pop; 2-4 for calmer lines). Group
  `transcript.words` accordingly.
- **Highlight-as-spoken (karaoke)**: the active word pops/recolors exactly when spoken —
  ASS `\k` karaoke tags or one event per word, using per-word start/end. This is precisely
  what SRT can't do and what the word timing unlocks.
- **Emphasis / emoji / color** per keyword.

**Styling driven by the LLM, not MemeCat's embedding buckets (DECIDED: LLM).** The buckets'
value is very custom captions; we keep that expressiveness but move the CHOICE from an
embedding search to LLM judgment. The shorts agent returns a rich `caption_style` that
expresses MemeCat's full vocabulary:
```
caption_style = { font, base_size, primary_color, outline, shadow,
                  words_per_line, highlight_mode: none|word|line, highlight_color,
                  emphasis_keywords[], emoji: off|auto|map, position }
```
The agent picks these from the short's content/tone ("call the captioning style based on what
MemeCat shows"). Later we can add a few named presets (mirroring the bucket YAMLs) for the
agent to pick among, if pure free-config feels too loose.

## 4. Output
- `exports/shorts/short_1.mp4` (own subfolder, per Nate).
- Sidecar `exports/shorts/short_1.txt`: the agent's `hook_title` + a suggested social caption
  + hashtags (marketing helper, like `chapters.txt`). Directly serves the visibility goal.

## 5. Code / API
- New `shorts.py`: `find_short(project)` [agent] + `build_caption_ass(words, style)`.
- `render.py`: `render_short(project, short_plan)` — 9:16 reframe + caption burn, monolithic
  like export, writing to `exports/shorts/`. (Reuses the existing compositing/overlay code
  with a vertical canvas + per-clip crop + the `ass=` filter.)
- Endpoint `POST /projects/{pid}/shorts` → find + export → returns `{video, caption_text}`.
- UI later: a "Make a short" button. For now the smoke test drives the endpoint/module.

## 6. Smoke test (part of implementation)
Run `find_short` + `render_short` on an existing published project (e.g. **Neurocracy 2**
`prj_51aa63792c`). Verify: output is **1080x1920, ~30s**, captioned in the safe zone,
reframed correctly (center for clips, left for web-captures), audio is the right window, and
it plays cleanly. Eyeball the chosen window — is it actually a good hook?

## What Nate may have left out (flagging)
1. **Captions are essential** on mute-autoplay platforms — making them explicit + safe-zone
   placed (implied via MemeCat, but worth stating).
2. **First-1-2s hook** makes or breaks a short — bias the agent to open on a hook; optional
   bold title-card overlay for ~1.5s.
3. **Loudness normalization** (`loudnorm`) for platform consistency.
4. **Caption safe margins** for 9:16 platform chrome (bottom caption bar + right buttons).
5. **Social caption/title/hashtags sidecar** for posting (serves the marketing goal).
6. Reframe is **dumb center/left crop** — fine for v1; subject/face-aware reframe is future.
7. **One now, N later** — keep the schema able to return ranked candidates.
8. **No new heavy deps** — port only the ASS+ffmpeg logic; skip MemeCat's ML stack.

## Effort / sequencing
1. Shorts agent (find window + style + caption) — ~½ day.
2. 9:16 reframe + shorts export path + subfolder — ~½ day.
3. Caption ASS port + `ass=` burn + agent style config — ~½ day.
4. Smoke test on Neurocracy 2, eyeball, tune the prompt tips.
