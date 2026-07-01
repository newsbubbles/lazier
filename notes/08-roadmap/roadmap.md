# lazier — roadmap / parked ideas

Running list of future work, so nothing gets lost. Newest/most-discussed at top.

## Manual editing of beat & section boundaries (drag the edges)

Nate wants to click-drag the edges of any section or beat clip in the timeline. Easy to
render; the real problems are the EDITING SEMANTICS, which is why this is a note not a
quick task:

- **A beat with a clip already in it**: if you drag a beat edge, the beat span changes but
  the placed clip no longer matches that span. Do we re-trim the clip to the new span,
  re-fetch, letterbox, or hold-last-frame? Needs a rule.
- **Dragging the LEFT edge — two different intentions**:
  1. *Move the beat's position in time* (the beat starts later/earlier on the timeline), OR
  2. *Change where inside the source clip the beat starts* — reveal/hide the beginning of
     the clip (a trim-in), leaving the beat's timeline position fixed.
  These are opposite operations. An editor expects both, via different affordances (drag
  the beat block body = move; drag the clip's in/out handle = trim). We need to model beat
  span vs clip source_in/source_out separately in the UI so a left-drag can mean either.
- **Ripple vs overwrite**: dragging one beat's edge should it push the neighbor (ripple,
  keep flush) or overlap/leave a gap? Given we just made everything flush, ripple-to-keep-
  flush is probably the default, with a modifier for a free move.
- Snapping: to word boundaries, beat boundaries, the playhead.

Model implication: clips already carry `source_in`/`source_out` separate from
`timeline_start`/`end`, so the data supports the trim-vs-move split — it's a UI + rules job.

## Richer director "type" palette (as sources expand)

The director already fills `content_type` and the sourcer searches in that modality; today
the palette is just youtube/web. As we wire more sources (memes, stock images, AI-gen,
movie-scene lookups, screen-capture beyond articles), the director's type vocabulary widens
and the sourcer switches modality per beat. Nate's instinct ("I imagine the TYPE first,
then search within it") IS the architecture — it just gets richer with more sources.
Meme + own-meme-gen is the first expansion (see 05-ideas/memes-and-tuning.md).

## Web capture: AMP / cached fallback for walled news

Aggressive bot-walls (Akamai on business-standard, Cloudflare) block headless Chromium even
with stealth; headed won't launch on this box and would be blocked anyway. For reliable
news/evidence capture, try the article's `/amp/` URL or an archive.today / Google-cache
mirror before giving up. Cheap and often unwalled. (Block detection already skips walled
sites cleanly and auto-source retries the next URL.)

## The Inspector (next big build)

Full per-beat trace: context the director saw + director reasoning + search results (incl.
rejects) + every candidate's verifier score/why + the decision. See
07-inspector/observability.md. This unblocks all quality tuning.

## Sourcing quality (after the Inspector)

- **Fit threshold**: don't auto-place sub-~0.4 clips; flag "needs you" instead of placing
  junk (also catches web-capture-fail beats).
- **Entity-aware + multi-type sourcing**: director names the specific entity; sourcer tries
  the primary type PLUS a secondary (a youtube clip AND a Serper article for one beat),
  verifies across all, picks best.
- **Project premise/context field** + regenerate summary for existing projects, so the
  director has the real backdrop (missing context was ~half the off-kilter results).

## Earlier milestones still open

- M3+ incremental chunked proxy cache (re-render only edited regions).
- Vertical 9:16 + multi-export with auto-reframe.
- Stylized animated text overlays (fade/move-in), caption styling.
- Background music track UI + ducking controls, SFX.
