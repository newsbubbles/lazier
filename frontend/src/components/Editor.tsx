import { useCallbackRef } from "../lib/useCallbackRef";
import { useEffect, useRef, useState } from "react";
import { api } from "../lib/api";
import type { Project } from "../lib/types";
import { Timeline } from "./Timeline";
import { SuggestionPanel } from "./SuggestionPanel";
import { SoundPanel } from "./SoundPanel";

export function Editor({ projectId, onClose }: { projectId: string; onClose: () => void }) {
  const [project, setProject] = useState<Project | null>(null);
  const [cursor, setCursor] = useState(0);
  const [pxPerSec, setPxPerSec] = useState(90);
  const [log, setLog] = useState<string[]>([]);
  const [selectedBeat, setSelectedBeat] = useState<string | null>(null);
  const [selectedCue, setSelectedCue] = useState<string | null>(null);
  const [proxyUrl, setProxyUrl] = useState<string | null>(null);
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState("");
  const [pct, setPct] = useState<number | null>(null);   // determinate progress 0..1, or null
  const [err, setErr] = useState("");
  const [leftOpen, setLeftOpen] = useState(false);       // mobile drawers
  const [rightOpen, setRightOpen] = useState(false);
  const [exportOpen, setExportOpen] = useState(false);   // Export dropdown
  const srcTotal = useRef(0);
  const srcDone = useRef(0);

  const audioInput = useRef<HTMLInputElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const [playing, setPlaying] = useState(false);
  const cursorRef = useRef(0);
  cursorRef.current = cursor;

  // The proxy video is slaved to the waveform's clock. BEFORE a render exists it's silent
  // and the waveform plays the voice spine. ONCE a proxy is rendered it already contains the
  // full mix (voice + music + SFX), so we unmute the video and mute the waveform — otherwise
  // you'd hear the voice-only master and never the music/SFX you placed.
  // Scrub the timeline -> video seeks; play -> both run; light drift correction.
  useEffect(() => {
    const v = videoRef.current;
    if (!v || !proxyUrl) return;
    const tol = playing ? 0.3 : 0.05;
    if (Math.abs(v.currentTime - cursor) > tol) v.currentTime = cursor;
  }, [cursor, playing, proxyUrl]);

  const onPlaying = (p: boolean) => {
    setPlaying(p);
    const v = videoRef.current;
    if (!v || !proxyUrl) return;
    v.currentTime = cursorRef.current;
    if (p) v.play().catch(() => {}); else v.pause();
  };

  const reload = useCallbackRef((p?: Project) =>
    p ? Promise.resolve(setProject(p))
      : api.getProject(projectId).then(setProject).catch((e) => setErr(e.message)));

  useEffect(() => { reload(); }, [projectId]);

  // Restore the last-rendered proxy on load — it persists on disk as preview.mp4, the
  // frontend just wasn't pointing at it after a refresh. HEAD it; adopt it if present.
  useEffect(() => {
    const u = `/files/${projectId}/proxies/preview.mp4`;
    fetch(u, { method: "HEAD" }).then((r) => { if (r.ok) setProxyUrl(u + `?t=${Date.now()}`); }).catch(() => {});
  }, [projectId]);

  useEffect(() => {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/ws/${projectId}`);
    ws.onmessage = (ev) => {
      const m = JSON.parse(ev.data);
      let line = "";
      if (m.stage === "transcribe" && m.progress != null) { line = `transcribe ${Math.round(m.progress * 100)}%`; setPct(m.progress); }
      else if (m.stage === "render" && m.progress != null) { line = `rendering ${m.kind} ${Math.round(m.progress * 100)}%`; setPct(m.progress); }
      else if (m.stage === "render_done") { line = `✓ ${m.kind} render done`; setPct(null); }
      else if (m.stage === "source" && m.msg) line = `· ${m.msg}`;
      else if (m.stage === "source_done") { srcDone.current += 1; if (srcTotal.current) setPct(srcDone.current / srcTotal.current); line = `✓ section sourced (${m.candidates} clips)`; }
      else if (m.stage === "source_all_start") { srcTotal.current = m.count; srcDone.current = 0; setPct(0); line = `sourcing ${m.count} sections…`; }
      else if (m.stage === "source_all_done") line = `done sourcing all`;
      else if (m.stage === "sound" && m.msg) line = `♪ ${m.msg}`;
      else if (m.stage === "sound_planned") line = `♪ sound director planned ${m.cues} cues`;
      else if (m.stage === "sound_all_start") { srcTotal.current = m.count; srcDone.current = 0; setPct(0); line = `sourcing ${m.count} sound cues…`; }
      else if (m.stage === "sound_done") { srcDone.current += 1; if (srcTotal.current) setPct(srcDone.current / srcTotal.current); line = `♪ cue sourced (${m.candidates})`; }
      else if (m.stage === "sound_all_done") line = `done sourcing sound`;
      else if (m.stage === "error") line = `ERROR: ${m.error}`;
      else line = JSON.stringify(m);
      setLog((l) => [...l.slice(-80), line]);
      if (["done", "source_done", "source_all_done", "sound_planned", "sound_done", "sound_all_done", "error"].includes(m.stage)) reload();
      if (["done", "source_all_done", "sound_all_done"].includes(m.stage)) { setBusy(""); setPct(null); }
    };
    return () => ws.close();
  }, [projectId]);

  if (!project) return <div className="wrap"><p className="muted">Loading…</p></div>;

  const audioAsset = project.audio_asset_id ? project.assets[project.audio_asset_id] : null;
  const beatObj = project.beats.find((b) => b.id === selectedBeat) || null;
  const cueObj = project.sound_cues?.find((c) => c.id === selectedCue) || null;
  const sourcedCount = project.tracks.find((t) => t.kind === "visual")?.clips.filter(c => c.beat_id).length ?? 0;

  const onAudio = async (f: File) => {
    setErr(""); setBusy("uploading audio");
    try { setProject(await api.uploadAudio(projectId, f)); } catch (e: any) { setErr(e.message); }
    setBusy("");
  };
  const transcribe = async () => {
    setErr(""); setBusy("transcribing"); setLog((l) => [...l, "starting transcription…"]);
    try { await api.transcribe(projectId, true); } catch (e: any) { setErr(e.message); setBusy(""); }
  };
  const resegment = async () => {
    setErr(""); setBusy("re-segmenting"); setLog((l) => [...l, "re-segmenting chapters + beats…"]);
    try { await api.resegment(projectId); } catch (e: any) { setErr(e.message); setBusy(""); }
  };
  const sourceAll = async () => {
    setErr(""); setBusy("auto-sourcing"); setPct(0);
    try { await api.sourceAll(projectId, undefined, notes); } catch (e: any) { setErr(e.message); setBusy(""); setPct(null); }
  };
  const doProxy = async () => {
    setErr(""); setBusy("rendering preview"); setPct(0);
    try { const { url } = await api.renderProxy(projectId); setProxyUrl(url + `?t=${Date.now()}`); }
    catch (e: any) { setErr(e.message); }
    setBusy(""); setPct(null);
  };
  const doExport = async () => {
    setErr(""); setBusy("exporting"); setPct(0);
    try { const r = await api.renderExport(projectId); window.open(r.video, "_blank"); }
    catch (e: any) { setErr(e.message); }
    setBusy(""); setPct(null);
  };
  const copyChapters = async () => {
    setErr("");
    try {
      const { text } = await api.chapters(projectId);
      await navigator.clipboard.writeText(text);
      setLog((l) => [...l, "✓ YT chapters copied to clipboard (also saved as chapters.txt)"]);
    } catch (e: any) { setErr(e.message); }
  };
  const doShort = async () => {
    setErr(""); setBusy("making short");
    try {
      const r = await api.makeShort(projectId);
      setLog((l) => [...l, `✓ short: "${r.hook}" (${r.duration}s)`]);
      window.open(r.video, "_blank");
    } catch (e: any) { setErr(e.message); }
    setBusy("");
  };
  const doFull = async () => {
    setErr("");
    try {
      setBusy("exporting video"); setPct(0);
      await api.renderExport(projectId); setPct(null);
      setBusy("making short");
      await api.makeShort(projectId);
      setBusy("writing chapters");
      await api.chapters(projectId);
      setLog((l) => [...l, "✓ full export: video + short + chapters"]);
    } catch (e: any) { setErr(e.message); }
    setBusy(""); setPct(null);
  };
  const soundAll = async () => {
    setErr(""); setBusy("scoring sound"); setPct(0);
    try { await api.soundSourceAll(projectId, notes); } catch (e: any) { setErr(e.message); setBusy(""); setPct(null); }
  };
  // selecting a beat opens the clips drawer on mobile (no-op visually on desktop); beat and
  // cue selection are mutually exclusive (one right-panel).
  const selectBeat = (id: string | null) => { setSelectedBeat(id); setSelectedCue(null); if (id) setRightOpen(true); };
  const selectCue = (id: string | null) => { setSelectedCue(id); setSelectedBeat(null); if (id) setRightOpen(true); };
  const toggleVoice = async (enabled: boolean) => {
    setErr("");
    try { setProject(await api.setVoiceEnhance(projectId, enabled)); }
    catch (e: any) { setErr(e.message); }
  };

  return (
    <div className="editor">
      <div className="topbar">
        <button className="drawer-toggle" onClick={() => setLeftOpen((v) => !v)} title="Tools panel">☰</button>
        <span className="brand">laz<span>ier</span></span>
        <span className="muted">{project.name}</span>
        <span className="pill">{project.aspect_ratio}</span>
        <span className="pill">{project.rights_posture}</span>
        <div className="spacer" />
        <button className="drawer-toggle" onClick={() => setRightOpen((v) => !v)} title="Clips panel">🎬</button>
        {busy && (
          <span className="busy-ind">
            <span className="spinner" />
            {busy}…{pct != null ? ` ${Math.round(pct * 100)}%` : ""}
          </span>
        )}
      </div>
      {pct != null && (
        <div className="progressbar"><div className="bar" style={{ width: `${Math.round(pct * 100)}%` }} /></div>
      )}

      <div className="editor-main">
        {(leftOpen || rightOpen) && (
          <div className="drawer-backdrop" onClick={() => { setLeftOpen(false); setRightOpen(false); }} />
        )}
        <div className={`side${leftOpen ? " open" : ""}`}>
          <h3>Audio spine</h3>
          {!audioAsset ? (
            <>
              <button className="primary" onClick={() => audioInput.current?.click()}>Upload audio</button>
              <input ref={audioInput} type="file" accept="audio/*,video/*" hidden
                     onChange={(e) => e.target.files?.[0] && onAudio(e.target.files[0])} />
            </>
          ) : <div className="muted" style={{ fontSize: 12 }}>{audioAsset.name} · {audioAsset.duration.toFixed(1)}s</div>}

          {audioAsset && (
            <div className="row" style={{ marginTop: 8, gap: 6 }}>
              <button onClick={transcribe} disabled={!!busy}>
                {project.sections.length ? "Re-transcribe" : "Transcribe → segment"}
              </button>
              {project.sections.length > 0 && (
                <button onClick={resegment} disabled={!!busy} title="Re-run chapters + beats on the existing transcript (no Whisper)">
                  Re-segment
                </button>
              )}
            </div>
          )}

          {project.sections.length > 0 && (
            <>
              <h3>Auto-assemble</h3>
              <textarea className="notes-box" value={notes} onChange={(e) => setNotes(e.target.value)}
                        placeholder="director notes (optional): what you want, a vibe, a specific scene… applies to Find clips too" />
              <button className="primary" onClick={sourceAll} disabled={!!busy} style={{ width: "100%" }}>
                ✨ Auto-source all beats
              </button>
              <div className="muted" style={{ fontSize: 12, marginTop: 6 }}>
                {sourcedCount}/{project.beats.length} beats have a clip. Agents find b-roll
                reactive to each moment; click any beat to review or swap.
              </div>

              <h3>Sound design</h3>
              <button className="primary" onClick={soundAll} disabled={!!busy} style={{ width: "100%" }}>
                🎚 {project.sound_cues?.length ? "Re-score sound" : "Score music + SFX"}
              </button>
              <div className="muted" style={{ fontSize: 12, marginTop: 6 }}>
                {project.sound_cues?.length
                  ? `${project.sound_cues.length} cues planned. Click a cue on the Music/SFX rows to audition or swap.`
                  : "A sound director plans a sparse set of music beds + SFX stingers, ducked under your voice."}
              </div>
            </>
          )}

          <h3>Agent activity</h3>
          <div className="log">{log.length === 0 ? "idle" : log.map((l, i) => <div key={i}>{l}</div>)}</div>
          <button onClick={onClose} className="back-btn">← Projects</button>
        </div>

        <div className="stage">
          <div className="toolbar">
            <button onClick={doProxy} disabled={!audioAsset || !!busy}>Render preview</button>
            <div className="dropdown">
              <button className="primary" onClick={() => setExportOpen((v) => !v)}
                      disabled={!audioAsset || !!busy}>Export ▾</button>
              {exportOpen && (
                <>
                  <div className="dropdown-backdrop" onClick={() => setExportOpen(false)} />
                  <div className="dropdown-menu">
                    <label className="dd-toggle">
                      <input type="checkbox" checked={!!project.voice_enhance}
                             onChange={(e) => toggleVoice(e.target.checked)} />
                      Enhance voice <span className="dd-sub">podcast vocal chain</span>
                    </label>
                    <div className="dd-sep" />
                    <button onClick={() => { setExportOpen(false); doFull(); }}>
                      Full <span className="dd-sub">video + short + chapters</span>
                    </button>
                    <button onClick={() => { setExportOpen(false); doExport(); }}>Video</button>
                    <button onClick={() => { setExportOpen(false); doShort(); }}>Short</button>
                    <button onClick={() => { setExportOpen(false); copyChapters(); }}
                            disabled={!project.sections.length}>YT Chapters</button>
                  </div>
                </>
              )}
            </div>
            <div className="spacer" />
            <span className="muted">{project.sections.length} sections</span>
          </div>

          <div className="viewport">
            <video ref={videoRef} src={proxyUrl ?? undefined} muted={!proxyUrl} playsInline
                   style={{ display: proxyUrl ? "block" : "none" }}
                   onLoadedMetadata={(e) => { e.currentTarget.currentTime = cursorRef.current; }} />
            {!proxyUrl && <div className="empty">Render preview, then scrub or play the timeline — the video follows the audio.</div>}
          </div>

          {audioAsset
            ? <Timeline project={project} pxPerSec={pxPerSec} onZoom={setPxPerSec} cursor={cursor} onCursor={setCursor}
                        onPlaying={onPlaying} selectedBeatId={selectedBeat} onSelectBeat={selectBeat}
                        selectedCueId={selectedCue} onSelectCue={selectCue} hasProxy={!!proxyUrl} />
            : <div className="bottom" style={{ padding: 20 }}><span className="muted">Upload audio to build the timeline.</span></div>}
        </div>

        <div className={`sugcol${rightOpen ? " open" : ""}`}>
          {cueObj
            ? <SoundPanel project={project} cue={cueObj} busy={!!busy} onChanged={reload} />
            : beatObj
            ? <SuggestionPanel project={project} beat={beatObj} notes={notes} busy={!!busy}
                               onChanged={reload} cursor={cursor} playing={playing} />
            : <div className="sp-empty muted">Click a beat to see clip suggestions, or a Music/SFX cue to audition sound for that moment.</div>}
        </div>
      </div>
      {err && <div className="err" style={{ padding: "6px 16px" }}>{err}</div>}
    </div>
  );
}
