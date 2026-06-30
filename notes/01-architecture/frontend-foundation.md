# lazier — frontend foundation decision (2026-06-30)

From live library research (June 2026). Full per-library scorecard in the research, condensed here to the decision.

## Decision: React, not SvelteKit

The agentic backend is Python/FastAPI and fully decoupled, so framework choice is purely about timeline/media ecosystem maturity. On that axis it isn't close.

- React has an **MIT, no-render-lock, ready-made multi-track timeline component** (`@xzdarcy/react-timeline-editor`), plus solid players.
- SvelteKit has **no equivalent**. Every Svelte "video timeline" is a Gantt chart, an activity feed, or a proprietary SDK that owns rendering. You'd hand-build the timeline on svelte-konva from scratch (~1-2 extra weeks).
- The shared libs (wavesurfer.js, Konva) are framework-agnostic, so Svelte wouldn't even win the waveform layer. The hard part (multi-track clip timeline) is the one part only React has off the shelf.

If Nate has a strong Svelte preference, the honest cost is "+1-2 weeks building the timeline yourself on svelte-konva." Otherwise React.

## The rule that killed the obvious candidates

Most "video editor" libs **render client-side and want to own the render**, which collides with our ffmpeg-server design:

- **Remotion** renders via headless Chrome (Puppeteer). Also company license required above a size threshold. Out. (Its timeline tutorial is still worth reading for clip/track data modeling.)
- **@designcombo/react-video-editor (openvideo)** rebuilt on its own PixiJS export engine, dual-license. Out as a dep; fine as a UX reference.
- **etro** is itself a client-side WebGL render engine, and GPL-3.0. Out.

We want timeline/waveform building blocks, not an engine.

## Concrete stack

| Need | Pick | License | Notes |
|---|---|---|---|
| Multi-track timeline (drag/resize/snap) | **`@xzdarcy/react-timeline-editor`**, vendored/forked | MIT | Only OSS React component that's a building block, not an engine. Emits time data + callbacks, zero render lock. Single-maintainer (~660 stars) so vendor it into the repo day one. |
| Master audio waveform spine | **wavesurfer.js v7** (Regions plugin) | BSD-3 | Most active (v7.12.8, Jun 2026). Single-track is fine for one spine. |
| Proxy player, locked to audio | **vidstack/player** (`@vidstack/react`) | MIT | Precise programmatic seek/time API, HLS-ready for chunked proxies. |
| Live caption/text overlay | **build it** (absolutely-positioned DOM/CSS over `<video>`) | — | Trivial, keeps client overlay decoupled from server render. |
| Timeline fallback if we outgrow xzdarcy | **Konva + react-konva** | MIT | Same clip/track data model, contained migration not a rewrite. |

## What we build ourselves (the real work)

- **Master-clock sync engine**: wavesurfer's audio clock is the master; slave vidstack's `currentTime` to it; drive the timeline playhead from the same clock. Custom regardless of libraries, this is the bulk of frontend time.
- **Snap-to-boundary** beyond xzdarcy's basic grid snap (snap clips to section + word boundaries from Whisper): custom, on the drag callbacks.
- **Caption overlay**: small custom DOM.

Everything else (waveform draw, clip drag visuals, player chrome) is library-provided. No lib in this stack owns rendering, so ffmpeg stays server-side as designed.

## Optional pairing

peaks.js (BBC) is the heavier waveform alt with zoomable overview+detail, and it pairs with BBC `audiowaveform` to precompute waveform data in the Python/ffmpeg pipeline. Hold unless wavesurfer's single zoom view feels limiting.
