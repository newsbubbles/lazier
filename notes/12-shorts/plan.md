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
  placed clips + a clean audio cut. Target ~30s (`SHORTS_TARGET_SECONDS=30`, accept ~20-40).
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

## 3. Captions — ported + adapted from MemeCat
Port the MECHANICAL parts (lightweight, stdlib + ffmpeg); DROP the heavy semantic stack.
- **ASS builder** (from `generate_subtitles` + `seconds_to_hms` + the Style/Format header):
  big bold style, heavy outline/shadow, a few words per line, per-word karaoke timing from
  `transcript.words` in the window (re-based to 0). Positioned in the **vertical safe zone**
  (centered, above the bottom ~15% platform UI and clear of the right-side buttons).
- **Burn-in** via ffmpeg `ass=<file>` filter appended to the shorts filtergraph (from `write`).
- **Content-driven styling WITHOUT MemeCat's EffectBucket.** MemeCat picks emphasis/color/
  emoji by embedding-search over YAML buckets (sentence_transformers + transformers +
  prompt-owl — deps lazier shouldn't take on). Instead the **shorts agent returns a
  `caption_style`** (font, size, primary color, emphasis policy, emoji on/off) chosen from
  the short's content/tone — which is exactly Nate's "agent chooses the config per short."
  Optionally a tiny keyword→emoji map for punch. **DECISION TO CONFIRM:** LLM-picked style
  config (recommended, dep-light) vs porting the embedding buckets wholesale.
- We do NOT need MemeCat's Whisper (lazier already has word timings).

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
