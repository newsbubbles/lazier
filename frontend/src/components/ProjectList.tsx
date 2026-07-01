import { useEffect, useState, type MouseEvent } from "react";
import { api } from "../lib/api";
import type { ProjectSummary } from "../lib/types";

export function ProjectList({ onOpen }: { onOpen: (id: string) => void }) {
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [name, setName] = useState("");
  const [aspect, setAspect] = useState("16:9");
  const [posture, setPosture] = useState("anything_goes");
  const [tone, setTone] = useState("");
  const [refDate, setRefDate] = useState("");
  const [err, setErr] = useState("");

  const refresh = () => api.listProjects().then(setProjects).catch((e) => setErr(e.message));
  useEffect(() => { refresh(); }, []);

  const create = async () => {
    setErr("");
    try {
      const p = await api.createProject({
        name: name || "untitled", aspect_ratio: aspect, fps: 30,
        budget_cap: 5, rights_posture: posture, tone, reference_date: refDate,
      });
      onOpen(p.id);
    } catch (e: any) { setErr(e.message); }
  };

  const remove = async (e: MouseEvent, id: string) => {
    e.stopPropagation();
    if (!confirm("Delete this project and all its media?")) return;
    await api.deleteProject(id);
    refresh();
  };

  return (
    <div className="wrap">
      <h2>lazier <span className="muted" style={{ fontSize: 13 }}>audio-driven video editor</span></h2>

      <div className="card">
        <h3>New project</h3>
        <div className="grid">
          <div className="field">
            <label>Name</label>
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="My video" />
          </div>
          <div className="field">
            <label>Aspect ratio</label>
            <select value={aspect} onChange={(e) => setAspect(e.target.value)}>
              <option value="16:9">16:9 landscape</option>
              <option value="9:16">9:16 vertical</option>
              <option value="1:1">1:1 square</option>
              <option value="4:5">4:5 portrait</option>
            </select>
          </div>
          <div className="field">
            <label>Rights posture</label>
            <select value={posture} onChange={(e) => setPosture(e.target.value)}>
              <option value="anything_goes">anything goes (label uncleared)</option>
              <option value="commercial_safe">commercial safe only</option>
            </select>
          </div>
          <div className="field">
            <label>Tone / style (optional — director's guide)</label>
            <input value={tone} onChange={(e) => setTone(e.target.value)}
                   placeholder="e.g. dry comedic essay, meme-heavy" />
          </div>
          <div className="field">
            <label>Reference date (optional — for news timing)</label>
            <input value={refDate} onChange={(e) => setRefDate(e.target.value)}
                   placeholder="YYYY-MM-DD or leave blank" />
          </div>
          <div className="field" style={{ justifyContent: "flex-end" }}>
            <button className="primary" onClick={create}>Create &amp; open</button>
          </div>
        </div>
        {err && <div className="err" style={{ marginTop: 8 }}>{err}</div>}
      </div>

      <h3>Projects</h3>
      <div className="projlist">
        {projects.length === 0 && <div className="muted">No projects yet.</div>}
        {projects.map((p) => (
          <div key={p.id} className="item" onClick={() => onOpen(p.id)}>
            <div style={{ flex: 1 }}>
              <div style={{ fontWeight: 600 }}>{p.name}</div>
              <div className="muted" style={{ fontSize: 12 }}>
                {p.aspect_ratio} · {p.has_audio ? `${p.duration.toFixed(1)}s` : "no audio"} · {p.section_count} sections
              </div>
            </div>
            <button className="danger" onClick={(e) => remove(e, p.id)}>Delete</button>
          </div>
        ))}
      </div>
    </div>
  );
}
