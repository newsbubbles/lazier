import type { Clip, MediaAsset, Project, ProjectSummary } from "./types";

async function j<T>(r: Response): Promise<T> {
  if (!r.ok) {
    let detail = r.statusText;
    try { detail = (await r.json()).detail ?? detail; } catch {}
    throw new Error(detail);
  }
  return r.json() as Promise<T>;
}

export const api = {
  health: () => fetch("/api/health").then(j<{ ok: boolean; whisper: string }>),

  listProjects: () => fetch("/api/projects").then(j<ProjectSummary[]>),

  getProject: (id: string) => fetch(`/api/projects/${id}`).then(j<Project>),

  createProject: (body: {
    name: string; aspect_ratio: string; fps: number;
    budget_cap: number; rights_posture: string;
  }) =>
    fetch("/api/projects", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(j<Project>),

  deleteProject: (id: string) =>
    fetch(`/api/projects/${id}`, { method: "DELETE" }).then(j),

  uploadAudio: (id: string, file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return fetch(`/api/projects/${id}/audio`, { method: "POST", body: fd }).then(j<Project>);
  },

  uploadMedia: (id: string, file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return fetch(`/api/projects/${id}/media`, { method: "POST", body: fd }).then(j<MediaAsset>);
  },

  transcribe: (id: string, merge: boolean) =>
    fetch(`/api/projects/${id}/transcribe?merge=${merge}`, { method: "POST" }).then(j),

  placeClip: (id: string, body: {
    track_id: string; asset_id: string;
    timeline_start: number; timeline_end?: number;
    source_in?: number; source_out?: number | null;
  }) =>
    fetch(`/api/projects/${id}/clips`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(j<Clip>),

  updateClip: (id: string, clipId: string, body: Record<string, unknown>) =>
    fetch(`/api/projects/${id}/clips/${clipId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(j<Clip>),

  deleteClip: (id: string, clipId: string) =>
    fetch(`/api/projects/${id}/clips/${clipId}`, { method: "DELETE" }).then(j),

  sourceBeat: (id: string, bid: string) =>
    fetch(`/api/projects/${id}/beats/${bid}/source`, { method: "POST" }).then(j),

  sourceAll: (id: string, sectionId?: string) =>
    fetch(`/api/projects/${id}/source-all${sectionId ? `?section_id=${sectionId}` : ""}`,
      { method: "POST" }).then(j<{ status: string; beats: number }>),

  captureSite: (id: string, bid: string, url: string, highlight?: string) =>
    fetch(`/api/projects/${id}/beats/${bid}/capture`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, highlight: highlight || null }),
    }).then(j),

  acceptCandidate: (id: string, bid: string, candidate_index: number) =>
    fetch(`/api/projects/${id}/beats/${bid}/accept`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ candidate_index }),
    }).then(j<Project>),

  renderProxy: (id: string) =>
    fetch(`/api/projects/${id}/render/proxy`, { method: "POST" }).then(j<{ url: string }>),

  renderExport: (id: string) =>
    fetch(`/api/projects/${id}/render/export`, { method: "POST" }).then(j<{ video: string; srt: string }>),

  fileUrl: (id: string, rel: string) => `/files/${id}/${rel}`,
};
