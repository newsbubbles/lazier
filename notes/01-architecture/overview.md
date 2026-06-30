# lazier — system architecture (v1 plan, 2026-06-30)

Built around the decisions in `../00-intake/synthesis.md`. This is the implementation map: stack, data model, rendering pipeline, agentic backbone, UI, and milestones.

The one-liner: drop in audio, Whisper time-aligns it, a fleet of background agents auto-assemble a first-cut faceless b-roll video onto a real multi-track timeline keyed to the voice, and you refine it with the audio as the spine.

---

## 1. Stack

| Layer | Choice | Why |
|---|---|---|
| Backend | Python + FastAPI | Approved; native home for pydantic-ai + fastmcp |
| Agents | pydantic-ai over OpenRouter | Model-agnostic, default kimi-k2.5 for text, a VLM for vision |
| Tool servers | fastmcp | Reusable, testable, follows Nate's existing patterns |
| Transcription | faster-whisper / WhisperX (local) | Word-level alignment, free, on-GPU |
| Fetch/trim | yt-dlp | Stream extraction + `--download-sections` trimming |
| Search | YouTube Data API, Serper, stock APIs | Find candidates before fetching |
| Image gen | FAL.ai | Custom per-phrase visuals |
| Render | ffmpeg | Proxy preview + final export |
| Frontend | React + TypeScript | NLE-style timeline + preview |
| Realtime | WebSocket | Agent progress, live timeline updates |
| Storage | SQLite (metadata/index) + filesystem (media + project doc) | Simple, local, no server |

Rust note: Nate's general lean is Rust-first for agentic, but he explicitly handed FastAPI/pydantic-ai latitude here because the agent ecosystem is more mature. If a hot path shows up (proxy stitching, frame sampling) it can be a small Rust/native helper called from Python. Default is Python.

### Repo layout (proposed)

```
D:\lazier\
  notes\                  # this planning
  backend\
    app\                  # FastAPI app, routes, websocket
    core\                 # project model, EDL, render orchestration
    agents\               # pydantic-ai agents (director, segmenter, sourcers, verifier)
    mcp\                  # fastmcp tool servers (search, fetch, gen, vision, transcribe)
    render\               # ffmpeg proxy + export engine
    whisper\              # local transcription service
  frontend\               # React/TS editor
  workspace\              # per-project media + project.json + proxies + exports
    {project_id}\
      project.json
      audio\
      media\              # downloaded/generated/pooled assets
      proxies\            # cached low-res render chunks
      exports\
      transcript.json
      captions.srt
```

---

## 2. Data model

The project doc (`project.json`) is the single source of truth; SQLite indexes assets for fast search/reuse.

- **Project**: id, name, aspect_ratio (set at creation), fps, created_at, audio_ref, budget_cap, source_toggles, rights_posture (`commercial_safe` | `anything_goes`, see `media-sources.md`), media_pool_path (optional).
- **Transcript**: words[] with start/end (from Whisper), the raw word-level alignment.
- **Segment (pass 1)**: span derived from Whisper voice timing (silence/gaps split it).
- **Section (pass 2)**: merged coherent topic span. Fields: start, end, transcript_text, topic_label, **visual_brief** (agent's description of what should be on screen). This is the unit agents source for.
- **Track**: ordered. types = `visual` | `audio` | `caption` | `overlay`. Multi-track.
- **Clip** (timeline item): track_id, timeline_start, timeline_end, asset_ref, source_in/source_out (trim), transforms (scale/position/crop for reframe + ken-burns), effects (fade in/out, transition), z_order.
- **MediaAsset**: id, kind (video/image/audio), origin (youtube | stock | meme | fal | pool | upload), source_url, local_path, license, duration, resolution, metadata, **verify_score** + verify_notes.
- **Suggestion**: section_id, candidates[] (each = asset_ref + rationale + fit_score), recommended_index. Drives the per-section cards in the UI.

State an asset moves through: `discovered -> fetched/generated -> verified -> offered (suggestion) -> placed (clip)`. No silent fallbacks (per Nate's rule): if a source fails, the suggestion records the failure with state, it doesn't quietly swap in something worse.

---

## 3. Rendering pipeline (server-rendered proxy)

The hard part. Design splits responsibilities so editing feels live without building a full in-browser compositor.

- **Visual compositing -> server.** ffmpeg renders the composited visual track(s) into **GOP-aligned proxy chunks** (e.g. 480p, ~5-10s each), cached per chunk keyed by the clips covering it (asset + in/out + transforms + effects). Editing one clip invalidates only the chunks it touches. The browser plays the muted proxy locked to the master audio.
- **Master audio -> client spine.** The real audio plays in the browser and drives the playhead + waveform. The proxy video follows it. Audio is never re-rendered for preview.
- **Text / captions / overlays -> client-side live.** Rendered as DOM/canvas over the video for instant feedback while editing. Only baked by ffmpeg at export. (This is why captions can stay optional and cheap.)
- **Final export -> full server render.** One ffmpeg `filter_complex` assembles all tracks at full res: visual stack, overlays, baked captions (if toggled), audio mix with **auto-ducking** of background music under the VO. Output mp4 + the always-written `captions.srt`.

For faceless b-roll, usually one full-frame visual at a time plus optional caption/overlay, so compositing is light and the chunk-cache stays cheap. Heavier compositing (picture-in-picture, overlays) still works, just dirties more chunks.

MVP shortcut if chunk-stitching is too much for M1: debounced "render preview" of the whole proxy after edits. Upgrade to chunk-cache in M3.

---

## 4. Agentic backbone

pydantic-ai agents orchestrated by a director. Tools live in fastmcp servers so they're reusable and unit-testable.

### Agents

- **Director / orchestrator**: owns the project, walks sections, fans out sourcing tasks, assembles the draft, enforces budget_cap, emits progress over WebSocket. Low visual presence by design.
- **Segmenter** (pass 2): reads pass-1 Whisper segments, merges into topic sections, writes each section's `visual_brief`.
- **Sourcing agents** (fan-out, one task per section):
  - **Researcher** (Serper): turns the visual_brief into concrete entities + search terms.
  - **YouTube fetcher**: YouTube Data API search -> rank candidates -> yt-dlp trim to the section length + correct format.
  - **Stock/meme fetcher**: free image/clip libraries + meme sources.
  - **Gen** : FAL.ai custom images (custom video later).
  - **Pool**: checks the local media_pool_path first when set.
- **Verifier** (OpenRouter VLM): samples frames from fetched clips and from AI-gen, scores fit against the visual_brief. Runs on AI-gen + fetched clips (not on trusted pool/upload).
- **Assembler** (director step): places the recommended pick per section onto the visual track at the section's timing, applies defaults (ken-burns on stills, fade transitions), and emits 2-3 ranked **Suggestions** with one recommended.

### Concurrency + tool discipline (Nate's hard-won rules, baked in from day 1)

- Fan-out across sections means concurrent agent runs -> **fresh pydantic-ai Agent per call + per-role cached model**, never a shared Agent with structured output (that serializes). See `feedback_pydantic_ai_shared_agent_concurrency`.
- Every fastmcp tool = **Request BaseModel + Context**, two args only. See `feedback_fastmcp_tool_signature`.
- Include a **`process_tool_call` arg normalizer + prompt guidance** from the start to avoid retry-exhaustion loops. See `feedback_pydantic_ai_tool_call_normalizer`.
- If an agent's tool call gets rejected, fix the **Field description / docstring** first, don't code around it. See `feedback_tool_description_tightening`.
- Section merge / fit judgment = **LLM judgment, not regex/keyword heuristics**. See `feedback_no_regex_for_semantic_checks`.

### MCP tool servers

- `transcribe` — local Whisper (audio -> word-aligned transcript).
- `media-search` — Serper + YouTube search + stock search + meme search.
- `media-fetch` — yt-dlp wrapper (guarantees length/format) + plain downloader.
- `media-gen` — FAL.ai.
- `vision-verify` — OpenRouter VLM frame scoring.

---

## 5. UI

Feels like an NLE; agents stay backstage.

- **Create-project dialog**: name, aspect ratio, fps, audio upload, optional media-pool folder, budget cap, source toggles (YouTube / stock / meme / FAL / pool).
- **Editor layout**:
  - Top: **preview viewport** sized to the chosen aspect + transport controls (play/scrub/zoom).
  - Side: **media bin** (asset pool) + **section suggestion panel** for the selected section (the recommended card highlighted, 2 alternates, with accept / swap / regenerate / override-with-own-media).
  - Bottom: **multi-track timeline** with the **audio waveform as the spine**, sections marked along it, clips on the visual track(s), audio tracks (music/SFX), optional caption track. Zoomable; snaps to section + word boundaries.
  - Corner: a quiet **agent activity feed** (what's being sourced/verified), low visual presence.
- **Captions**: per-section toggle to bake; SRT always exported regardless.
- **Export**: pick quality, ffmpeg full render, drops mp4 + srt in `exports\`.

---

## 6. Milestones

- **M0 — spec** (this). Done when overview + decisions are signed off.
- **M1 — the spine.** Project model, audio ingest, local Whisper, two-pass segmentation, timeline data model + waveform UI, manual clip add, ffmpeg export, SRT write. No agents yet. Proves audio->timeline->render end to end.
- **M2 — first sourcing agent.** Director + segmenter + YouTube fetcher (API search + yt-dlp trim) + verifier. Suggestion cards, accept-to-timeline, override-with-own-media.
- **M3 — proxy preview + multi-track + audio mix.** Chunk-cache proxy engine, background music track with auto-ducking, SFX.
- **M4 — more sources.** Stock + meme fetchers, FAL gen, vision-verify across all fetched + gen.
- **M5 — captions + polish.** Caption track, per-section bake, styling, budget UI.
- **Later.** Stylized animated text overlays (fade/move-in), vertical 9:16 + multi-export auto-reframe, more transitions/effects.

---

## 7. Open items to resolve before/at build

- ~~Confirm THIS machine's GPU to size the Whisper model.~~ RESOLVED: 1080 Pascal 8GB → faster-whisper large-v3 INT8 (Pascal FP16 is crippled). See `../02-agents/tool-design.md` §6.
- ~~Pick the React timeline foundation.~~ RESOLVED: React + `@xzdarcy/react-timeline-editor` (vendored) + wavesurfer.js + vidstack. See `frontend-foundation.md`.
- ~~Stock/meme source list.~~ RESOLVED: Pexels + Pixabay first, then Openverse + Internet Archive. See `media-sources.md`.
- ~~License/metadata capture per asset.~~ RESOLVED: license tagged at fetch + per-project rights posture. See `media-sources.md`.
- Budget/cost model: per-project cap + a cost preview before AI-gen spend (Nate is cost-aware). Tools exist (`estimate_gen_cost`, budget guard); the UI surface for it is still open.
- Confirm default rights posture (`anything_goes` w/ labels vs `commercial_safe`) at project create.
