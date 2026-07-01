# lazier — the Inspector: full sourcing observability (2026-07-01)

From the "I can't see what's going on" conversation. The problem: when an auto-sourced
clip is wrong, you can't tell WHY — was it the director's idea, the search results, the
content-type choice, or the verifier? The Agent Activity log is ephemeral ws chatter that
shows "idle" after a run. You're debugging blindfolded.

Goal: make every clip choice fully traceable. For each beat, capture EVERY agent's input
and output, persisted (not ephemeral) and streamed live, so the three-way question
("thinking vs search vs type choice") is a two-second read.

## The five layers to capture (per beat)

1. **Context frame — what the director actually SAW.**
   Video thesis/summary, tone, premise, reference_date; the section text; prev/next
   section topic; already-placed neighbor clips (what + register); and the user notes.
   Why it matters: this is where you'd instantly see "thesis: none" on Neurocracy and know
   the director was flying blind. You cannot judge a decision without its inputs.

2. **Director output — the thought trace.**
   Per beat: visual_register, content_type, shot_brief, search_terms, time_window, and the
   director's WRITTEN RATIONALE for why this shot. Plus the model that produced it
   (grok-4.20). Ideally also a section-level rationale (its read of the whole scene).

3. **Sourcer / search trace — the currently-invisible layer.**
   Per query: the exact query string, the source (youtube/serper), the time filter applied,
   the result count, and the top result titles/URLs — INCLUDING the ones it rejected. This
   is how you tell "the query was bad" from "the query was fine but results were garbage."

4. **Verifier output — every candidate, not just the winner.**
   For each fetched clip: sampled frames, fit_score, the verifier's WRITTEN reasoning (why
   it scored that), and the flags — tagged with the model (gemini vision). Losers stay
   visible so you see what it passed over.

5. **Decision.**
   Which candidate was placed, why (highest fit), and a LOUD flag when it's a weak pick
   (a 0% clip should scream, not sit quietly "on timeline").

## Two required properties

- **Live**: stream the trace during sourcing so Agent Activity shows real depth (which
  query, which candidate, which score), not "idle."
- **Persisted**: store the trace on the beat's Suggestion so you can inspect any beat long
  after the run.

## Implementation sketch

Backend (capture):
- `Suggestion` gains a trace: a `context_snapshot` (what the director saw), a `searches`
  list (`{query, source, time_filter, result_count, top_titles}` incl. rejects), and a
  step log. Director rationale already lives in `plan.rationale`; candidates already carry
  the verifier's fit/notes/flags — surface ALL of them, not just recommended.
- `direct_section` returns/records the context it built + per-beat rationale.
- `source_from_plan` records each search (query -> results/titles) and appends step events
  to the trace (the same events currently fired only to the ws).

Frontend (surface):
- A per-beat "🔍 Trace" panel (in or beside the SuggestionPanel) showing the five layers
  top to bottom.
- Keep the live ws stream in Agent Activity, now backed by the persisted trace so it's
  inspectable after the fact.

## Why this is the FIRST thing to build

Everything else (better director prompts, search-term/entity reasoning, multi-type
sourcing, fit thresholds) is guesswork until you can see which layer is failing. The
Inspector turns tuning from vibes into evidence. Build it before the quality tuning.

## Related follow-on tuning (after the Inspector, from the same convo)

- **Context inputs**: regenerate the video summary for existing projects; add a project
  PREMISE/context field (e.g. Nate's real backdrop — govt restricting GPT-5.6 / Claude
  Mythos) that feeds the director. Missing context was ~half the off-kilter results.
- **Sourcer reasoning**: director names the SPECIFIC entity; sourcer tries the primary
  type PLUS a secondary (a youtube clip AND a Serper article for the same beat), verifies
  across all, picks best. Matches Nate's own mental process (which politician -> youtube?
  -> news article -> judge both).
- **Fit threshold**: don't auto-place sub-~0.4 clips; flag "needs you" instead of silently
  placing junk. Catches the web-capture-fail beats too.
