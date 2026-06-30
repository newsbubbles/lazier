import { useCallbackRef } from "../lib/useCallbackRef";
import { useEffect, useRef, useState } from "react";
import { api } from "../lib/api";
import type { Project } from "../lib/types";
import { Timeline } from "./Timeline";
import { SuggestionPanel } from "./SuggestionPanel";

export function Editor({ projectId, onClose }: { projectId: string; onClose: () => void }) {
  const [project, setProject] = useState<Project | null>(null);
  const [cursor, setCursor] = useState(0);
  const [pxPerSec, setPxPerSec] = useState(90);
  const [log, setLog] = useState<string[]>([]);
  const [selectedBeat, setSelectedBeat] = useState<string | null>(null);
  const [proxyUrl, setProxyUrl] = useState<string | null>(null);
  const [busy, setBusy] = useState("");
  const [err, setErr] = useState("");

  const audioInput = useRef<HTMLInputElement>(null);
  const reload = useCallbackRef((p?: Project) =>
    p ? Promise.resolve(setProject(p))
      : api.getProject(projectId).then(setProject).catch((e) => setErr(e.message)));

  useEffect(() => { reload(); }, [projectId]);

  useEffect(() => {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/ws/${projectId}`);
    ws.onmessage = (ev) => {
      const m = JSON.parse(ev.data);
      let line = "";
      if (m.stage === "transcribe" && m.progress != null) line = `transcribe ${Math.round(m.progress * 100)}%`;
      else if (m.stage === "source" && m.msg) line = `· ${m.msg}`;
      else if (m.stage === "source_done") line = `✓ section sourced (${m.candidates} clips)`;
      else if (m.stage === "source_all_start") line = `sourcing ${m.count} sections…`;
      else if (m.stage === "source_all_done") line = `done sourcing all`;
      else if (m.stage === "error") line = `ERROR: ${m.error}`;
      else line = JSON.stringify(m);
      setLog((l) => [...l.slice(-80), line]);
      if (["done", "source_done", "source_all_done", "error"].includes(m.stage)) reload();
      if (["done", "source_all_done"].includes(m.stage)) setBusy("");
    };
    return () => ws.close();
  }, [projectId]);

  if (!project) return <div className="wrap"><p className="muted">Loading…</p></div>;

  const audioAsset = project.audio_asset_id ? project.assets[project.audio_asset_id] : null;
  const beatObj = project.beats.find((b) => b.id === selectedBeat) || null;
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
  const sourceAll = async () => {
    setErr(""); setBusy("auto-sourcing");
    try { await api.sourceAll(projectId); } catch (e: any) { setErr(e.message); setBusy(""); }
  };
  const doProxy = async () => {
    setErr(""); setBusy("rendering preview");
    try { const { url } = await api.renderProxy(projectId); setProxyUrl(url + `?t=${Date.now()}`); }
    catch (e: any) { setErr(e.message); }
    setBusy("");
  };
  const doExport = async () => {
    setErr(""); setBusy("exporting");
    try { const r = await api.renderExport(projectId); window.open(r.video, "_blank"); }
    catch (e: any) { setErr(e.message); }
    setBusy("");
  };

  return (
    <div className="editor">
      <div className="topbar">
        <span className="brand">laz<span>ier</span></span>
        <button onClick={onClose}>← Projects</button>
        <span className="muted">{project.name}</span>
        <span className="pill">{project.aspect_ratio}</span>
        <span className="pill">{project.rights_posture}</span>
        <div className="spacer" />
        {busy && <span className="muted">{busy}…</span>}
      </div>

      <div className="editor-main">
        <div className="side">
          <h3>Audio spine</h3>
          {!audioAsset ? (
            <>
              <button className="primary" onClick={() => audioInput.current?.click()}>Upload audio</button>
              <input ref={audioInput} type="file" accept="audio/*,video/*" hidden
                     onChange={(e) => e.target.files?.[0] && onAudio(e.target.files[0])} />
            </>
          ) : <div className="muted" style={{ fontSize: 12 }}>{audioAsset.name} · {audioAsset.duration.toFixed(1)}s</div>}

          {audioAsset && (
            <button style={{ marginTop: 8 }} onClick={transcribe} disabled={!!busy}>
              {project.sections.length ? "Re-transcribe" : "Transcribe → segment"}
            </button>
          )}

          {project.sections.length > 0 && (
            <>
              <h3>Auto-assemble</h3>
              <button className="primary" onClick={sourceAll} disabled={!!busy} style={{ width: "100%" }}>
                ✨ Auto-source all beats
              </button>
              <div className="muted" style={{ fontSize: 12, marginTop: 6 }}>
                {sourcedCount}/{project.beats.length} beats have a clip. Agents find b-roll
                reactive to each moment; click any beat to review or swap.
              </div>
            </>
          )}

          <h3>Agent activity</h3>
          <div className="log">{log.length === 0 ? "idle" : log.map((l, i) => <div key={i}>{l}</div>)}</div>
        </div>

        <div className="stage">
          <div className="toolbar">
            <button onClick={doProxy} disabled={!audioAsset || !!busy}>Render preview</button>
            <button className="primary" onClick={doExport} disabled={!audioAsset || !!busy}>Export</button>
            <div className="spacer" />
            <span className="muted">{project.sections.length} sections</span>
          </div>

          <div className="viewport">
            {proxyUrl ? <video src={proxyUrl} controls />
              : <div className="empty">Render preview to see the cut. (Live proxy-sync is M3.)</div>}
          </div>

          {audioAsset
            ? <Timeline project={project} pxPerSec={pxPerSec} onZoom={setPxPerSec} cursor={cursor} onCursor={setCursor}
                        selectedBeatId={selectedBeat} onSelectBeat={setSelectedBeat} />
            : <div className="bottom" style={{ padding: 20 }}><span className="muted">Upload audio to build the timeline.</span></div>}
        </div>

        <div className="sugcol">
          {beatObj
            ? <SuggestionPanel project={project} beat={beatObj} busy={!!busy} onChanged={reload} />
            : <div className="sp-empty muted">Click a beat on the timeline to see clip suggestions for that moment, or hit Auto-source all beats.</div>}
        </div>
      </div>
      {err && <div className="err" style={{ padding: "6px 16px" }}>{err}</div>}
    </div>
  );
}
