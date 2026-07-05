import { useRef, useState } from "react";
import { api } from "../lib/api";
import type { Clip, Project, SoundCandidate, SoundCue } from "../lib/types";

// The audio-side sibling of SuggestionPanel: review + place music/SFX for one SoundCue,
// then fine-tune the placed clip (level, duck, fades, timing nudge).
export function SoundPanel({
  project, cue, busy, onChanged,
}: {
  project: Project; cue: SoundCue; busy: boolean; onChanged: (p?: Project) => void;
}) {
  const [url, setUrl] = useState("");
  const [err, setErr] = useState("");
  const sug = project.sound_suggestions?.[cue.id];
  const placed = project.tracks
    .filter((t) => t.kind === "audio")
    .flatMap((t) => t.clips)
    .find((c) => c.cue_id === cue.id);

  const find = async () => { setErr(""); try { await api.sourceCue(project.id, cue.id); onChanged(); } catch (e: any) { setErr(e.message); } };
  const use = async (i: number) => { try { onChanged(await api.acceptSoundCandidate(project.id, cue.id, i)); } catch (e: any) { setErr(e.message); } };
  const add = async () => {
    if (!url.trim()) return;
    setErr("");
    try { await api.captureSoundUrl(project.id, cue.id, url.trim()); setUrl(""); onChanged(); }
    catch (e: any) { setErr(e.message); }
  };

  return (
    <div className="sugpanel">
      <div className="sp-head">
        <div className="sp-title">
          <span className={`pill reg ${cue.kind}`}>{cue.kind}</span> {cue.dynamics}
        </div>
        <div className="sp-time">{cue.start.toFixed(1)}s – {cue.end.toFixed(1)}s</div>
      </div>
      <div className="sp-plan">
        <div className="sp-shot">🔊 {cue.brief}</div>
        {cue.intent && <div className="sp-brief">intent: {cue.intent}</div>}
        {cue.rationale && <div className="cand-why" style={{ marginTop: 4 }}>{cue.rationale}</div>}
        <div className="cand-meta" style={{ marginTop: 6 }}>
          {cue.duck && <span className="pill">ducks under voice</span>}
          <span className="pill">climax @ {cue.anchor.toFixed(1)}s</span>
        </div>
      </div>

      <div className="row" style={{ margin: "10px 0 4px", gap: 8 }}>
        <button className="primary" onClick={find} disabled={busy || sug?.status === "sourcing"}>
          {sug?.candidates?.length ? "↻ Re-source" : "🔎 Find sounds"}
        </button>
      </div>
      <div className="capture-row">
        <input value={url} onChange={(e) => setUrl(e.target.value)}
               placeholder="paste a YouTube URL (audio pulled at ?t=)…"
               onKeyDown={(e) => e.key === "Enter" && add()} />
        <button onClick={add} disabled={busy || !url.trim()}>➕ Add</button>
      </div>
      {err && <div className="err" style={{ fontSize: 11, marginBottom: 4 }}>{err}</div>}
      {sug?.status === "sourcing" && <div className="muted">sourcing… pulling audio for this cue</div>}
      {sug?.status === "error" && <div className="err">{sug.error}</div>}

      {placed && <ClipControls project={project} clip={placed} onChanged={onChanged} />}

      <div className="cards">
        {sug?.candidates?.map((c, i) => {
          const isRec = i === sug.recommended_index;
          const isPlaced = placed?.asset_id === c.asset_id;
          return (
            <div key={c.asset_id} className={`cand ${isPlaced ? "placed" : ""}`}>
              <div className="cand-body" style={{ width: "100%" }}>
                <div className="cand-title">{c.title}</div>
                <SoundPreview project={project} c={c} />
                <div className="cand-meta">
                  <span className="pill">{c.source}</span>
                  <span className="pill">{c.duration.toFixed(1)}s</span>
                  {c.flags.map((f) => <span key={f} className="pill flag">{f}</span>)}
                  {isRec && <span className="pill">recommended</span>}
                </div>
                <button className={isPlaced ? "" : "primary"} disabled={busy || isPlaced}
                        onClick={() => use(i)}>
                  {isPlaced ? "✓ on timeline" : "Use this"}
                </button>
              </div>
            </div>
          );
        })}
      </div>

      {!sug?.candidates?.length && sug?.status !== "sourcing" && (
        <div className="muted" style={{ fontSize: 12 }}>
          No sound yet. Hit “Find sounds” to pull music/SFX for this cue, or paste a YouTube URL.
        </div>
      )}
    </div>
  );
}

// Waveform image + tap-to-audition (the sound plays; the waveform is the visual handle).
function SoundPreview({ project, c }: { project: Project; c: SoundCandidate }) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const asset = project.assets[c.asset_id];
  const [playing, setPlaying] = useState(false);
  const toggle = () => {
    const a = audioRef.current;
    if (!a) return;
    if (a.paused) { a.currentTime = 0; a.play().catch(() => {}); setPlaying(true); }
    else { a.pause(); setPlaying(false); }
  };
  return (
    <div className="wf" onClick={toggle} title="tap to audition">
      {c.waveform
        ? <img src={api.fileUrl(project.id, c.waveform)} alt="" />
        : <div className="wf-none muted">no waveform</div>}
      <span className="wf-play">{playing ? "❚❚" : "▶"}</span>
      {asset?.local_path && (
        <audio ref={audioRef} src={api.fileUrl(project.id, asset.local_path)} preload="none"
               onEnded={() => setPlaying(false)} />
      )}
    </div>
  );
}

// Per-clip mix controls for a placed sound: level, duck, fades, and a manual timing nudge.
function ClipControls({ project, clip, onChanged }: {
  project: Project; clip: Clip; onChanged: (p?: Project) => void;
}) {
  const patch = async (body: Record<string, unknown>) => {
    await api.updateClip(project.id, clip.id, body);
    onChanged();
  };
  return (
    <div className="clip-ctl">
      <div className="clip-ctl-h">placed clip</div>
      <label>level <span>{Math.round(clip.gain * 100)}%</span>
        <input type="range" min={0} max={1.5} step={0.05} defaultValue={clip.gain}
               onMouseUp={(e) => patch({ gain: parseFloat((e.target as HTMLInputElement).value) })}
               onTouchEnd={(e) => patch({ gain: parseFloat((e.target as HTMLInputElement).value) })} />
      </label>
      <label>nudge <span>{clip.align_offset > 0 ? "+" : ""}{clip.align_offset.toFixed(2)}s</span>
        <input type="range" min={-2} max={2} step={0.05} defaultValue={clip.align_offset}
               onMouseUp={(e) => patch({ align_offset: parseFloat((e.target as HTMLInputElement).value) })}
               onTouchEnd={(e) => patch({ align_offset: parseFloat((e.target as HTMLInputElement).value) })} />
      </label>
      <label className="clip-ctl-chk">
        <input type="checkbox" checked={clip.duck !== false}
               onChange={(e) => patch({ duck: e.target.checked })} />
        duck under voice
      </label>
    </div>
  );
}
