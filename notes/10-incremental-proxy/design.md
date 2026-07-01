# Incremental proxy preview — only re-render what changed

## Problem
A proxy render is ~2 min because it re-decodes all ~100 clips and re-composites the whole
12.5-min timeline every time, even when you changed ONE beat. We want: edit a beat →
preview updates in seconds, not minutes.

## Answer to "do we need a dirty flag on clips?"
No. A dirty boolean is fragile — every code path that mutates a clip has to remember to set
it, and it can drift out of sync with reality. Instead, key each rendered piece by a
**content hash of everything that affects it**. If the hash matches a cached tile, reuse it;
if not, rebuild. The cache key IS the dirty check — self-synchronizing, can't be forgotten,
and it also lets identical content be reused across edits (e.g. a pure time-shift). This
matches the determinism principle: state defines the artifact, not a side flag.

## Approach: per-beat proxy tiles + concat (recommended)
Beats already tile the whole timeline with no gaps (flush), and — importantly — today's
filtergraph is already **per-beat independent**: fades, ken-burns, and the overlay
`enable=between(t,...)` are all self-contained within one beat. There are no cross-beat
transitions. So we can render each beat as its own small proxy clip and stitch them.

1. **Tile per beat.** For each beat render a self-contained proxy segment (video only,
   duration = beat length, PTS from zero) with identical encoder params: filled beat = its
   clip composited over black; empty beat = a black tile.
2. **Cache by hash.** `workspace/{pid}/proxies/tiles/{hash}.mp4`, where hash covers:
   asset_id + asset.local_path, source_in/out, beat duration, transforms (scale/x/y/
   ken_burns), effects (fades), canvas WxH, fps. Empty beat → hash of `black:{dur}:{WxH}`
   (reused across all same-duration empties).
3. **Stitch with the concat demuxer** (`-c copy`, no re-encode) into `preview.mp4`. Instant,
   and seams are exact because every tile shares codec/timebase/fps and starts on a keyframe
   (we already force dense keyframes for the proxy).
4. **Edit one beat →** only that tile's hash changes → rebuild that one tile (a few seconds)
   → re-concat (instant). First render is the same cost as today; every render after is cheap.

## Why video-only tiles
The preview `<video>` is muted and slaved to the wavesurfer audio clock (M3); wavesurfer
loads the source mp3 directly. So the proxy never needs baked audio — dropping it removes
the audio re-encode from the preview path and makes tiles purely visual. (Export keeps
muxing real audio — see below.)

## Keep export monolithic
Only the PROXY gets tiled (speed matters, CRF30, throwaway). The final **export stays the
proven single-pass path** (full res, real audio mux, SRT + chapters). This de-risks: the
fast cache can't corrupt a deliverable.

## Honest caveats
- **First render unchanged** (~2 min): every tile is cold. The win is all subsequent edits.
- **Future cross-beat transitions** (crossfades between beats) would make a tile depend on
  its neighbor at the seam; then that tile's hash must include the neighbor. Note it now so
  we don't design it out. Today there are none, so tiling is clean.
- **Cache GC**: drop tile files whose hash isn't referenced by any current beat; cheap
  periodic sweep.
- **Concat param drift**: all tiles must be encoded with byte-identical settings or `-c copy`
  concat rejects them. Centralize the tile encode settings in one place.

## Effort / sequencing
Medium. Refactor `_build_command` to emit a per-beat tile command + a hash/cache layer + a
concat step, behind `render_proxy` only. Suggest doing it AFTER the web-capture hardening
(notes/09) and the bad-clip robustness fix, since those affect correctness of what lands in
the tiles.

## Related bad-clip robustness (surfaced during render-progress work)
A single corrupt/partial sourced clip (e.g. a failed fetch) currently fails the WHOLE
render (`ffmpeg failed:` on that input). Fix direction: probe each clip before building the
command and either (a) skip it with a loud, logged warning naming the beat, or (b) error
naming the beat so it can be re-sourced. Per the no-silent-degrade rule, prefer (b) or a
very loud (a). This should land before tiling, so a bad clip fails one tile, not the batch.
