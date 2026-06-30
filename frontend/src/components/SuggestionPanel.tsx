import { useRef } from "react";
import { api } from "../lib/api";
import type { Project, Section } from "../lib/types";

export function SuggestionPanel({
  project, section, onChanged, busy,
}: {
  project: Project;
  section: Section;
  onChanged: (p?: Project) => void;
  busy: boolean;
}) {
  const fileRef = useRef<HTMLInputElement>(null);
  const sug = project.suggestions?.[section.id];
  const filledClip = project.tracks.find((t) => t.kind === "visual")
    ?.clips.find((c) => c.section_id === section.id);

  const find = async () => { await api.sourceSection(project.id, section.id); onChanged(); };

  const use = async (idx: number) => {
    const p = await api.acceptCandidate(project.id, section.id, idx);
    onChanged(p);
  };

  const uploadOwn = async (f: File) => {
    const asset = await api.uploadMedia(project.id, f);
    await api.placeClip(project.id, {
      track_id: project.tracks.find((t) => t.kind === "visual")!.id,
      asset_id: asset.id, timeline_start: section.start, timeline_end: section.end,
    });
    // tag it to the section so it shows as filled
    onChanged();
  };

  return (
    <div className="sugpanel">
      <div className="sp-head">
        <div className="sp-title">{section.topic_label || "Section"}</div>
        <div className="sp-time">{section.start.toFixed(1)}s – {section.end.toFixed(1)}s</div>
      </div>
      <div className="sp-transcript">“{section.text}”</div>
      {section.visual_brief && <div className="sp-brief">brief: {section.visual_brief}</div>}

      <div className="row" style={{ margin: "10px 0", gap: 8 }}>
        <button className="primary" onClick={find} disabled={busy || sug?.status === "sourcing"}>
          {sug?.candidates?.length ? "↻ Re-source" : "🔎 Find clips"}
        </button>
        <button onClick={() => fileRef.current?.click()} disabled={busy}>⬆ Use my own</button>
        <input ref={fileRef} type="file" accept="video/*,image/*" hidden
               onChange={(e) => e.target.files?.[0] && uploadOwn(e.target.files[0])} />
      </div>

      {sug?.status === "sourcing" && <div className="muted">sourcing… agents are finding clips</div>}
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
          No clips yet. Hit “Find clips” and agents will source b-roll for this line.
        </div>
      )}
    </div>
  );
}
