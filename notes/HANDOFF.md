# lazier — HANDOFF (2026-07-01)

Resume point after a long build session. Read this + `notes/` to continue.

## What lazier is
Audio-driven, mostly-autonomous video editor at `D:\lazier`. Drop in audio → local Whisper
time-aligns it → two-pass segmentation into topic CHAPTERS then per-moment BEATS → a Visual
DIRECTOR plans each section's shot sequence → sourcer fetches YouTube clips / web scroll-
captures → VLM verifies against the shot brief → clips land on an aligned NLE timeline where
the audio is the spine. Owner: Nate (newsbubbles). Full design in `notes/` (00→08).

## Repo / run
- Backend: `D:\lazier\backend` (FastAPI + uv). Run: `cd backend; uv run uvicorn lazier.main:app --port 5181` (or `launch.sh`/`launch.ps1` at repo root)
- Frontend: `D:\lazier\frontend` (React+Vite+TS). Run: `cd frontend; npm run dev` (:5180 strictPort, proxies to :5181)
- Git: `git@github.com:newsbubbles/lazier.git`, branch `main`. `.env` + `workspace/` are gitignored (keys + real projects never committed). NOTE: use PowerShell here-strings (`@'...'@`) for commit messages, NOT bash (bash mangles them with stray `@`).
- Keys auto-load from `D:\lazier\.env` via dotenv: OPENROUTER, SERPER, FAL, YOUTUBE_API_KEY.

## CURRENTLY RUNNING (this session's background tasks — may have died on compaction)
- Backend uvicorn on :8000 (task b2notzhdu).
- Frontend preview on :5180 (Claude Preview server, launch.json name `lazier-frontend`).
- If dead: restart both. Preview serverId last was `1879f584-aba5-4d35-8562-351ec1b9a2b9`.

## Models (config.py, env-overridable)
- `LLM_MODEL` = `google/gemini-2.5-flash` (segmentation, queries — fast + reliable structured output)
- `VLM_MODEL` = `google/gemini-2.5-flash` (clip verify, multimodal)
- `DIRECTOR_MODEL` = `x-ai/grok-4.20` (won the A/B: 5s, most register variety + metaphor; kimi-k2.5 was terrible for this, kimi-k2-thinking ok, gemini-flash 2nd)

## Built + verified (all committed/pushed)
- M1: project model, audio ingest, local faster-whisper (CPU `base` model — box has no CUDA libs), two-pass segmentation, aligned timeline (React + wavesurfer custom, NO xzdarcy), ffmpeg proxy/export + SRT.
- M2: per-beat sourcing. YouTube (Data API + yt-dlp trim) + web-capture (Playwright scroll-record). VLM verify. Suggestion cards.
- BEATS: section=topic chapter (nav), beat=speech-chunk (visual unit). Speech-timing flush phrases → agent merges adjacent same-visual phrases, capped by BEAT_MAX_SECONDS. Sections+beats now FLUSH (no black gaps).
- M3: proxy preview synced to the audio clock (scrub/play → muted proxy video follows; dense keyframes).
- **VISUAL DIRECTOR** (`direction.py`): summarize_video (thesis+tone) + direct_section (per-beat register/content_type/shot_brief/search_terms/time_window, plans by INDEX, labeled context hierarchy incl. USER NOTES). Time-aware search (YT publishedAfter/Before + Serper tbs). Verifier scores against the SHOT BRIEF. UI: tone/date at create, director-notes box, plan shown on cards.
- Web-capture hardened: subprocess worker (Proactor) so Playwright launches; targeted gentle scroll to the highlight; trims blank load off the front; bot-block detection (skips denial pages, auto-source retries next URL); basic stealth.

## CRITICAL GOTCHAS (don't re-learn these — see feedback_pydantic_ai_structured_output memory)
1. **pydantic-ai output mode**: use `output_type=NativeOutput(Model)`, NOT the default ToolOutput (kimi AND gemini fail ToolOutput over OpenRouter → retry exhaustion). NEVER hand-parse JSON. `agents.py: run_agent()` is the one helper. Param is `retries=` (not output_retries) in pydantic-ai-slim 2.2.
2. **Windows event loop**: `config.py` sets `WindowsSelectorEventLoopPolicy` (ProactorEventLoop crashes on run_sync teardown → hangs). BUT Selector can't spawn subprocesses → Playwright must run in its OWN subprocess (`webcapture_worker.py`) that sets ProactorEventLoop.
3. **Agent I/O by INDEX not hash-id**: director/segmenter output uses small integer indices (models mangle long ids). Tiling built by construction from start-boundaries.

## Neurocracy test project (prj_43ae7ffec8)
12.5-min real video, 11 chapters / 107 beats, sections+beats flush. Has no video_summary/tone (transcribed before summarizer — director flies partly blind on it, which is a known limitation and part of why some auto-sourced clips are off). A few beats have auto-sourced clips (low fit — search quality is the tuning frontier). Use it as the working test project; don't re-transcribe (slow).

## Known issues / honest state
- Auto-sourced clip QUALITY is low (fit 0.0-0.5): search terms too loose, no fit threshold (places junk), and Neurocracy lacks summary/tone context. This is the tuning frontier, NOT broken plumbing.
- Akamai/Cloudflare-walled sites (business-standard) block web-capture; headed Chromium won't launch on this box. Walled news needs AMP/cache (roadmap).

## NEXT: build the INSPECTOR (Nate's explicit next ask)
Per-beat trace, persisted + live, so every clip choice is debuggable. Five layers
(see `notes/07-inspector/observability.md`):
1. Context the director saw (thesis/tone/notes/section/neighbors/placed) — exposes "thesis: none".
2. Director output + written rationale.
3. Search trace: each query, source, time filter, result count, top titles INCL. rejects (invisible today).
4. Verifier output for EVERY candidate (fit + written why + flags), not just the winner.
5. Decision + loud "weak pick" flag.
Backend: add trace capture to Suggestion (context_snapshot, searches list; candidates already carry verifier data; plan.rationale exists). Frontend: a "🔍 Trace" panel per beat.

## Then (roadmap, notes/08-roadmap/roadmap.md)
Fit threshold (don't place sub-0.4), project premise field + regenerate summary, entity-aware + multi-type sourcing, draggable beat/section edges (trim-vs-move semantics), richer type palette (memes/images/gen sources), AMP/cache capture, chunked proxy cache.

## Notes index
00-intake, 01-architecture, 02-agents/tool-design, 03/04 (older), 05-ideas/memes-and-tuning,
06-direction/visual-direction, 07-inspector/observability, 08-roadmap/roadmap. README.md has run/config.
Commits of note: M1+M2 33f94f9 · beats 591f26e · timeline UX baa64a1 · web-capture bf48e4c ·
M3 c9f2bdb · pydantic-ai refactor f38a352 · director 805b783 · grok default ab6d376 ·
capture subprocess ae09b6f · stealth+block c4ff689 · scroll/trim 4f53cbd · flush a7e5767.
