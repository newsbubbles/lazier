import { useEffect, useMemo, useRef, useState } from "react";
import WaveSurfer from "wavesurfer.js";
import { api } from "../lib/api";
import type { Clip, Project } from "../lib/types";

// Transcript-driven timeline. One shared time axis (pxPerSec), everything scrolls
// together. Sections (chapters) are the thin context band; BEATS are the visual
// units — one clip slot per speech chunk, reactive to the moment's words.
// Clicking a chapter or a beat seeks the master audio there (scrub by section/beat).
export function Timeline({
  project, pxPerSec, onZoom, cursor, onCursor, onPlaying, selectedBeatId, onSelectBeat,
}: {
  project: Project;
  pxPerSec: number;
  onZoom: (pps: number) => void;
  cursor: number;
  onCursor: (t: number) => void;
  onPlaying?: (playing: boolean) => void;
  selectedBeatId: string | null;
  onSelectBeat: (bid: string) => void;
}) {
  const waveRef = useRef<HTMLDivElement>(null);
  const innerRef = useRef<HTMLDivElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const wsRef = useRef<WaveSurfer | null>(null);
  const [playing, setPlaying] = useState(false);
  const ppsRef = useRef(pxPerSec);
  ppsRef.current = pxPerSec;

  const duration = project.transcript?.duration
    || (project.audio_asset_id ? project.assets[project.audio_asset_id]?.duration : 0) || 0;
  const contentW = Math.max(duration * pxPerSec, 800);
  const audioUrl = project.audio_asset_id
    ? api.fileUrl(project.id, project.assets[project.audio_asset_id].local_path) : null;

  const clipByBeat = useMemo(() => {
    const map = new Map<string, Clip>();
    project.tracks.filter((t) => t.kind === "visual")
      .forEach((t) => t.clips.forEach((c) => c.beat_id && map.set(c.beat_id, c)));
    return map;
  }, [project]);

  useEffect(() => {
    if (!waveRef.current || !audioUrl) return;
    const ws = WaveSurfer.create({
      container: waveRef.current, url: audioUrl, height: 56,
      fillParent: true, autoScroll: false, interact: true,
      waveColor: "#46506a", progressColor: "#5b78b0", cursorWidth: 0,
    });
    wsRef.current = ws;
    ws.on("audioprocess", (t: number) => onCursor(t));
    ws.on("seeking", (t: number) => onCursor(t));
    ws.on("play", () => { setPlaying(true); onPlaying?.(true); });
    ws.on("pause", () => { setPlaying(false); onPlaying?.(false); });
    ws.on("finish", () => { setPlaying(false); onPlaying?.(false); });
    return () => { ws.destroy(); wsRef.current = null; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [audioUrl]);

  // spacebar toggles play/pause (unless you're typing in a field or on a button, which
  // already handle space themselves).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.code !== "Space" && e.key !== " ") return;
      const el = e.target as HTMLElement | null;
      const tag = el?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "BUTTON" || el?.isContentEditable) return;
      if (!wsRef.current) return;
      e.preventDefault();
      wsRef.current.playPause();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  // ctrl+wheel = zoom (anchored under the mouse); plain wheel = horizontal pan.
  // Native non-passive listener so we can preventDefault the page scroll.
  useEffect(() => {
    const sc = scrollRef.current;
    if (!sc) return;
    const onWheel = (e: WheelEvent) => {
      if (e.ctrlKey) {
        e.preventDefault();
        const rect = sc.getBoundingClientRect();
        const tAt = (e.clientX - rect.left + sc.scrollLeft) / ppsRef.current;
        const next = Math.max(15, Math.min(400, ppsRef.current * (e.deltaY < 0 ? 1.15 : 1 / 1.15)));
        onZoom(next);
        requestAnimationFrame(() => { sc.scrollLeft = tAt * next - (e.clientX - rect.left); });
      } else {
        e.preventDefault();
        sc.scrollLeft += e.deltaY + e.deltaX;
      }
    };
    sc.addEventListener("wheel", onWheel, { passive: false });
    return () => sc.removeEventListener("wheel", onWheel);
  }, [onZoom]);

  // auto-PAGE (not realtime follow): when the playhead leaves the viewport, jump so
  // it lands near the left edge and keep reading from there.
  useEffect(() => {
    const sc = scrollRef.current;
    if (!sc) return;
    const x = cursor * pxPerSec;
    if (x > sc.scrollLeft + sc.clientWidth - 48 || x < sc.scrollLeft) {
      sc.scrollLeft = Math.max(0, x - 48);
    }
  }, [cursor, pxPerSec]);

  const seek = (t: number) => {
    if (!duration) return;
    const tt = Math.max(0, Math.min(t, duration));
    wsRef.current?.seekTo(tt / duration);
    onCursor(tt);
  };
  const seekClientX = (clientX: number) => {
    const el = innerRef.current;
    if (!el) return;
    seek((clientX - el.getBoundingClientRect().left + el.scrollLeft) / pxPerSec);
  };

  const sugStatus = (bid: string) => project.suggestions?.[bid]?.status;
  const beatColor = (bid: string) => {
    if (clipByBeat.has(bid)) return "var(--good)";
    const st = sugStatus(bid);
    if (st === "sourcing") return "var(--warn)";
    if (st === "ready") return "var(--accent)";
    if (st === "error") return "var(--bad)";
    return "var(--border)";
  };

  const ticks: number[] = [];
  for (let s = 0; s <= duration; s += 5) ticks.push(s);

  return (
    <div className="tl">
      <div className="tl-transport">
        <button onClick={() => wsRef.current?.playPause()}>{playing ? "⏸" : "▶"}</button>
        <button onClick={() => { wsRef.current?.stop(); onCursor(0); }}>⏹</button>
        <span className="muted">{cursor.toFixed(2)}s / {duration.toFixed(1)}s</span>
        <span className="muted">· {project.beats.length} beats / {project.sections.length} chapters</span>
        <div className="spacer" />
        <span className="muted" style={{ fontSize: 11 }}>ctrl+wheel zoom · wheel pan</span>
      </div>

      <div className="tl-scroll" ref={scrollRef}>
        <div className="tl-inner" ref={innerRef} style={{ width: contentW }}>
          <div className="tl-ruler" onMouseDown={(e) => seekClientX(e.clientX)}>
            {ticks.map((s) => <span key={s} className="tick" style={{ left: s * pxPerSec }}>{s}s</span>)}
          </div>

          {/* chapters (context + nav) */}
          <div className="tl-row tl-chapters" onMouseDown={(e) => { if (e.target === e.currentTarget) seekClientX(e.clientX); }}>
            {project.sections.map((s) => (
              <div key={s.id} className="chapter"
                   style={{ left: s.start * pxPerSec, width: Math.max((s.end - s.start) * pxPerSec - 2, 8) }}
                   title={s.visual_brief || s.text} onClick={() => seek(s.start)}>
                {s.topic_label || "chapter"}
              </div>
            ))}
          </div>

          {/* waveform spine */}
          <div className="tl-row tl-wave"><div ref={waveRef} style={{ width: "100%" }} /></div>

          {/* beats = visual slots, one clip per speech chunk */}
          <div className="tl-row tl-beats" onMouseDown={(e) => { if (e.target === e.currentTarget) seekClientX(e.clientX); }}>
            {project.beats.map((b) => {
              const clip = clipByBeat.get(b.id);
              const sug = project.suggestions?.[b.id];
              const thumb = clip && sug?.candidates?.[sug.recommended_index]?.thumb;
              const w = Math.max((b.end - b.start) * pxPerSec - 2, 6);
              return (
                <div key={b.id}
                     className={`beat ${clip ? "filled" : "empty"} ${selectedBeatId === b.id ? "sel" : ""}`}
                     style={{ left: b.start * pxPerSec, width: w, borderColor: beatColor(b.id) }}
                     title={b.text}
                     onClick={() => { onSelectBeat(b.id); seek(b.start); }}>
                  {thumb && <img src={api.fileUrl(project.id, thumb)} alt="" />}
                  <span className="beat-cap">
                    {clip ? (project.assets[clip.asset_id]?.name ?? "clip")
                      : sugStatus(b.id) === "sourcing" ? "sourcing…" : b.text.slice(0, 24)}
                  </span>
                </div>
              );
            })}
          </div>

          <div className="tl-playhead" style={{ left: cursor * pxPerSec }} />
        </div>
      </div>
    </div>
  );
}
