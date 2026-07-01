# Memes as a source + auto-sourcing tuning (for tomorrow)

Captured from Nate's good-night note. Not started, just parked.

## Memes as a clip/image source

The instinct: memes make it more fun to watch, used sparingly, "when YouTube clips
can't cut the cake." Two paths, and we probably want both:

1. **Template memes (deterministic, cleanest rights)** — Imgflip free API:
   `get_memes` (top ~100 blank templates) + `caption_image`. We compose the meme
   ourselves from a known template, so it's the safest monetization story in the meme
   category (the macro layout is ours; some underlying images still carry IP). See
   `../01-architecture/media-sources.md` Tier-3.
   - Agent picks a template + top/bottom (or N-box) captions from the beat's words.

2. **Custom-generated memes (when a template fits but needs our own content)** — Nate's
   idea: prompt an image model with "a meme in the style of <template>, but with our
   content." We don't have an OpenAI key, so route to what we have:
   - **FAL** (FAL_KEY already wired) image gen, or
   - **OpenRouter image models** (e.g. `google/gemini-2.5-flash-image`) — same key we
     already use.
   - Prompt = describe the meme template layout + the joke tied to the beat text.

## How it plugs in

- A new candidate `source: "meme"` (template) and reuse/extend `fal`/image-gen for
  custom. Add to the per-beat candidate mix.
- **Sparingly**: an agent gate (like `web_intent`) decides if a meme actually fits the
  moment and beats a literal clip — only fire when it lands, not every beat.
- Verify with the same VLM pass (does the meme read? is text legible?).

## Auto-sourcing tuning (Nate testing tomorrow)

- The YouTube fit scores run low on abstract beats. Plan: iterate the agent SYSTEM
  PROMPTS (`sourcing._QSYS` query-gen, `_WEBSYS` web intent, and add a meme-intent) with
  real beats from the Neurocracy project as the test set.
- Likely wins: better query generation (concrete visual nouns, entities), maybe 2 query
  strategies (literal vs conceptual), and letting the agent pick source TYPE per beat
  (clip vs web vs meme) instead of always trying YouTube first.
- Also: chapter-scoped "source this chapter" to stay under YouTube's 100-search/day quota
  while testing.
