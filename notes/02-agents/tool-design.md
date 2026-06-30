# lazier — agent fleet tool design (2026-06-30)

Designed against the agentic-tooling framework (deterministic control surfaces for probabilistic planners). The fleet is a set of LLM steps wired by deterministic Python; each LLM step only ever sees decision-sized tools with shaped errors and bounded output.

Read alongside `../01-architecture/overview.md`. Tool source lives in `backend/mcp/` as fastmcp servers (each tool = `Request` BaseModel + `Context`, two args, per Nate's standing rule).

---

## 0. The one rule that shapes everything: media never enters context

Clips, images, audio, and video frames are large. An agent must perceive them through **handles + compact metadata + scores**, never raw bytes (Principle 5: context-length awareness is correctness).

So every tool obeys:

- Search/fetch/gen tools return an **`asset_id`** plus light metadata (title, duration, resolution, source, license, a thumbnail URL). Never the file.
- The model "looks at" a clip only through the **verifier**, which sames frames and returns a *score + notes*, not the frames.
- The timeline is **queryable state**, not a blob the model rewrites. Agents mutate it through decision-sized actions (`place_clip`, `propose_suggestion`), never by emitting JSON.

This is what lets a mid-tier OpenRouter model (kimi-k2.5) run the whole thing. The more the Python harness does deterministically, the weaker the model we need (Principle 2).

---

## 1. What is deterministic code vs what is an LLM step

Push everything that can be deterministic into the harness (Principle 2). The LLM only does judgment.

| Stage | Who does it |
|---|---|
| Transcribe audio | deterministic (Whisper service) |
| Pass-1 segmentation (silence/gap split) | deterministic |
| Pass-2 merge into topic sections + visual briefs | **LLM: Segmenter** |
| Fan-out scheduling across sections, retries, budget accounting | deterministic harness |
| Turn a visual brief into entities + search terms | **LLM: Researcher** |
| Run the searches | deterministic (tools) |
| Rank/choose among candidates | **LLM: Sourcer** (per source family) |
| Download + trim to format | deterministic (yt-dlp / downloader) |
| Sample frames + score fit | **LLM: Verifier** (VLM), tool-fused |
| Place recommended pick, set timing/effects, propose alternates | **LLM: Assembler**, with deterministic validation |
| Global pacing / variety / budget tradeoffs | **LLM: Director** (thin) |

The "Director" is mostly the scheduler (code). Its LLM portion only handles global calls a local step can't see: don't reuse the same stock clip five times, spend the gen budget where it matters, flag sections with no good free option.

---

## 2. MCP servers (the control-complete tool subsets)

Each server is one domain concept and closes a full loop: discover → inspect → act → verify (Principle 3).

### 2.1 `transcribe`

| Tool | Input | Returns | Notes |
|---|---|---|---|
| `transcribe_audio` | audio_asset_id, model_size=large-v3, lang? | transcript_id, duration, word_count, segment_count | Deterministic. Does NOT return words into context. |
| `get_transcript_window` | transcript_id, start_s, end_s | words[] in range | Windowed read (Principle 5). |

### 2.2 `segments` (Segmenter agent)

| Tool | Input | Returns | Notes |
|---|---|---|---|
| `list_segments` | transcript_id | [{seg_id, start, end, text_preview, word_count}] | Previews truncated, not full text. |
| `get_segment_text_batch` | seg_ids[] | full text per id | Batch read of a window to decide merges (Principle 6). |
| `merge_segments` | seg_ids[], topic_label, visual_brief | section_id | The act. Creates a Section. |
| `set_section_brief` | section_id, visual_brief | ok | Revise a brief without re-merging. |
| `list_sections` | — | [{section_id, start, end, label, brief, status}] | Verify the result. |

Loop: `list_segments` → `get_segment_text_batch` → `merge_segments` → `list_sections`.

### 2.3 `media-search` (Researcher + Sourcers)

All return bounded candidate lists with previews + an opaque `candidate_handle`. Never media bytes.

| Tool | Input | Returns |
|---|---|---|
| `search_web` | query, max=5 | Serper results: title, snippet, url (for entity/term discovery) |
| `search_youtube` | query, max, min_dur?, max_dur? | [{candidate_handle, video_id, title, channel, duration, thumbnail_url, desc_preview}] |
| `search_stock_video` | query, sources[], max | [{candidate_handle, source, id, title, duration, preview_url, license}] |
| `search_stock_image` | query, sources[], max | [{candidate_handle, source, id, title, preview_url, license}] |
| `search_gif` | query, source, max | [{candidate_handle, source, id, preview_url}] |
| `search_meme` | query, source, max | [{candidate_handle, source, id, title, preview_url}] |

`sources[]` enum (from `../01-architecture/media-sources.md`): `pexels`, `pixabay`, `openverse`, `internet_archive`, `mixkit`, `imgflip`, `coverr`, `giphy`, `reddit`, `imgur`, plus `youtube` (separate yt-dlp path) and `pool`. Each candidate carries its **license** so downstream placement can record and enforce it. (Note: Tenor's API is dead as of 2026-06-30, not in the enum.)

### 2.4 `media-fetch` (YouTube/Stock/Meme sourcers + Pool)

| Tool | Input | Returns | Notes |
|---|---|---|---|
| `fetch_youtube_clip` | video_id, start_s, end_s, target_format | asset_id, actual_duration, resolution, thumb_refs | yt-dlp `--download-sections`. Guarantees container/codec/fps. |
| `fetch_media_url` | candidate_handle, target_format? | asset_id, metadata | Stock/gif/image/meme download + normalize. |
| `list_pool_media` | query? | [{asset_id, kind, name, duration, thumb}] | Searches the user's local media-pool folder (when set). Checked FIRST. |
| `import_pool_media` | path | asset_id | Register a pool file. |
| `get_asset_info` | asset_id | metadata only | No bytes. |

Loop: `search_*` → `fetch_*` → `get_asset_info`/verify.

### 2.5 `media-gen` (Gen agent) — cost-guarded

| Tool | Input | Returns | Notes |
|---|---|---|---|
| `estimate_gen_cost` | model, n, aspect | est_cost_usd | Called BEFORE spending (Principle 10). |
| `generate_image` | prompt, aspect, model? | asset_id, thumb_ref, cost_usd | FAL. Checks project budget; refuses + guides if over cap. |

Budget guard is part of the contract: if a generate would breach `budget_cap`, the tool **refuses with an informative error** naming remaining budget and telling the agent to fall back to a free source or ask the user (Principles 9 + 10). It does not silently spend (also matches Nate's no-silent-fallback rule).

### 2.6 `vision-verify` (Verifier agent) — fused sample+score

| Tool | Input | Returns | Notes |
|---|---|---|---|
| `verify_fit` | asset_id, visual_brief, n_frames=4 | {fit_score 0-1, notes, flags[]} | Samples frames + runs OpenRouter VLM in one call (Principle 6). flags: has_watermark, has_burned_text, letterboxed, low_quality, nsfw, off_topic. |

One fused tool instead of `sample_frames` then `score`: the agent never holds frames in context, only the verdict. Runs on fetched clips + AI-gen, skipped on trusted pool/upload.

### 2.7 `timeline` (Assembler + Director) — the project mutation surface

Decision-sized, deterministic, validated.

| Tool | Input | Returns | Notes |
|---|---|---|---|
| `get_project` | — | aspect, fps, duration, tracks[], budget state | Bounded summary. |
| `list_sections` | — | sections + placement status | Discover what still needs visuals. |
| `propose_suggestion` | section_id, candidates[{asset_id, rationale, fit_score}], recommended_index | suggestion_id | Writes the 2-3 cards the UI shows. |
| `place_clip` | section_id, asset_id, in/out, transforms?, effects? | clip_id | Validates timing fits the section; refuses overlap on the single visual track with guidance. Enforces the project **rights posture**: under `commercial_safe`, refuses uncleared assets (youtube/giphy/reddit/imgur) with guidance to pick a Tier-1 source; under `anything_goes`, places but stamps the clip's license/quarantine label for the UI. |
| `update_clip` / `remove_clip` | clip_id, ... | ok | |
| `add_audio_clip` | track, asset_id, start, gain, duck? | clip_id | Music/SFX; `duck=true` ducks under VO at export. |
| `set_caption` | section_id, on, style? | ok | Per-section bake toggle; SRT always written regardless. |
| `get_timeline_state` | — | full EDL summary | Verify. |

Loop: `list_sections` → `propose_suggestion` / `place_clip` → `get_timeline_state`.

---

## 3. Agent → tool capability matrix (Principle 8: shape per role)

Each agent gets only the tools its job needs. No agent gets the kernel.

| Agent | Tools it can call |
|---|---|
| **Segmenter** | `segments.*`, `transcribe.get_transcript_window` |
| **Researcher** | `media-search.search_web`, `search_youtube`, `search_stock_*`, `search_gif`, `search_meme` |
| **YouTube sourcer** | `search_youtube`, `media-fetch.fetch_youtube_clip`, `get_asset_info` |
| **Stock/meme sourcer** | `search_stock_*`, `search_gif`, `search_meme`, `fetch_media_url`, `list_pool_media`, `import_pool_media`, `get_asset_info` |
| **Gen** | `media-gen.estimate_gen_cost`, `generate_image` |
| **Verifier** | `vision-verify.verify_fit`, `get_asset_info` |
| **Assembler** | `timeline.*`, `get_asset_info` |
| **Director (thin)** | `timeline.get_project`, `list_sections`, `get_timeline_state` (read-mostly: global pacing/budget) |

---

## 4. Error shaping (Principles 9 + 11): a few concrete contracts

Errors point forward and name the next call.

- `fetch_youtube_clip` on a region-locked/removed video →
  `{error: "unavailable", reason: "video removed", next: "discard this candidate; call search_youtube again with a broader query or try search_stock_video"}`
- `generate_image` over budget →
  `{error: "budget_exceeded", remaining_usd: 0.40, next: "fall back to search_stock_image / search_meme for this section, or surface to user to raise budget_cap"}`
- `place_clip` with a clip longer than the section →
  `{error: "duration_overflow", section_len: 4.2, clip_len: 7.1, next: "set source_out to trim to <=4.2s, or split across the next section"}`
- `verify_fit` flags `has_burned_text` on a clip →
  not an error, a flag; the Assembler is instructed to prefer a clean alternate so we don't bake someone else's captions in.

Stable, predictable semantics so the planner branches instead of retrying blindly (Principle 12).

---

## 5. Batch / fused tools already folded in (Principle 6)

- `get_segment_text_batch` — read a window of segments in one call.
- `verify_fit` — sample + VLM-score in one call (no frames in context).
- A future `source_section(section_id)` macro could fuse the whole search→fetch→verify→propose chain for a section into one director-level call once the per-step behavior is stable. Hold until traces justify it (Principle 12: evolve from observed behavior, don't pre-fuse).

---

## 6. Whisper sizing for THIS box (1080 Pascal, 8GB)

- Pascal FP16 is 1/64 rate, so **use INT8** via faster-whisper / CTranslate2.
- **large-v3 @ INT8** ≈ 2-3GB VRAM, fits 8GB with headroom, good accuracy.
- Start with faster-whisper built-in `word_timestamps=True` (DTW, no extra model). Add WhisperX wav2vec2 alignment only if word boundaries aren't tight enough for snapping.
- `distil-large-v3` is an option if speed beats accuracy, but this is an offline editor so favor accuracy.
- Exposed as the `transcribe` MCP server, not a baked-in call (Principle 7).
