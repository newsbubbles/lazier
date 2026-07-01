# lazier — visual direction: how sourcing should actually work (2026-07-01)

Deep design note from Nate's "think like a director, not an engineer" conversation. This
sets the architecture for the sourcing agents and the reference for later tweaks. Nothing
here is built yet; current sourcing is the naive per-beat version.

## The core reframe

**The beat is the unit of PLACEMENT. The section is the unit of creative DECISION.**

Today: each beat independently asks "what footage matches these words." That is a
researcher with no editor, and it produces literal, repetitive, semantically-flat results.
It can't do the thing Nate wants: tell a visual story across a section.

A real edit is a **paper edit** first. The editor reads the whole scene, plans the shot
sequence (this shot establishes, this is evidence, this is the comedic payoff), THEN a
researcher finds the actual footage, THEN the editor reviews options and cuts. We only had
two of those three roles. The missing one is the **director**.

## How a human team breaks it down (the model to copy)

1. **Writer** → the narration (we have it: the audio + transcript).
2. **Editor / Director** → the "paper edit" / shot list. Reads the script, splits into
   scenes (= our sections), and for each scene plans the visual sequence: annotates each
   line with a shot idea, a register, a source type, and notes on rhythm/tone/payoffs.
   Holds the WHOLE scene (and the whole video's thesis) in mind.
3. **Researcher / Assistant editor** → takes the shot list and finds the actual footage
   (stock, archive, YouTube, screen-captures, generated graphics). Returns options.
4. **Editor** → reviews options, picks, arranges, adjusts. (= verify + place + human
   override in our UI.)

Our pipeline should mirror this exactly.

## Proposed architecture: three roles (+ a one-time summarizer)

- **Summarizer** (once per video, after transcription): writes the video's thesis /
  throughline as a short paragraph. Cheap. Gives the director the top of the hierarchy.
- **Visual Director** (per section — THE NEW PIECE): plans the section's shot sequence.
  For each beat it outputs: `register`, `content_type`, a `shot_brief` (concrete visual
  description of the intended shot), `search_intent` (terms/entities/metadata), a
  `time_window` (for news/evidence), a `tone`, and `avoid` notes (e.g. "not another
  article"). Enforces variety, flow, escalation, contrast, continuity, and no repetition
  ACROSS the section. This is the creative brain.
- **Sourcer** (per beat, per type — we have it, upgraded): takes one shot_brief + type and
  executes the search/fetch against the right source. Pure retrieval.
- **Verifier** (we have it, upgraded): scores candidates against the SHOT BRIEF, not the
  literal transcript. A metaphor clip that fulfills the brief must score HIGH even though
  it doesn't match the spoken words. (Today's verifier would reject it as off_topic — that
  is the bug Nate's example exposes.)

### Why two agents (director + sourcer), not one
- Different context: director needs the whole section + neighbors + video summary +
  already-placed clips; sourcer needs a tight brief + tools. One per-beat agent can't hold
  the section-wide view that makes variety/flow possible.
- Different models (see model routing).
- Different jobs: creative planning vs mechanical retrieval. Separating them lets us
  re-plan without re-searching and vice versa.

## The context hierarchy (labeled — what the DIRECTOR sees)

Tag every part of the context so the model knows what role it plays:
- **VIDEO**: title + short transcript summary (the thesis/throughline).
- **SECTION**: the full section transcript text, with the CURRENT beat's text MARKED
  inside it (the moment in context, not isolated). Plus the ordered list of the section's
  beats.
- **NEIGHBORS**: previous/next section topic (for transitions) + the already-placed clips
  in this section (their type + brief) so it varies and doesn't repeat or clash.
- **STYLE**: project-level tone/genre knob (comedic / serious / documentary / meme-heavy /
  essayist). Default inferred from the summary, overridable per project.

The **SOURCER** sees only: the shot_brief + content_type + time_window + its tools.
The **VERIFIER** sees: the shot_brief (+ frames). Fit = "does this fulfill the intended
shot," register-aware.

## Registers — the visual vocabulary (this is what makes it a STORY)

Give the director an explicit palette and rhythm rules. Register drives content type.

| Register | What it is | Typical type |
|---|---|---|
| literal / illustrative | show the thing named | stock / youtube |
| evidence / source | the article, tweet, paper, chart | web-capture / screenshot (time-aware) |
| data / graphic | a number or chart | generated / found |
| metaphor / association | visual analogy (bell shattering = prices soaring) | youtube / gen |
| reaction / comedic | meme, cartoon reaction, facial reaction | meme / gif |
| archival / historical | old footage for context | internet archive / youtube |
| ambient / mood | atmospheric b-roll, sets tone, non-literal | stock |
| motif / callback | a recurring visual that ties the video together | any (reused) |

**Rhythm rules the director must apply:**
- Don't repeat the same register or source type back-to-back (the "two articles" problem).
- Build/escalate within a section toward a payoff.
- Contrast for punchlines (serious setup -> comedic metaphor payoff).
- Hold continuity when the subject stays put across beats; vary when it moves.
- The FIRST beat of a section usually establishes (literal/evidence); later beats can go
  associative/metaphorical.
- **Temporal salience**: use beat DURATION. A ~2s beat wants a punchy single image/meme; a
  ~10s beat can hold a developing clip or a web-scroll. Position matters too
  (opening vs climax vs resolution of the section).

## Worked example (Nate's) — the difference between a researcher and a director

Section thesis: *food is overpriced and getting worse.*
- Beat 1 "food is overpriced" -> **evidence**, web-capture, a recent news headline,
  time-scoped to this month.
- Beat 2 "prices keep rising, no signs of stopping" -> director SEES beat 1 was evidence,
  refuses another article, escalates to **metaphor/comedic**: youtube, brief = "carnival
  strength-tester; character swings the hammer, the puck rockets up and shatters the bell
  — visual metaphor for prices exploding." Verifier scores it HIGH because it matches the
  brief, though it's nowhere in the transcript literally.
- Beat 3 (payoff/reaction) -> a meme reaction to release the tension.

The naive per-beat sourcer produces "article, article, article." The director produces a
scene.

## Real features this implies (not just prompt tweaks)

1. **Video summary** generated once after transcription (top of the hierarchy).
2. **Time-aware search**: project has a `reference_date` (default today / video date); the
   director emits a `time_window` per news/evidence beat; wire date filters into YouTube
   (`publishedAfter`/`publishedBefore`) and Serper (`tbs`/date range). Granularity down to
   day for breaking-news beats. Without this, "food prices" pulls a 2016 article.
3. **Register/rhythm palette** encoded in the director prompt + as a small config so it's
   tunable.
4. **Already-placed-clips awareness**: the director reads what's in the section (from prior
   runs or user overrides) and plans around it. Supports re-planning ONE beat in full
   section context (when the user re-sources a single beat) as well as the whole section.
5. **Verifier becomes brief-aware** (score against shot_brief, register-aware), not literal
   transcript match.

## Model routing (where kimi/grok finally fit)

Everything mechanical (segment, search, verify) wants the FAST model (gemini-2.5-flash) —
measured reliable + quick. **Direction is genuine reasoning** (tone, metaphor, rhythm,
anti-repetition), so the Director is the ONE agent where a stronger/thinking model earns
its keep. Route the Director to a reasoning model (candidates: kimi-k2-thinking, grok, or a
gemini thinking variant) and A/B it on OUTPUT QUALITY, not speed. It's one call per section
(low frequency), so latency there is acceptable. This is also how Nate's kimi/grok
preference gets honored where it actually matters.

Caveat: kimi was slow + inconsistent at STRUCTURED extraction (see
feedback_pydantic_ai_structured_output). The director's output is also structured. Keep the
director's output schema SIMPLE (per-beat register/type/brief/terms) and use NativeOutput;
if kimi is still flaky, gemini-2.5-flash with a strong director prompt is the fallback.

## Nate's calls (2026-07-01) — DECIDED

1. **User notes per invocation.** Both "Auto-source all beats" and per-beat "Find clips"
   take an OPTIONAL free-text message from Nate, labeled as USER NOTES in the agent
   context. It can be loose ("this should be funny"), tight/rigid ("a specific moment from
   <movie scene>"), or empty (fully up to the director). This is the human director leaning
   over the AI director's shoulder. Thread it into the Director's context prominently.
2. **Project-create inputs.** Add (a) a TONE input (Nate's own idea of the tone) and
   (b) an OPTIONAL "date sensitive" input (reference date). Date can ALSO be inferred by
   the director from transcript cues ("yesterday on June 30th"). Same spirit as #1: give
   the human a place to inject intent, fall back to inference/director when empty.
3. **Model test.** Nate's read: kimi has built-in reasoning; grok unsure. So run a quick
   CONTROLLED test (same director context) comparing kimi vs grok (vs gemini) on direction
   OUTPUT QUALITY before committing the director's model. Config: LAZIER_DIRECTOR_MODEL.

## Open questions (decide at implementation)

- **Reference date source**: project setting (default today or a user-entered "video is
  about <date>")? Plus director inferring per-beat from transcript cues ("last month",
  "in 2024")? Recommend: project `reference_date` default = today, director can narrow.
- **Style/tone**: global project setting vs inferred from summary. Recommend: inferred
  default, user-overridable (comedic / serious / documentary / meme-heavy).
- **How hard to force variety**: a knob for register-change cadence? Start with a prompt
  rule, add a knob if needed.
- **Director scope**: plan whole section at once (holistic, one call) — yes. Re-source of a
  single beat re-invokes the director for just that beat WITH section context + neighbors.
- **Does the director ever touch timing** (merge/split beats for pacing)? Not v1 — beats
  are fixed from segmentation. Possible later ("director suggests a pacing change").

## Build order when we implement (rough)

1. Summarizer (one call after transcribe) + store `video_summary` + `reference_date` on the
   project.
2. Director agent: section -> per-beat plan (register/type/brief/search_intent/time_window).
   Structured output via pydantic-ai NativeOutput. Reasoning model, A/B'd.
3. Rewire Sourcer to consume the shot_brief + type (per-type search: youtube/web/image/
   meme/gen) and make search time-aware.
4. Make the Verifier brief-aware.
5. UI: show the director's plan per section (register + brief per beat) as the thing you
   review/tweak, not just raw candidates. The plan becomes the editable creative layer.
