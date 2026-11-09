// Types mirror the FastAPI responses in backend/app/main.py.
export type JobStatus = "queued" | "running" | "complete" | "failed" | "cancelled" | "interrupted";
export interface Job {
  id: string; attempt_id: string; kind: "import" | "analysis"; status: JobStatus; stage: string;
  progress: { done: number; total: number | null }; cancel_requested: boolean; error: string | null;
  has_error_detail: boolean; attempt_bounds_ms: { start: number | null; end: number | null };
  config_hash: string | null; pipeline_version: string | null; detector_version: string | null;
  summary: { low_movement_fraction: number | null; event_count: number } | null;
  created_at: string; finished_at: string | null;
}
export interface Attempt {
  id: string; title: string; route_name: string; grade: string; outcome: string; focus: string;
  status: "importing" | "ready" | "failed"; error: string | null; width: number | null; height: number | null;
  duration_ms: number | null; attempt_start_ms: number | null; attempt_end_ms: number | null; created_at: string;
  original_filename: string; single_climber_confirmed: boolean; fixed_camera_confirmed: boolean;
  warnings: string[]; import_job: Job | null; analyses: Job[]; video_url: string | null;
}
export interface Review {
  detection_judgment: "unreviewed" | "confirmed" | "incorrect" | "cannot_tell";
  usefulness: "unrated" | "useful" | "not_useful"; context_tags: string[]; note: string;
}
export interface ClimbEvent {
  id: string; type: "low_movement" | "wrist_motion"; hand: "left" | "right" | null; start_ms: number; end_ms: number;
  truncated: boolean; evidence: Record<string, unknown>;
  tracking_quality: { label: string; median_min_required_visibility: number; is_calibrated_event_probability: boolean };
  feedback: { template_version: string; observation: string; interpretation: string; reflection_question: string };
  review: Review;
}
export interface Gap { start_ms: number; end_ms: number; duration_ms: number; reasons: Record<string, number> }
export interface DetectorCoverage {
  status: "available" | "insufficient_tracking"; reason: string | null; eligible_ms: number | null;
  fraction: number | null; attempt_ms: number; gaps: Gap[];
  per_landmark: Record<string, { valid_fraction: number | null; invalid_reasons: Record<string, number> }>;
}
export interface Result {
  attempt_bounds_ms: { start: number; end: number }; pipeline_version: string; config_hash: string;
  coverage: { detectors: Record<string, DetectorCoverage>; pose_detected_fraction: number | null;
    camera_motion_interval_fraction: number | null;
    attempt_scale: { status: string; L_px: number | null } };
  detection: { detector_version: string; detectors: Record<string, { status: string; reason: string | null; event_count: number | null }> };
  warnings: string[];
}
export interface Summary {
  attempt_duration_ms: number; low_movement_total_ms: number | null; low_movement_fraction_of_eligible: number | null;
  eligible: Record<string, { eligible_ms: number | null; fraction: number | null; status: string }>;
  wrist_episode_counts: { left: number | null; right: number | null };
  review_priority: { meaning: string; event_ids: string[] };
}
export interface OverlaySample { t: number; pose: boolean; joints: Record<string, [number, number]> }

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  if (!response.ok) {
    let message = `Request failed (${response.status}).`;
    try {
      const body = await response.json();
      if (typeof body.detail === "string") message = body.detail;
    } catch { /* keep the generic message */ }
    throw new Error(message);
  }
  return response.status === 204 ? (undefined as T) : response.json();
}
const jsonInit = (method: string, body: unknown): RequestInit => ({
  method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
});

export const api = {
  listAttempts: () => request<Attempt[]>("/api/attempts"),
  getAttempt: (id: string) => request<Attempt>(`/api/attempts/${id}`),
  patchAttempt: (id: string, body: Partial<Attempt>) => request<Attempt>(`/api/attempts/${id}`, jsonInit("PATCH", body)),
  deleteAttempt: (id: string) => request<void>(`/api/attempts/${id}`, { method: "DELETE" }),
  retryImport: (id: string) => request<Attempt>(`/api/attempts/${id}/retry-import`, { method: "POST" }),
  queueAnalysis: (id: string) => request<Job>(`/api/attempts/${id}/analyses`, { method: "POST" }),
  cancelJob: (id: string) => request<Job>(`/api/analyses/${id}/cancel`, { method: "POST" }),
  getAnalysis: (id: string) => request<Job & { result?: Result }>(`/api/analyses/${id}`),
  getPoses: (id: string) => request<{ samples: OverlaySample[] }>(`/api/analyses/${id}/poses`),
  getEvents: (id: string) => request<{ events: ClimbEvent[]; summary: Summary }>(`/api/analyses/${id}/events`),
  putReview: (runId: string, eventId: string, review: Review) =>
    request<Review>(`/api/analyses/${runId}/events/${eventId}/review`, jsonInit("PUT", review)),
  getReflection: (id: string) => request<{ observation: string; next_focus: string }>(`/api/attempts/${id}/reflection`),
  putReflection: (id: string, body: { observation: string; next_focus: string }) =>
    request<{ observation: string; next_focus: string }>(`/api/attempts/${id}/reflection`, jsonInit("PUT", body)),
  upload: (file: File, title: string, onProgress: (fraction: number) => void) =>
    new Promise<Attempt>((resolve, reject) => {
      const data = new FormData();
      data.append("file", file);
      data.append("title", title);
      const xhr = new XMLHttpRequest();
      xhr.open("POST", "/api/attempts");
      xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total);
      xhr.onload = () => {
        try {
          const body = JSON.parse(xhr.responseText);
          if (xhr.status === 201) resolve(body);
          else reject(new Error(typeof body.detail === "string" ? body.detail : "Upload failed."));
        } catch { reject(new Error("Upload failed.")); }
      };
      xhr.onerror = () => reject(new Error("Upload failed. Is the local server running?"));
      xhr.send(data);
    }),
};

export const clock = (ms: number | null | undefined): string => {
  if (ms == null) return "n/a";
  const total = ms / 1000;
  const minutes = Math.floor(total / 60);
  return `${String(minutes).padStart(2, "0")}:${(total - minutes * 60).toFixed(1).padStart(4, "0")}`;
};
export const percent = (value: number | null | undefined): string =>
  value == null ? "unavailable" : `${(value * 100).toFixed(1)}%`;
