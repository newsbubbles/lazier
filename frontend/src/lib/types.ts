// Mirrors backend/lazier/models.py

export interface Word { text: string; start: number; end: number; }
export interface Transcript { language: string; duration: number; words: Word[]; }
export interface Segment { id: string; start: number; end: number; text: string; }
export interface Section {
  id: string; start: number; end: number; text: string;
  topic_label: string; visual_brief: string; segment_ids: string[];
}

export type AssetKind = "video" | "image" | "audio";

export interface MediaAsset {
  id: string; kind: AssetKind; origin: string; name: string;
  local_path: string; source_url: string; license: string;
  duration: number; width: number; height: number;
  verify_score: number | null; quarantined: boolean;
}

export interface Transforms { scale: number; x: number; y: number; ken_burns: boolean; }
export interface Effects { fade_in: number; fade_out: number; }

export interface Candidate {
  asset_id: string; source: string; title: string; rationale: string;
  fit_score: number; thumb: string; flags: string[]; quarantined: boolean;
}
export interface Suggestion {
  id: string; section_id: string;
  status: "sourcing" | "ready" | "error" | "empty";
  candidates: Candidate[]; recommended_index: number; error: string; queries: string[];
}

export interface Clip {
  id: string; track_id: string; asset_id: string; section_id: string | null;
  timeline_start: number; timeline_end: number;
  source_in: number; source_out: number | null;
  transforms: Transforms; effects: Effects; z_order: number;
}

export type TrackKind = "visual" | "audio" | "caption" | "overlay";
export interface Track {
  id: string; name: string; kind: TrackKind; clips: Clip[];
  gain: number; duck: boolean;
}

export interface Project {
  id: string; name: string; aspect_ratio: string;
  width: number; height: number; fps: number; created_at: number;
  audio_asset_id: string | null; budget_cap: number;
  rights_posture: string; media_pool_path: string | null;
  assets: Record<string, MediaAsset>;
  transcript: Transcript | null;
  segments: Segment[]; sections: Section[];
  suggestions: Record<string, Suggestion>;
  tracks: Track[];
}

export interface ProjectSummary {
  id: string; name: string; aspect_ratio: string; created_at: number;
  duration: number; has_audio: boolean; section_count: number;
}
