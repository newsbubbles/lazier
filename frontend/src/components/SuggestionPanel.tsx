import { useRef, useState } from "react";
import { api } from "../lib/api";
import type { Beat, Project } from "../lib/types";

export function SuggestionPanel({
  project, beat, notes, onChanged, busy,
}: {
  project: Project;
  beat: Beat;
  notes: string;
  onChanged: (p?: Project) => void;
  busy: boolean;
}) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [url, setUrl] = useState("");
  const sug = project.suggestions?.[beat.id];
  const plan = sug?.plan;
  const section = project.sections.find((s) => s.id === beat.section_id);
  const filledClip = project.tracks.find((t) => t.kind === "visual")
    ?.clips.find((c) => c.beat_id === beat.id);

  const find = async () => { await api.sourceBeat(project.id, beat.id, notes); onChanged(); };
  const use = async (idx: number) => onChanged(await api.acceptCandidate(project.id, beat.id, idx));
  const capture = async () => {
    if (!url.trim()) return;
    await api.captureSite(project.id, beat.id, url.trim(), beat.text);
    setUrl(""); onChanged();
  };

  const uploadOwn = async (f: File) => {
    const asset = await api.uploadMedia(project.id, f);
    await api.placeClip(project.id, {
      track_id: project.tracks.find((t) => t.kind === "visual")!.id,
      asset_id: asset.id, timeline_start: beat.start, timeline_end: beat.end,
    });
    onChanged();
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

      <div className="row" style={{ margin: "10px 0", gap: 8 }}>
        <button className="primary" onClick={find} disabled={busy || sug?.status === "sourcing"}>
          {sug?.candidates?.length ? "↻ Re-source" : "🔎 Find clips"}
        </button>
        <button onClick={() => fileRef.current?.click()} disabled={busy}>⬆ Use my own</button>
        <input ref={fileRef} type="file" accept="video/*,image/*" hidden
               onChange={(e) => e.target.files?.[0] && uploadOwn(e.target.files[0])} />
      </div>

      <div className="capture-row">
        <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="paste a URL to scroll-capture a site…"
               onKeyDown={(e) => e.key === "Enter" && capture()} />
        <button onClick={capture} disabled={busy || !url.trim()}>🌐 Capture</button>
      </div>
      <div className="muted" style={{ fontSize: 11, marginBottom: 4 }}>
        records a scroll-through of the page, highlighting this moment's words. Agents also
        auto-offer a site when a moment cites a source.
      </div>

      {sug?.status === "sourcing" && <div className="muted">sourcing… agents are finding clips for this moment</div>}
      {sug?.status === "error" && <div className="err">{sug.error}</div>}

      <div className="cards">
        {sug?.candidates?.map((c, i) => {
          const isRec = i === sug.recommended_index;
          const isPlaced = filledClip?.asset_id === c.asset_id;
          return (
            <div key={c.asset_id} className={`cand ${isPlaced ? "placed" : ""}`}>
              <div className="cand-thumb">
                {c.thumb && <img src={api.fileUrl(project.id, c.thumb)} alt="" />}
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
