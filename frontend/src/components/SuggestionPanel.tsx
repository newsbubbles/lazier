import { useEffect, useRef, useState } from "react";
import { api } from "../lib/api";
import type { Beat, Candidate, Project } from "../lib/types";

export function SuggestionPanel({
  project, beat, notes, onChanged, busy, cursor, playing,
}: {
  project: Project;
  beat: Beat;
  notes: string;
  onChanged: (p?: Project) => void;
  busy: boolean;
  cursor: number;
  playing: boolean;
}) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [url, setUrl] = useState("");
  const [beatNote, setBeatNote] = useState("");   // per-beat guidance for Find clips
  const [zoom, setZoom] = useState(true);          // slow-zoom uploaded stills
  const [err, setErr] = useState("");
  const sug = project.suggestions?.[beat.id];
  const plan = sug?.plan;
  const section = project.sections.find((s) => s.id === beat.section_id);
  const filledClip = project.tracks.find((t) => t.kind === "visual")
    ?.clips.find((c) => c.beat_id === beat.id);

  const find = async () => {
    // global director notes + this beat's optional steer (merge, so global tone still applies)
    const guidance = [notes, beatNote.trim() && `This beat: ${beatNote.trim()}`]
      .filter(Boolean).join("\n\n");
    await api.sourceBeat(project.id, beat.id, guidance); onChanged();
  };
  const use = async (idx: number) => onChanged(await api.acceptCandidate(project.id, beat.id, idx));
  const capture = async () => {
    if (!url.trim()) return;
    await api.captureSite(project.id, beat.id, url.trim(), beat.text);
    setUrl(""); onChanged();
  };

  const uploadOwn = async (f: File) => {
    setErr("");
    const vt = project.tracks.find((t) => t.kind === "visual");
    if (!vt) { setErr("project has no visual track"); return; }
    try {
      const asset = await api.uploadMedia(project.id, f);
      await api.placeClip(project.id, {
        track_id: vt.id, asset_id: asset.id,
        timeline_start: beat.start, timeline_end: beat.end,
        beat_id: beat.id, section_id: beat.section_id,   // link to the beat so it shows
        ken_burns: zoom,                                  // backend applies it only to stills
      });
      onChanged();
    } catch (e: any) { setErr(e.message); }
  };

  return (
    <div className="sugpanel">
      {section && <div className="sp-chapter">{section.topic_label}</div>}
      <div className="sp-head">
        <div className="sp-title">this moment</div>
        <div className="sp-time">{beat.start.toFixed(1)}s – {beat.end.toFixed(1)}s</div>
      </div>
      <div className="sp-transcript">“{beat.text}”</div>
      {plan && (
        <div className="sp-plan">
          <span className="pill reg">{plan.visual_register}</span>
          <span className="pill">{plan.content_type}</span>
          {plan.time_window && <span className="pill">{plan.time_window}</span>}
          <div className="sp-shot">🎬 {plan.shot_brief}</div>
        </div>
      )}
      {!plan && section?.visual_brief && <div className="sp-brief">chapter theme: {section.visual_brief}</div>}

      <input value={beatNote} onChange={(e) => setBeatNote(e.target.value)}
             style={{ width: "100%", fontSize: 12, marginTop: 10 }}
             placeholder="guidance for this beat (optional): steer the finder for this moment…" />
      <div className="row" style={{ margin: "8px 0 4px", gap: 8 }}>
        <button className="primary" onClick={find} disabled={busy || sug?.status === "sourcing"}>
          {sug?.candidates?.length ? "↻ Re-source" : "🔎 Find clips"}
        </button>
        <button onClick={() => fileRef.current?.click()} disabled={busy}>⬆ Use my own</button>
        <input ref={fileRef} type="file" accept="video/*,image/*" hidden
               onChange={(e) => e.target.files?.[0] && uploadOwn(e.target.files[0])} />
      </div>
      <label className="muted" style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11, marginBottom: 8 }}>
        <input type="checkbox" checked={zoom} onChange={(e) => setZoom(e.target.checked)} style={{ width: "auto" }} />
        effects on images (slow zoom)
      </label>

      <div className="capture-row">
        <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="paste a YouTube / video / image / site URL…"
               onKeyDown={(e) => e.key === "Enter" && capture()} />
        <button onClick={capture} disabled={busy || !url.trim()}>➕ Add</button>
      </div>
      <div className="muted" style={{ fontSize: 11, marginBottom: 4 }}>
        A YouTube or direct video link is clipped at its timestamp (add <code>?t=</code>); an
        image link drops in with effects; any other page is scroll-captured. No search used.
        Added clips stack as candidates; nothing you placed is lost.
      </div>
      {err && <div className="err" style={{ fontSize: 11, marginBottom: 4 }}>{err}</div>}

      {sug?.status === "sourcing" && <div className="muted">sourcing… agents are finding clips for this moment</div>}
      {sug?.status === "error" && <div className="err">{sug.error}</div>}

      <div className="cards">
        {sug?.candidates?.map((c, i) => {
          const isRec = i === sug.recommended_index;
          const isPlaced = filledClip?.asset_id === c.asset_id;
          return (
            <div key={c.asset_id} className={`cand ${isPlaced ? "placed" : ""}`}>
              <div className="cand-thumb">
                <CandidateThumb project={project} c={c} beat={beat} cursor={cursor} playing={playing} />
                <span className="fit">{Math.round(c.fit_score * 100)}%</span>
                {isRec && <span className="rec">recommended</span>}
              </div>
              <div className="cand-body">
                <div className="cand-title">{c.title}</div>
                <div className="cand-meta">
                  <span className="pill">{c.source}</span>
                  {c.quarantined && <span className="pill warn">uncleared</span>}
                  {c.flags.map((f) => <span key={f} className="pill flag">{f}</span>)}
                </div>
                <div className="cand-why">{c.rationale}</div>
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
          No clips yet. Hit “Find clips” and agents will source b-roll for this exact moment.
        </div>
      )}
    </div>
  );
}

// A candidate's preview: static thumbnail when the playhead is elsewhere, but a LIVE video
// synced to the timeline cursor's position within this beat while the playhead is inside it —
// so every option animates in lockstep with the timeline (same trick as the main viewport).
function CandidateThumb({ project, c, beat, cursor, playing }: {
  project: Project; c: Candidate; beat: Beat; cursor: number; playing: boolean;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [previewing, setPreviewing] = useState(false);   // tapped to play once
  const asset = project.assets[c.asset_id];
  const isVideo = !!asset && asset.kind === "video" && !!asset.local_path;
  const inBeat = cursor >= beat.start && cursor <= beat.end;
  const showVideo = isVideo && (inBeat || previewing);

  // cursor sync (only when the playhead is in the beat AND we're not doing a tap-preview)
  useEffect(() => {
    const v = videoRef.current;
    if (!v || !isVideo || previewing) return;
    if (!inBeat) { v.pause(); return; }
    const dur = asset!.duration || 0;
    let t = cursor - beat.start;               // seconds into the beat = seconds into the clip
    if (dur > 0) t = Math.min(t, dur - 0.05);  // clamp: clip may be shorter than the beat
    t = Math.max(0, t);
    const tol = playing ? 0.3 : 0.05;          // don't fight playback; snap when scrubbing
    if (Math.abs(v.currentTime - t) > tol) v.currentTime = t;
    if (playing) v.play().catch(() => {}); else v.pause();
  }, [cursor, playing, inBeat, isVideo, previewing, beat.start, asset?.duration]);

  // tap the preview: play this clip once from the start (mobile can't reach the transport)
  const playOnce = () => {
    const v = videoRef.current;
    if (!v) return;
    setPreviewing(true);
    v.currentTime = 0;
    v.play().catch(() => {});
  };

  if (isVideo) {
    return (
      <>
        {!showVideo && c.thumb && <img src={api.fileUrl(project.id, c.thumb)} alt="" onClick={playOnce} />}
        <video ref={videoRef} src={api.fileUrl(project.id, asset!.local_path)}
               muted playsInline preload="auto" onClick={playOnce}
               onEnded={() => setPreviewing(false)}
               style={{ display: showVideo ? "block" : "none", cursor: "pointer" }} />
      </>
    );
  }
  return c.thumb ? <img src={api.fileUrl(project.id, c.thumb)} alt="" /> : null;
}
