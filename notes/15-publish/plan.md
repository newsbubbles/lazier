# Publish — auto-publish to YouTube (+ X, TikTok) from lazier

Goal: a **Publish ▾** dropdown next to Export that takes the rendered artifacts (long-form
export, short, captions, chapters) and pushes them to platforms with all the tedious metadata
filled in — following Nate's exact manual flow and the `D:\YouTube` packaging playbook.

Status: PLAN ONLY. Research done 2026-07-06 (feasibility confirmed with sources, see below).

## Nate's manual flows (the spec we automate)
**YouTube long-form:** upload mp4 → title + 1-sentence hook description + chapter list (so
chapters render) → not-for-kids + video language English + relevant hashtags → 2nd screen: add
subtitles + end screen (subscribe + prev video, for the backward binge chain) → publish public,
OR if before 5pm schedule for **17:30 UTC+1** (6pm is the sweet spot).
**YouTube short:** short title + hashtags (#ai #anthropic …) → copy description from the short's
`.txt` → language English → 2nd screen: reference/link back to the long-form just uploaded →
publish immediately.
**X / TikTok:** X = maybe long-form or shorts (TBD by reach); TikTok = the shorts.

## Feasibility (researched 2026-07-06 — hard gates in bold)

| Platform | Public-post gate | Audit? | Cost | Worst API gap |
|---|---|---|---|---|
| **YouTube** | **Uploads force-locked to `private` until a compliance audit passes** | Yes — free "API Services Audit & Quota Extension" form + demo video | Free API; **100 uploads/day/project** dedicated bucket (2026 change) | **End screens & cards have NO API** — always manual |
| **X (Twitter)** | none (public by default) | No | **No free tier (2026): pay-per-use $0.015/post, $0.20 if it has a link** | v1.1 media upload deprecating; use v2 chunked (INIT/APPEND/FINALIZE + poll) |
| **TikTok** | **All posts forced `SELF_ONLY` until Content-Posting audit; ≤5 posters/24h; account must be private** | Yes — separate Content Posting API audit | Free API | Draft (`video.upload`) flow needs user to finish in the TikTok app |

**Three must-clear-before-public gates (Nate's action, not code):** (1) YouTube compliance audit,
(2) TikTok Content-Posting audit, (3) an X billable account. Until each clears, that platform runs
in its degraded mode (below), which is still a big time-save.

### YouTube specifics
- Scopes: `youtube.upload` covers `videos.insert` (title/description/tags/categoryId/
  `defaultLanguage`/`status.publishAt`/`status.privacyStatus`/`selfDeclaredMadeForKids=false`).
  Captions (`captions.insert`) need the broader `youtube.force-ssl`. **Our current token is
  read-only (`yt-analytics.readonly`+`youtube.readonly`) — needs a one-time re-consent.**
- `snippet.defaultAudioLanguage` is NOT reliably settable via API; `defaultLanguage` is. (Minor.)
- **End screens / cards: no API exists** (open feature request, unimplemented). Permanent manual step.
- Pre-audit reality: lazier uploads as `private` + fills ALL metadata + captions; Nate opens the
  video, adds the end screen, clicks Publish. Post-audit: lazier sets `publishAt`/public directly.
  So the feature is useful even before the audit (front-loads the grunt work).

### The binge-chain "point at previous video" — we can auto-derive it
Our EXISTING read-only scope can fetch the channel's most recent upload (`search.list` /
`playlistItems`). So lazier can auto-fill the description back-link AND tell Nate exactly which
video to end-screen to. No manual lookup.

## Architecture (lazier-idiomatic)

Split by the agentic-tooling rule (determinism for exact ops, LLM only for judgment):
- **Metadata agent** (`publish/metadata.py`, pydantic-ai `NativeOutput`): the only LLM piece.
  Generates the *copy* per platform from the transcript + `video_summary` + `tone` + the short's
  `hook_title`/`social_caption`, following `D:\YouTube\notes\playbook\packaging.md` house style.
  Output model `PublishMeta`: `title_variants: list[str]` (3, each selling a different beat:
  hook / flip / technical, per packaging.md), `hook_description` (1 sentence), `tags`, `hashtags`,
  `x_post`, `tiktok_caption`, and `thumbnail_prompts: list[ThumbPrompt]` (3, see below).
  Deterministic assembly after: YT description = chosen `hook_description + "\n\n" + chapters.txt`;
  short description from its `.txt`.
- **Platform adapters** (`publish/youtube.py`, `publish/x.py`, `publish/tiktok.py`): pure
  deterministic API clients, mirror the `sourcing`/`soundsourcing` adapter shape. Common interface:
  `class Target: def preflight(project) -> list[str] (missing creds/blockers); def publish(project,
  artifact, meta, opts) -> PublishResult`. `PublishResult { url, status, manual_steps: list[str] }`.
  - `youtube.py`: reuse the stdlib token-refresh pattern from `D:\YouTube\scripts`. Resumable
    `videos.insert` (POST the mp4), then `captions.insert`, then set `publishAt` if scheduling.
    Returns `manual_steps=["Add end screen → <prev video url> in Studio: <edit deep link>"]`.
  - `x.py`: v2 chunked media upload → poll STATUS → `POST /2/tweets` with `media_id`. OAuth user
    context. Degraded mode if no billing: prepare copy + `manual_steps=["open composer"]`.
  - `tiktok.py`: Query Creator Info → Direct Post (`video.publish`) when audited, else Upload/draft
    (`video.upload`) with `manual_steps=["finish + publish in TikTok app"]`.
- **Endpoints** (`main.py`, async + WS progress like render): `POST /publish/{platform}` and
  `POST /publish-all`. A publish reuses the last render artifacts (auto-render first if missing).
  Long-form publishes FIRST so its URL threads into the short's description (the binge chain).
- **Scheduling (deterministic, no LLM):** `publish/schedule.py`. Rule: if now (UTC+1) is before
  17:00 → `publishAt = today 17:30 UTC+1`, else public now. Env-tunable
  `LAZIER_PUBLISH_HOUR=17:30`, `LAZIER_PUBLISH_TZ=+01:00`, cutoff. (Note: scheduling public still
  needs the YT audit; pre-audit it stays a private draft.)

## What lazier already has vs what the agent makes
- HAVE: `export.mp4`, `captions.srt`, `chapters.txt`, `shorts/short_1.mp4` + `short_1.txt`
  (hook + caption + hashtags), `project.name`, `video_summary`, `tone`, `sections`.
- AGENT MAKES: long-form YouTube **title** (packaging house style — thesis/coined-term), the
  1-sentence **hook description**, **tags/hashtags**, and the **X post** / **TikTok caption** copy.
- A review step: publish opens a small **metadata editor** (title/desc/tags/schedule) prefilled by
  the agent — Nate can tweak before the actual push. (Publishing is irreversible-ish; never fully
  silent.)

## Thumbnails + title A/B (packaging = the #1 CTR lever on this channel)
Your own data (packaging.md, 2026-07-03): b-roll-frame thumbs converted 0.8-1.4%; a designed
thumb + thesis title is "the single highest-leverage fix." So this is core, not a nice-to-have.

**Generate (FAL — key already set, no new creds):**
- `publish/thumbs.py`, deterministic FAL client. Researched model picks (re-confirm slugs at
  build time — fal rotates them):
  - **Hero variant → Nano Banana Pro** (`fal-ai/nano-banana-pro` / `fal-ai/gemini-3-pro-image-preview`,
    edit `…/edit`): best short-text rendering + reference-image edit (drop in a face / brand badge),
    native 16:9, ~$0.15. Params: `prompt`, `image_urls` (array of reference-image URLs),
    `aspect_ratio:"16:9"`, `num_images`, `output_format:"jpeg"`.
  - **Cheap variant fan-out → Ideogram V3** (`fal-ai/ideogram/v3`): typography-first, `style:DESIGN`,
    `rendering_speed:TURBO` ~$0.03. Params: `prompt`, `aspect_ratio:"16:9"`, `rendering_speed`,
    `style`, `num_images`.
- `ThumbPrompt` from the metadata agent = { subject (one bold idea), text (≤3 words, quoted in the
  prompt), accent_hex }. House style baked in: one image, ≤3 words readable at 120px, ONE idea,
  consistent brand signature (corner badge), and **A/B varies the accent color per variant**
  (cyan / magenta / orange) so a winner teaches color too. Optional `image_urls` = a brand badge or
  a face for consistency.
- Render 3 at **1280×720** (YT spec: 16:9, JPEG/PNG, <2MB). Land them in `exports/thumbs/`.

**A/B mechanics — NO API (Studio-only, same as end screens; researched, high-confidence):**
- There is no YouTube API to create/manage the native "Test & compare" A/B test, and native
  **title** A/B is still a gated/partial rollout (not guaranteed per channel). Only `thumbnails.set`
  (single thumbnail, ≤2MB, scope `youtube.force-ssl`) exists.
- So the flow: lazier generates the 3 titles + 3 thumbs, sets ONE thumbnail + the chosen title via
  the upload/`thumbnails.set`, and hands Nate the other variants + a deep link to **set up Test &
  compare manually in Studio** (up to 3 thumbs, YouTube judges by watch-time over ~1-2 weeks;
  needs Advanced Features, desktop, not Shorts/kids).
- Optional later: a **roll-your-own rotation** tester (swap `thumbnails.set` on a schedule + read
  CTR from the analytics token we already have) — a real automatable A/B lazier could own end to
  end, sidestepping the Studio-only native test. Flag as a Phase-4 idea.

## .env / creds
- YouTube: reuse `D:\YouTube\.secrets\{client_secret.json, yt_oauth.json}` via
  `LAZIER_YT_SECRETS_DIR` (default that path). Ship a `publish/youtube_reauth.py` (fork of the
  existing `oauth_flow.py`) that re-consents with `youtube.upload youtube.force-ssl` and writes a
  NEW token (keep the read-only one for analytics). Channel id via env or auto-resolve.
- X: `LAZIER_X_API_KEY/SECRET`, `LAZIER_X_ACCESS_TOKEN/SECRET` (OAuth1a user) or OAuth2 bearer +
  refresh. Billable account required.
- TikTok: `LAZIER_TIKTOK_CLIENT_KEY/SECRET`, `LAZIER_TIKTOK_ACCESS_TOKEN`.
- Thumbnails: **`FAL_KEY` already set** in `.env` and `config.FAL_KEY` (currently unused) — nothing
  new needed. Optional `LAZIER_THUMB_MODEL` to pick the fal slug.
- All optional: a platform with missing creds shows greyed-out in the dropdown with a preflight
  reason (principle-9 forward-pointing errors), never a crash.

## UI — Publish ▾ (mirror the Export dropdown)
```
Publish ▾
  [x] language English   [x] not made for kids      (dd-toggles, defaults on)
  schedule: (auto 17:30 UTC+1) ▸                     (editable)
  ────────
  Publish to All                                     (long → short, threads binge link)
  ────────
  YouTube: long-form + short
  ▸ also post long-form to X   [checkbox]
  ────────
  YouTube long-form only
  YouTube short only
  X  (post)                                          (greyed if no billing creds)
  TikTok  (short)                                    (greyed if unaudited → draft mode label)
```
After a publish: a results panel with the live URL(s) + the `manual_steps` checklist (end screen,
TikTok finish-in-app). Reuse the render progress bar / WS for upload progress.

## Phasing
1. **YouTube long-form + short (assisted) + thumbnails.** Metadata agent (title variants +
   description + tags + thumbnail prompts) + `thumbs.py` FAL generator (3 variants) + `youtube.py`
   adapter + re-auth script + schedule logic + binge-chain auto-derive + Publish dropdown + a
   metadata/thumbnail review editor. Works pre-audit as "upload private draft + all metadata +
   captions + set best thumbnail; you add the end screen, set up Test & compare, hit publish."
   Nate submits the audit form in parallel → unlocks direct public/scheduled. (Thumbnails are the
   #1 CTR lever, so they ship in Phase 1, not later.)
2. **X adapter.** Once Nate has a billable X account. v2 chunked upload. Long-form or short per
   what reach research says. ~$0.015-0.20/post, so gate behind an explicit toggle.
3. **TikTok adapter.** Draft/`video.upload` flow first (works unaudited, finish-in-app); direct
   public post after the Content-Posting audit.

## Open decisions for Nate
1. **YouTube audit** — worth submitting now? Without it, YT publish tops out at "private draft +
   metadata done, you click publish." With it, fully scheduled/public. (I can draft the form
   answers + we already have the OAuth demo to record.)
2. **X**: pay-per-use is live cost per post. Post long-form, shorts, or both? Set a monthly cap?
3. **TikTok**: start with the unaudited draft flow (push to your drafts, you tap publish in-app),
   or wait until we clear the audit for true one-click?
4. **Review vs silent**: default to the prefilled metadata-review step before every publish
   (recommended — publishing is public + hard to undo), or a "trust it, fire" mode for YT drafts?
5. Scheduling exactness — confirm 17:30 UTC+1 default and the "before 5pm → schedule" cutoff
   (playbook says a fixed 7pm hour; your message said ~6pm sweet spot / 5:30 schedule — pick one).
6. **Thumbnails**: default to Nano Banana Pro hero + Ideogram-V3 cheap variants, or one model?
   And do you want a brand badge / face reference image fed in (`image_urls`) for a consistent
   signature, or pure prompt each time?
7. **A/B**: native Studio Test & compare (we generate assets, you set it up — no API), or should
   we later build lazier's own thumbnail-rotation A/B (auto-swap + read CTR from the analytics
   token we already have)? The native one is judged by watch-time; ours would be CTR-based.
