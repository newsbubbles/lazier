# lazier — decisions log (from intake Q&A, 2026-06-30)

Locked decisions from the two rounds of leading questions. These are the constraints the architecture in `../01-architecture/overview.md` is built around.

## Product

- **Primary genre to nail first: faceless narration + b-roll.** VO/script audio in, agents fill each phrase with stock + YouTube b-roll + AI images. Visuals illustrate the words. Engine should stay general enough to grow, but "good" is defined against this format.
- **Closest existing tools** (Opus Clip, Submagic, InVideo, Captions.ai) are repurpose-existing-video or template-fillers. None pair a real NLE timeline with autonomous Whisper-aligned source-gathering agents. lazier is a genuine gap.

## Autonomy model

- Not full-auto, not pure suggest. The agent **recommends one specific pick out of 2-3 candidates per section.** Sits between "auto-cut with gated review" and "suggest-only."
- Per section I can **accept the recommendation, swap to an alternate, regenerate, or override with my own clip/image.**
- The YouTube/sourcing agent should be able to **stream + trim down a video the way yt-download sites do** (that's yt-dlp under the hood, see below) AND use the **YouTube Data API for search** (Nate has keys). Two separate tools.

## Sources (priority + posture)

- **YouTube is the primary workhorse** (richest, most specific footage). Copyright-gray for published output; this is Nate's call and noted, no gating on it.
- **Free image/clip libraries** (Pexels/Pixabay-style) as cheap safe fill.
- **Memes** are explicitly wanted as a source.
- **AI-gen via FAL.ai** for custom visuals that exactly match a phrase.
- **Local media pool**: a workspace folder the agents pull from first. Nate doesn't have one yet; it must be an option when it exists.
- Sourcing agents need **tight constraints + good guidance** so they fetch the right thing, not junk.

## Transcription

- **Local faster-whisper / WhisperX** for word-level alignment. Free, private, runs on this box's GPU.
- TODO at build time: confirm which GPU is in THIS Windows machine (Nate has a 1070 and a 5090 across other projects) to size the model.

## Segmentation (core primitive)

- **Two passes:**
  1. Pass 1: raw Whisper timing (segments + gaps from voice timing).
  2. Pass 2: an agent reads the section transcripts and decides whether to **merge adjacent segments into coherent topic sections.**
- The **section** (post-merge) is the unit agents source visuals for.

## Captions

- **Optional, not required.** SRT is always written alongside the project, so YouTube / a video service can auto-caption, or the SRT can be uploaded.
- I can **toggle baked captions onto any section I choose.**
- The thing actually worth baking later: **stylized animated text** dropped into the frame with fade / short move / etc. Parked for a slightly later version.

## Aspect ratio

- **Chosen per-project at creation time.**
- **Multi-export with auto-reframe is a future feature**, not v1.

## Match rigor (quality lever)

- **Vision-verify** (sample frames, score fit) runs on **AI-gen outputs and on clips the fetching agent pulls.**
- Use **OpenRouter VLMs** for this (they host a collection).

## Stack latitude (from intake)

- Web UI + Python + FastAPI backend approved. pydantic-ai + fastmcp for the agentic layer.
- LLMs over **OpenRouter**, model-agnostic, default to Nate's non-anthropic pick (kimi-k2.5) for text agents, a VLM for vision.

## How yt-download sites actually work (Nate asked)

They wrap **yt-dlp** (maintained successor to youtube-dl). It does stream extraction, format selection, and section trimming via `--download-sections`. So: yt-dlp for grab/trim, YouTube Data API for search. Clean split.
