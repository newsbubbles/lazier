# lazier — original request (2026-06-30)

Captured verbatim-in-spirit from Nate's intake message. This is the source of truth for what was actually asked; my interpretation lives in `synthesis.md`.

## The ask

An agent harness plus a UI for **audio-driven video editing**. An audio source drives the visuals. The system makes resource-gathering for clips, images, and effects easy to get and add in, all in one UI.

- Mostly **autonomous**. Uses agents that have access to:
  - **Serper** (web search)
  - **YouTube API** for video clips (needs a yt downloader, possibly engineer one that just grabs clips and guarantees correct format)
  - **Generative image sources**, including AI generation hubs like **FAL.ai** for custom images
- Should **feel like a real video editor** in the UI: arrange clips around the audio, viewport size, all the standard NLE stuff.
- Agents have **little visual presence**. They work behind the scenes to find the perfect clips/images for each part of the transcript. Their suggestions, timing, etc. show up in the clip-arrangement area, with the audio as the guiding track.
- **Whisper** does audio-based timing via the transcript. This feeds the agents the timing/sources for how the visuals line up to the audio.
- **ffmpeg** drives the actual video rendering.
- **Multi-track**, including audio tracks (background music, sound effects).
- Vibe: a **low-effort audio-to-video system** that uses the Whisper transcript to produce a properly edited video. Nate isn't sure if this exists already.

## Stack latitude given

- Doesn't care about language. WebUI + Python + FastAPI backend is fine and would help with **pydantic-ai** and **fastmcp** (tried-and-tested agentic stack).
- Wants the **agentic backbone** thought through, plus how much control is needed in the UI.
- Goal: **least work possible for the user, highest quality video out**.
- **OpenRouter** for LLMs.

## Process ask

1. Take notes on the original request (this file).
2. Walk through the feature sets together; ask leading questions.
3. End with a full system that can work and show results, with architecture planned out to make implementation easier.

## Name / location

- Project name: **lazier**
- Location: **D:\lazier\**
