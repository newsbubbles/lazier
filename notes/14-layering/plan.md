# Retention "layering" — concept-density signal + overlay/vibe-shift armor

Parked idea from 2026-07-05, after publishing "Art or Entertainment" and running the
YouTube Studio "Ask Studio" AI + a cross-chat with the video-pipeline agent. NOT built yet.
This is the capture so we can pick it up later.

## Where this came from (evidence, not vibes)
- Studio AI + a real viewer comment both point at the same leak: on **intellectually dense
  passages** retention drops. The viewer literally asked for "sound effects with the visuals
  to stay hooked" (this is what kicked off the sound-design spike, notes/13).
- First **timestamped** retention evidence for the channel: a dip at **1:06 in the UN video**
  (`2zlac1NUCgA`) right where the topic ramps from concrete → abstract.
- The pipeline agent named the fix "layering": add sensory/structural scaffolding over the
  heavy beats so the viewer's brain keeps up. It sorted into 3 layers.

## The 3 layers and WHOSE job each is (the important part)
1. **Human-bridge** — plain-speak translation right after each dense quote.
   → **NOT lazier.** This is script-writing (the words Nate speaks). It belongs to the
   `write-broll-video` skill the pipeline agent is writing (D:\YouTube\skills\), applied when
   authoring the spoken audio. lazier never sees a script, so this can't live here.
2. **Audio vibe-shift + SFX punctuation** on dense beats.
   → **Sound Director's job — already exists** (notes/13, `sounddirection.py`). Music beds /
   swells / stingers already get planned + ducked. Gap: it keys off `visual_register`, not off
   "conceptual density." Needs a density trigger (see below).
3. **Visual concept-overlay** — when a framework with named parts shows up (e.g. Collingwood's
   magic / amusement / art-proper), pin those as a persistent on-screen list over the b-roll and
   highlight the active item as the VO walks through it.
   → **NEW build.** Highest-leverage visual feature here; directly targets the 1:06 class of dip.

## Key architecture decision: density is a Director OUTPUT, not a script tag
- The pipeline chat floated `[LAYER: ...]` tags in the script as "single source of truth."
  **Rejected for lazier**: lazier is **audio-first** (WAV → Whisper → beats). There is no script
  in the pipeline, and aligning written tags back onto the word-timed transcript is brittle. The
  `[LAYER]` tag idea is fine for the *script-writing skill*, not for the editor.
- Right fit (Nate's call): the Visual Director **already fills out a per-beat object from the
  transcript** (`_Directive`/`BeatPlan`). Add a **concept-density score** to that object. The
  director is already doing per-beat semantic judgment, so scoring density is nearly free and
  gives every downstream consumer a signal with **no new input format and no alignment pass**.
  - Concretely: add `concept_density: float` (0..1) to `_Directive` + `BeatPlan` (per beat).
    Optionally a section-level density on `Section` too (chapter-scale ramps).
  - Deterministic-friendly: it's an LLM judgment (fits the no-regex-for-semantic-checks rule),
    emitted alongside the existing register/shot_brief work.

## Scope caution on the Director's system prompt
- The Visual Director's `_DIRECTOR_SYS` is scoped to **visual b-roll** (registers, shot briefs,
  search terms, variety). Do **not** stuff vibe-shift / audio / retention-armor instructions
  into it — different scope.
- It's fine to (a) add the density SCORE to its output object (a judgment it's well placed to
  make), and (b) note that user notes already flow into the director as a separate channel.
  But the ACTIONS on density belong elsewhere:
  - audio vibe-shift/SFX → Sound Director (consume the density score to decide where beds swell
    and stingers land).
  - visual overlay → a new director field + render pass (below).

## Visual concept-overlay — the one genuinely new build
- Data model already reserves `TrackKind = "caption" | "overlay"`, but `render.py` only
  composites `visual` + `audio` tracks today. So this needs:
  - a Director/overlay field: when a beat introduces a named framework, emit the list items +
    which one is active (e.g. `overlay: ["magic","amusement","art proper"]`, `highlight: 1`).
  - an ffmpeg `drawtext`/`ass` overlay pass over the b-roll (corner-pinned list, active item
    highlighted), spanning the beats the framework is discussed across.
- For faceless b-roll this is EASIER than for a facecam channel: the overlay sits on top of the
  moving b-roll, and lazier already owns the visual track. The Studio advice ("don't just stay
  on your talking-head shot") doesn't apply — translate it to "overlay rides on the b-roll."

## Effort ranking (when we come back to this)
1. **Density score on the Director object** — small (one field + a prompt line). Unlocks the
   rest. Do this first.
2. **Sound Director consumes density** — small prompt/logic tweak; the machinery exists.
3. **Visual concept-overlay** — real feature (Director field + render overlay pass). Biggest,
   but the highest-value visual retention tool.
- (Human-bridge is out of lazier entirely — lives in the write-broll-video skill.)

## Status
Notes only. No code. Sound-design (notes/13) already covers layer #2's machinery; this doc
adds the density signal that would make #2 fire on the right beats and defines #3.
