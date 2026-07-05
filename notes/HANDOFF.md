# lazier — HANDOFF (2026-07-05)

Resume point after a long build session. Read this + `notes/` (00→13) to continue.

## >>> NEXT TASK: SOUND DESIGN spike (notes/13-sound-design/plan.md) — decisions LOCKED
Add music + SFX via a **Sound Director** agent + fetch + deterministic climax alignment, on a
new audio track. Voice spine stays the protagonist. Render already has positioned audio clips
+ sidechain ducking, and projects already carry a "Music" audio track — foundation is half
there. Fetch sources (researched): **Freesound API** (SFX, CC/CC0), **Pixabay Audio API** +
Jamendo + FMA (music), **yt-dlp audio** (soundbites). Locked decisions:
1. **Two audio tracks** (music + SFX), rendered at REDUCED row height so mobile fits.
2. **Licensing follows `project.rights_posture`** (anything_goes vs commercial_safe) — same
   gate video sourcing uses; anything_goes allows CC-BY + emits `credits.txt`, commercial_safe
   = CC0/royalty-free only.
3. **Beat-boundary alignment for v1** + a per-clip **manual start-offset** control in the
   sound clip's drawer. Full details + agent pipeline + data model + UI in notes/13.

## Audio state (all committed; tree is clean)
- **voice_enhance** podcast vocal chain (`config.VOICE_CHAIN`/`AUDIO_LUFS`, applied in
  `render.py` when `project.voice_enhance`; UI checkbox, OFF by default) — committed `5bf5335`.
  Nate A/B'd it, didn't love the result (afftdn denoiser + single-pass loudnorm artifacts),
  so it stays opt-off. If revisited: soften/remove `afftdn`, make loudnorm two-pass/linear.
- `_kind_for` fix (trust image extension so uploads aren't miscalled "video") — committed.
- **`-ar 48000` pin** on both render audio outputs (loudnorm was upsampling to 96k) — committed `c4cf21c`.

## What lazier is
Audio-driven, mostly-autonomous video editor at `D:\lazier`. Drop in audio → local Whisper
time-aligns it (word-level) → two-pass segmentation into topic CHAPTERS then per-moment BEATS
→ a Visual DIRECTOR plans each section's shot sequence → sourcer fetches YouTube clips / web
scroll-captures → VLM verifies against the shot brief → clips land on an aligned NLE timeline
where the audio is the spine. Now also exports **vertical shorts** with karaoke captions.
Owner: Nate (newsbubbles, @natecodesai on YT).

## Repo / run
- Backend: `D:\lazier\backend` (FastAPI + uv). Run: `cd backend; uv run uvicorn lazier.main:app --port 5181 --host 127.0.0.1`
- Frontend: `D:\lazier\frontend` (React+Vite+TS). Run: `cd frontend; npm run dev` (**:5180 strictPort**, proxies /api /files /ws to :5181; `allowedHosts: ['.ts.net']` for phone access via `tailscale serve`)
- **Launchers** (repo root): `./launch.sh [both|backend|frontend]` (bash) or `.\launch.ps1` (PowerShell). They free the ports first, then start. Default = both.
- **PORTS ARE PINNED: frontend 5180, backend 5181** (config in vite.config.ts, main.py CORS, both launchers). Off the generic 8000/5173. Don't let them drift.
- Git: `git@github.com:newsbubbles/lazier.git`, branch `main`. `.env` + `workspace/` gitignored (keys + real projects never committed). NO Co-Authored-By trailer. Commit messages: bash `git commit -m` with a plain string, or a `-F <file>` — avoid PowerShell here-strings with parens/`@`.
- Keys auto-load from `D:\lazier\.env`: OPENROUTER, SERPER, FAL, YOUTUBE_API_KEY (YT key now UNUSED — search moved to yt-dlp).

## Running state (background tasks die on compaction — restart both)
- Backend on :5181, frontend on :5180. If either seems down but a listener shows on the port,
  it's a **ZOMBIE** (bound socket, dead process) — `netstat -ano | grep LISTENING | grep :PORT`,
  `taskkill //F //PID <pid>`, then relaunch. This bit us repeatedly (uvicorn + vite both).

## Models (config.py, env-overridable)
- `LLM_MODEL` = `google/gemini-2.5-flash` (segmentation, queries)
- `VLM_MODEL` = `google/gemini-2.5-flash` (clip verify, multimodal)
- `DIRECTOR_MODEL` = `x-ai/grok-4.20` (also `SHORTS_MODEL` default)

## CRITICAL GOTCHAS (don't re-learn — see feedback_pydantic_ai_structured_output memory)
1. **pydantic-ai output**: `output_type=NativeOutput(Model)`, never ToolOutput, never hand-parse JSON. `agents.py: run_agent()` is the one seam. It also sets `model_settings={"extra_body":{"provider":{"require_parameters":true}}}` (OpenRouter routing — see below). Param is `retries=` in pydantic-ai-slim 2.2.
2. **Windows event loop**: `config.py` sets Selector policy (Proactor crashes run_sync teardown). Selector can't spawn subprocesses → Playwright runs in its OWN Proactor subprocess (`webcapture_worker.py`).
3. **Agent I/O by INDEX** not hash-id (models mangle long ids). Tiling built by construction from start-boundaries.
4. **finish_reason='error' (OpenRouter)**: intermittent `UnexpectedModelBehavior` over a ValidationError — OpenRouter's upstream provider erroring, surfaced in a field the openai SDK's strict Literal rejects. `require_parameters:true` (in run_agent) mitigates but does NOT fully eliminate it (still seen occasionally in sourced projects). Next lever = OpenRouter provider ordering/pinning via extra_body, not a retry. It's NOT our schema.

## Built this session (all committed/pushed; earlier M1–M3 + Director + web-capture still stand)
- **Search off the YT Data API → yt-dlp `ytsearch`** (no key, no 100/day quota) + 14-day disk cache in `WORKSPACE/_cache` (doubles as dedupe). `youtube.py`.
- **Manual per-beat sourcing** (`sourcing.capture_from_url` classifier): paste a **YouTube** link (w/ `?t=`), a **direct video** file (downloads then trims locally + `?t=`, strips our t/start param, browser UA), a **direct image** (downloads → ken-burns), or **any page** (scroll-capture). All additive candidates. Image ken-burns on placement; per-beat "guidance" box on Find clips.
- **Web-capture hardening**: domain blacklist (fb/x/ig/linkedin/reddit + hard paywalls) at search; verifier hard-fails login/consent/paywall/error frames (`not_content`); scroll **dwells ~20%** before panning. (notes/09 Layers 2/3 — CMP auto-dismiss + login/consent skip exit codes — still TODO, need live testing.)
- **Proxy preview speed**: 360p / 18fps / `ultrafast` (export unchanged). Render also fixed for the Windows 32k arg limit (`-filter_complex_script`) and a stderr-pipe deadlock (temp file), with a live **progress bar** over the websocket (render endpoints are async).
- **YouTube chapters** export (`chapters.txt` + "YT chapters" button → clipboard).
- **Export ▾ dropdown**: Full (video→short→chapters) / Video / Short / YT Chapters.
- **SHORTS** (`shorts.py` + `render.render_short`): agent picks best ~30s window (18–45 target, 60 cap, snapped to beats) + hook + social caption + LLM caption style; 9:16 reframe (web=left crop, else center; scale-cover+crop); **word-level karaoke ASS captions** (mechanics ported from MemeCat at D:\MemeCat, styling by LLM not embedding buckets); loudnorm; → `exports/shorts/short_1.mp4` + `.txt` sidecar. Word timing already in `project.transcript.words` (no backfill). SMOKE-TESTED on Neurocracy 2. TODO: emoji rendering stubbed; length sometimes long-ish; caption safe-zone tuning.
- **Mobile**: side panels → drawers (<860px), pinch-to-zoom timeline, tap a candidate preview to play once, responsive project form, `← Projects` moved to left-panel bottom, SVG transport icons.
- **Live candidate previews** in the suggestion panel synced to the timeline cursor. **Spacebar** play/pause.
- **CHANGELOG.md** (Keep a Changelog; 0.1.0 baseline + Unreleased). README screenshot (`img/`).
- **Robustness fixes**: startup reconcile resets orphaned `sourcing` suggestions (interrupted jobs no longer wedge a beat); `capture_site` error path now resets the suggestion too; `_prune_orphan_clips` drops beat_id=null clips overlapping beat-linked ones; `place_clip` now reflects a beat-linked placement as a candidate (so "Use my own" shows in the panel like URL paste).

## Known issues / honest state
- **finish_reason='error'** still pops occasionally (see gotcha 4).
- Some **YouTube clips fail normalize** (`Output file does not contain any stream`) — per-video yt-dlp section download yields no video stream. Now fails gracefully (beat → error, not stuck). Lever: drop `--force-keyframes-at-cuts` in `youtube.fetch_clip` (Nate said leave it for now).
- Auto-sourced clip **quality** is still the tuning frontier (loose search terms; no fit threshold → places weak clips).
- Web-capture can't beat Akamai/Cloudflare walls; headed Chromium won't launch on this box.

## Notes index (00→12)
00-intake · 01-architecture · 02-agents · 05-ideas · 06-direction · 07-inspector ·
08-roadmap · **09-web-capture** (hardening: blacklist/consent/login/dwell) · **10-incremental-proxy**
(per-beat tile cache — the real "instant preview" fix) · **11-manual-sourcing** (paste URL/upload/guidance) ·
**12-shorts** (the shorts plan) · **13-sound-design** (music/SFX spike — decisions locked, NEXT).

## Likely NEXT (Nate's call)
- **Incremental proxy tiling** (notes/10): render per-beat tiles keyed by content hash, concat → editing one beat re-renders in seconds, not the whole 2-min pass. Biggest iteration-speed win.
- **Web-capture Layer 2/3** (notes/09): auto-dismiss cookie banners + login/consent skip exit codes.
- **Shorts polish**: emoji captions, safe-zone position, tighter length, a "Make a short" button (currently endpoint-only, reachable via Export ▾ → Short).
- **Bad-clip robustness**: probe sourced clips before render, fail loud naming the beat (one bad clip currently can fail a whole render).
- **Fit threshold**: flag sub-~0.4 beats as "needs you" instead of placing junk.
- The **Inspector** (notes/07) is still unbuilt — per-beat trace for debuggability.

## Key commits (this session, newest first)
b166824 stuck-beat + orphan prune · 9f8201a place_clip→candidate · 6bf8d6e video-URL reliability ·
2263d7f direct-media URLs · dee61f8 export dropdown · 6446829 shorts · 6254edd proxy 360p/ultrafast ·
58ec364 search-term fix · fed711e web-capture blacklist/verifier/dwell · 1176b86 manual sourcing ·
d9de74f yt-dlp search+cache · 78c66a6 ports 5180/5181 · e3c5520 launchers · 436d197 chapters ·
e7d2012 render progress + provider routing · 890a51c live candidate previews · 48c81f6 changelog+spacebar.
