import { useEffect, useMemo, useRef, useState } from "react";
import WaveSurfer from "wavesurfer.js";
import { api } from "../lib/api";
import type { Project } from "../lib/types";

// The transcript-driven timeline: waveform spine + transcript ribbon + visual track,
// all on ONE shared time axis (pxPerSec) scrolling together. A clip sits directly
// under the words it illustrates — that vertical alignment is the whole idea.
export function Timeline({
  project, pxPerSec, cursor, onCursor, selectedSectionId, onSelectSection,
}: {
  project: Project;
  pxPerSec: number;
  cursor: number;
  onCursor: (t: number) => void;
  selectedSectionId: string | null;
  onSelectSection: (sid: string) => void;
}) {
  const waveRef = useRef<HTMLDivElement>(null);
  const innerRef = useRef<HTMLDivElement>(null);
  const wsRef = useRef<WaveSurfer | null>(null);
  const [playing, setPlaying] = useState(false);

  const duration = project.transcript?.duration
    || (project.audio_asset_id ? project.assets[project.audio_asset_id]?.duration : 0) || 0;
  const contentW = Math.max(duration * pxPerSec, 800);
  const audioUrl = project.audio_asset_id
    ? api.fileUrl(project.id, project.assets[project.audio_asset_id].local_path) : null;

  const filled = useMemo(() => {
    const set = new Set<string>();
    project.tracks.filter((t) => t.kind === "visual")
      .forEach((t) => t.clips.forEach((c) => c.section_id && set.add(c.section_id)));
    return set;
  }, [project]);

  const visualClips = useMemo(
    () => project.tracks.filter((t) => t.kind === "visual").flatMap((t) => t.clips),
    [project]
  );

  useEffect(() => {
    if (!waveRef.current || !audioUrl) return;
    const ws = WaveSurfer.create({
      container: waveRef.current,
      url: audioUrl,
      height: 60,
      fillParent: true,        // fills the contentW-wide container -> exact pxPerSec scale
      autoScroll: false,
      interact: true,
      waveColor: "#46506a",
      progressColor: "#5b78b0",
      cursorWidth: 0,
    });
    wsRef.current = ws;
    ws.on("audioprocess", (t: number) => onCursor(t));
    ws.on("seeking", (t: number) => onCursor(t));
    ws.on("play", () => setPlaying(true));
    ws.on("pause", () => setPlaying(false));
    ws.on("finish", () => setPlaying(false));
    return () => { ws.destroy(); wsRef.current = null; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [audioUrl]);

  const seekToClientX = (clientX: number) => {
    const el = innerRef.current;
    if (!el || !duration) return;
    const x = clientX - el.getBoundingClientRect().left + el.scrollLeft;
    const t = Math.max(0, Math.min(x / pxPerSec, duration));
    wsRef.current?.seekTo(t / duration);
    onCursor(t);
  };

  const sugStatus = (sid: string) => project.suggestions?.[sid]?.status;
  const ribbonColor = (sid: string) => {
    if (filled.has(sid)) return "var(--good)";
    const st = sugStatus(sid);
    if (st === "sourcing") return "var(--warn)";
    if (st === "ready") return "var(--accent)";
    if (st === "error") return "var(--bad)";
    return "var(--panel-2)";
  };

  const ticks = [];
  for (let s = 0; s <= duration; s += 5) ticks.push(s);

  return (
    <div className="tl">
      <div className="tl-transport">
        <button onClick={() => wsRef.current?.playPause()}>{playing ? "⏸" : "▶"}</button>
        <button onClick={() => { wsRef.current?.stop(); onCursor(0); }}>⏹</button>
        <span className="muted">{cursor.toFixed(2)}s / {duration.toFixed(1)}s</span>
      </div>

      <div className="tl-scroll">
        <div className="tl-inner" ref={innerRef} style={{ width: contentW }}>
          {/* ruler */}
          <div className="tl-ruler" onMouseDown={(e) => seekToClientX(e.clientX)}>
            {ticks.map((s) => (
              <span key={s} className="tick" style={{ left: s * pxPerSec }}>{s}s</span>
            ))}
          </div>

          {/* waveform spine */}
          <div className="tl-row tl-wave"><div ref={waveRef} style={{ width: "100%" }} /></div>

          {/* transcript ribbon */}
          <div className="tl-row tl-ribbon" onMouseDown={(e) => { if (e.target === e.currentTarget) seekToClientX(e.clientX); }}>
            {project.sections.map((s) => (
              <div key={s.id}
                   className={`ribbon-sec ${selectedSectionId === s.id ? "sel" : ""}`}
                   style={{ left: s.start * pxPerSec, width: Math.max((s.end - s.start) * pxPerSec - 2, 8),
                            borderColor: ribbonColor(s.id) }}
                   title={s.text}
                   onClick={() => onSelectSection(s.id)}>
                <div className="rs-label">{s.topic_label || "•"}</div>
                <div className="rs-text">{s.text}</div>
              </div>
            ))}
          </div>

          {/* visual track — clips sit under the words they illustrate */}
          <div className="tl-row tl-visual" onMouseDown={(e) => { if (e.target === e.currentTarget) seekToClientX(e.clientX); }}>
            {project.sections.map((s) => !filled.has(s.id) && (
              <div key={"e" + s.id} className="visual-empty"
                   style={{ left: s.start * pxPerSec, width: Math.max((s.end - s.start) * pxPerSec - 2, 8) }}
                   onClick={() => onSelectSection(s.id)}>
                {sugStatus(s.id) === "sourcing" ? "sourcing…" : "needs a visual"}
              </div>
            ))}
            {visualClips.map((c) => {
              const asset = project.assets[c.asset_id];
              const sug = c.section_id ? project.suggestions?.[c.section_id] : undefined;
              const thumb = sug?.candidates?.[sug.recommended_index]?.thumb;
              return (
                <div key={c.id} className="visual-clip"
                     style={{ left: c.timeline_start * pxPerSec,
                              width: Math.max((c.timeline_end - c.timeline_start) * pxPerSec - 2, 10) }}
                     onClick={() => c.section_id && onSelectSection(c.section_id)}>
                  {thumb && <img src={api.fileUrl(project.id, thumb)} alt="" />}
                  <span>{asset?.name ?? "clip"}</span>
                </div>
              );
            })}
          </div>

          {/* playhead across all rows */}
          <div className="tl-playhead" style={{ left: cursor * pxPerSec }} />
        </div>
      </div>
    </div>
  );
}
