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
  kind: "video" | "photo";
  id: string; title: string; route_name: string; grade: string; outcome: string; focus: string; problem_label: string; climber_label: string;
  status: "importing" | "ready" | "failed"; error: string | null; width: number | null; height: number | null;
  duration_ms: number | null; attempt_start_ms: number | null; attempt_end_ms: number | null; created_at: string;
  original_filename: string; single_climber_confirmed: boolean; fixed_camera_confirmed: boolean;
  warnings: string[]; import_job: Job | null; analyses: Job[]; video_url: string | null;
}
export interface Review {
  detection_judgment: "unreviewed" | "confirmed" | "incorrect" | "cannot_tell";
  usefulness: "unrated" | "useful" | "not_useful"; context_tags: string[]; note: string;
}
export type Limb = "left_wrist" | "right_wrist" | "left_foot" | "right_foot";
export interface EventContext {
  method: string; limbs: Partial<Record<Limb, { state: "moved" | "quiet" | "drifted" | "unknown"; unknown_reason: string | null; observed_fraction: number; max_excursion_L: number | null; overlapping: { event_id: string; start_ms: number; end_ms: number }[] }>>;
  previous: { limb: Limb; event_id: string; gap_ms: number; truncated: boolean } | null; next: { limb: Limb; event_id: string; gap_ms: number; truncated: boolean } | null;
}
export interface ClimbEvent {
  id: string; type: "low_movement" | "wrist_motion" | "foot_motion"; hand: "left" | "right" | null; start_ms: number; end_ms: number;
  truncated: boolean; evidence: Record<string, unknown>; context?: EventContext;
  tracking_quality: { label: string; median_min_required_visibility: number; is_calibrated_event_probability: boolean };
  feedback: { template_version: string; observation: string; context?: string; interpretation: string; reflection_question: string };
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
  foot_analysis_available?: boolean; foot_episode_counts?: { left: number | null; right: number | null }; digest?: Digest | null;
  review_priority: { meaning: string; event_ids: string[] };
}
export interface Digest {
  limbs: Record<Limb, { label: string; episodes: number | null; uncertain_episodes: number; analyzable_fraction: number | null; moving_ms: number | null; largest: { event_id: string; start_ms: number; text: string } | null }>;
  phases: { start_ms: number; end_ms: number; event_ids: string[]; text: string }[];
  repeated: { limb: Limb; start_ms: number; end_ms: number; count: number; event_ids: string[]; text: string }[];
  rewatch: { event_id: string; start_ms: number; reason: string }[];
  limits: { limb: Limb; fraction: number | null; text: string }[];
  prompts: string[]; meaning: string;
}
export interface LimbSeries { detector: string; anchor: string; x: (number | null)[]; y: (number | null)[]; speed_L_per_s: (number | null)[]; run: (number | null)[] }
export type Movement = { available: false } | { available: true; width: number; height: number; L_px: number | null; t: number[]; limbs: Record<Limb, LimbSeries> };
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
  cancelImport: (id: string) => request<Attempt>(`/api/attempts/${id}/cancel-import`, { method: "POST" }),
  retryImport: (id: string) => request<Attempt>(`/api/attempts/${id}/retry-import`, { method: "POST" }),
  queueAnalysis: (id: string) => request<Job>(`/api/attempts/${id}/analyses`, { method: "POST" }),
  cancelJob: (id: string) => request<Job>(`/api/analyses/${id}/cancel`, { method: "POST" }),
  getAnalysis: (id: string) => request<Job & { result?: Result }>(`/api/analyses/${id}`),
  getPoses: (id: string) => request<{ samples: OverlaySample[] }>(`/api/analyses/${id}/poses`),
  getMovement: (id: string) => request<Movement>(`/api/analyses/${id}/movement`),
  getEvents: (id: string) => request<{ events: ClimbEvent[]; summary: Summary }>(`/api/analyses/${id}/events`),
  putReview: (runId: string, eventId: string, review: Review) =>
    request<Review>(`/api/analyses/${runId}/events/${eventId}/review`, jsonInit("PUT", review)),
  getReflection: (id: string) => request<{ observation: string; next_focus: string }>(`/api/attempts/${id}/reflection`),
  putReflection: (id: string, body: { observation: string; next_focus: string }) =>
    request<{ observation: string; next_focus: string }>(`/api/attempts/${id}/reflection`, jsonInit("PUT", body)),
  upload: (file: File, title: string, onProgress: (fraction: number) => void, autoAnalyze = false) =>
    new Promise<Attempt>((resolve, reject) => {
      const data = new FormData();
      data.append("file", file);
      data.append("title", title);
      data.append("auto_analyze", autoAnalyze ? "true" : "false");
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

export type IntervalType = "low_movement" | "wrist_motion" | "foot_motion" | "unscorable";
export interface AnnotationInterval {
  id: string; event_type: IntervalType; hand: "left" | "right" | null; start_ms: number; end_ms: number; applies_to: string[]; notes: string;
}
export interface AnnotationSet {
  id: string; attempt_id: string; rater_alias: string; clip_id: string; climber_id: string; route_id: string; split: string;
  synthetic_test_fixture: boolean; kind: string; intervals: AnnotationInterval[];
}
export interface AnnotationSetSummary { id: string; rater_alias: string; synthetic_test_fixture: boolean; interval_count: number; updated_at: string }
export type IntervalBody = Omit<AnnotationInterval, "id">;

export const annotationApi = {
  listSets: (attemptId: string) => request<AnnotationSetSummary[]>(`/api/attempts/${attemptId}/annotation-sets`),
  createSet: (attemptId: string, body: Record<string, unknown>) =>
    request<AnnotationSet>(`/api/attempts/${attemptId}/annotation-sets`, jsonInit("POST", body)),
  getSet: (id: string) => request<AnnotationSet>(`/api/annotation-sets/${id}`),
  deleteSet: (id: string) => request<void>(`/api/annotation-sets/${id}`, { method: "DELETE" }),
  addInterval: (id: string, body: IntervalBody) => request<AnnotationSet>(`/api/annotation-sets/${id}/intervals`, jsonInit("POST", body)),
  editInterval: (id: string, intervalId: string, body: IntervalBody) =>
    request<AnnotationSet>(`/api/annotation-sets/${id}/intervals/${intervalId}`, jsonInit("PUT", body)),
  deleteInterval: (id: string, intervalId: string) =>
    request<AnnotationSet>(`/api/annotation-sets/${id}/intervals/${intervalId}`, { method: "DELETE" }),
};

export interface Hold { id: string; x: number; y: number; radius: number; route: string; hold_type: string; role: "" | "start" | "finish"; use: "" | "hand" | "foot" | "both"; pull?: "" | "down" | "left" | "right" | "up"; start_limb?: StartLimb }
export type StartLimb = "" | "left_hand" | "right_hand" | "both_hands" | "left_foot" | "right_foot";
export interface HoldMap {
  id: string; attempt_id: string; name: string; reference_frame_ms: number; width: number; height: number;
  holds: Hold[]; scope_note: string; frame_url: string; scale: MapScale | null;
}
export interface WallInfo { basis: string; frames_used: number; never_clear_fraction: number | null; detail: string; image_url: string; combined: boolean }
export interface MapScale { x1: number; y1: number; x2: number; y2: number; cm: number }
export interface HoldSuggestion { x: number; y: number; radius: number }
export interface SuggestionResult { suggestions: HoldSuggestion[]; seed_color: string; note: string; image: { basis: string; detail: string } }
export interface PlanResult extends BetaResult { body?: { torso_cm: number; arm_cm: number; leg_cm: number }; hold_map: (HoldMapSummary & { width: number; height: number }) | null }
export type HoldBody = Omit<Hold, "id">;
export const holdApi = {
  list: (attemptId: string) => request<HoldMap[]>(`/api/attempts/${attemptId}/hold-maps`),
  create: (attemptId: string, body: { name: string; reference_frame_ms: number }) =>
    request<HoldMap>(`/api/attempts/${attemptId}/hold-maps`, jsonInit("POST", body)),
  remove: (mapId: string) => request<void>(`/api/hold-maps/${mapId}`, { method: "DELETE" }),
  addHold: (mapId: string, body: HoldBody) => request<HoldMap>(`/api/hold-maps/${mapId}/holds`, jsonInit("POST", body)),
  editHold: (mapId: string, id: string, body: HoldBody) => request<HoldMap>(`/api/hold-maps/${mapId}/holds/${id}`, jsonInit("PUT", body)),
  suggest: (mapId: string, body: { x: number; y: number; tolerance: string }) => request<SuggestionResult>(`/api/hold-maps/${mapId}/suggestions`, jsonInit("POST", body)),
  putScale: (mapId: string, body: MapScale) => request<MapScale>(`/api/hold-maps/${mapId}/scale`, jsonInit("PUT", body)),
  get: (mapId: string) => request<HoldMap>(`/api/hold-maps/${mapId}`),
  fit: (mapId: string, body: { x: number; y: number; tolerance: string }) => request<{ x: number; y: number; radius: number; note: string }>(`/api/hold-maps/${mapId}/fit`, jsonInit("POST", body)),
  wallGeometry: (mapId: string) => request<WallGeometry>(`/api/hold-maps/${mapId}/wall-geometry`),
  wallInfo: (mapId: string) => request<WallInfo>(`/api/hold-maps/${mapId}/wall-info`),
  plan: (mapId: string, heightCm: number, wingspanCm: number, rectify = true) => request<PlanResult>(`/api/hold-maps/${mapId}/plan?height_cm=${heightCm}&wingspan_cm=${wingspanCm}&rectify=${rectify}`),
  removeHold: (mapId: string, id: string) => request<HoldMap>(`/api/hold-maps/${mapId}/holds/${id}`, { method: "DELETE" }),
};

export interface Feedback { decision: "unreviewed" | "will_try" | "intentional" | "disagree" | "cannot_tell"; trial_outcome: "not_tried" | "helped" | "no_change" | "worse" | "unclear"; note: string }
export interface CoachingOption { limb: string; hold_index: number; hold_id: string; step_L: number; margin_L: number | null; gain_L: number | null; x: number; y: number }
export interface CoachingCard {
  id: string; kind: string; title: string; start_ms: number; end_ms: number; status_label: string; limbs: string[]; moment: string; why: string; try_this: string; keep_if: string;
  measurements: { label: string; value: string; criterion: string }[]; uncertainty: string[]; sources: string[]; alternatives: CoachingOption[]; map_action: string | null;
  alternative_summary?: string; alternative_note?: string | null; observed_margin_L?: number; target: { limb: string; ms: number } | null; feedback: Feedback;
  scope?: "attempt"; moments?: number[]; highlight?: Highlight | null;
}
export type HighlightShape = { type: "ring" | "dot"; x: number; y: number; label: string } | { type: "area"; x: number; y: number; r: number; label: string }
  | { type: "arrow"; x1: number; y1: number; x2: number; y2: number; label: string };
/** What to look at on the video for one card: fixed marks measured at `at_ms`, and a one-line caption. */
export interface Highlight { at_ms: number; caption: string; shapes: HighlightShape[] }
export interface StoryStop { start_ms: number; end_ms: number; duration_ms: number; role: "start" | "middle" | "before_leaving"; height_L: number; spread_L: number; tracked_fraction: number; counts: Record<"left_foot" | "right_foot" | "left_wrist" | "right_wrist" | "uncertain", number> }
export type Story = { available: false; reason: string; note: string } | {
  available: true; note: string; headline: string; on_wall: { start_ms: number; end_ms: number; started_by: "start_of_clip" | "left_the_ground" | "lowered_into_start"; ended_by: "fast_descent" | "end_of_clip" };
  drop: { start_ms: number; end_ms: number; drop_L: number } | null;
  stats: { on_wall_ms: number; stopped_ms: number; moving_ms: number; stops: number; high_point_ms: number; height_gained_L: number; hips_tracked_fraction: number };
  phases: { kind: "moving" | "stopped" | "off_wall" | "before_start"; start_ms: number; end_ms: number }[]; stops: StoryStop[]; profile: { t: number; h: number; run: number }[];
};
export interface PlacementReview { status: "unreviewed" | "on_marked_hold" | "on_unmarked_hold" | "intentional_smear" | "not_placed" | "cannot_tell"; hold_id: string | null; note: string }
export interface Placement { id: string; limb: string; event_id: string; landing_ms: number; review_ms: number; x: number; y: number; anchor: string; proximity: string; settle_excursion_L: number; nearest_hold: { hold_index: number; hold_id: string; edge_L: number } | null; review: PlacementReview }
export interface HoldMapSummary { id: string; name: string; hold_count: number; reference_frame_ms: number; usable: boolean; message: string; frame_url: string; holds: Hold[]; alignment: { status: string; max_corner_motion_px: number | null; frames_measured: number; frames_checked: number } | null }
export interface Coaching {
  available: boolean; reason?: string; needs_reanalysis?: boolean; version: string; disclaimer: string; cards: CoachingCard[]; cards_omitted: number;
  not_flagged: { start_ms: number; text: string }[]; cannot_evaluate: { start_ms: number; text: string }[]; placements: Placement[]; hold_map: HoldMapSummary | null;
  plan: { chosen: { id: string; title: string; start_ms: number; try_this: string; trial_outcome: string }[]; suggested: { id: string; title: string; start_ms: number; try_this: string } | null } | null;
  sources: Record<string, { title: string; url: string }>;
  top_card_ids: string[]; story?: Story; cards_after_leaving_wall?: number; glance: Glance; observed_route: ObservedRoute | null; perspective: Perspective | null;
}
export interface BetaStep { limb: string; from_hold: number; to_hold: number; distance_L: number; margin_L: number; tight: boolean; match?: boolean; crossed?: boolean; high_foot?: boolean; strenuous?: boolean; big_shift?: boolean; on_volume?: boolean; to_point?: [number, number] | null }
/** Joint positions of the sketch figure for one placement, as fractions of the picture. */
export type BetaPose = Record<string, [number, number]>;
export interface BetaCandidate { id: string; profile: string; label: string; start: Record<string, number>; feet_start_off_wall: boolean; start_margin_L: number; steps: BetaStep[]; move_count: number; total_distance_L: number; largest_move_L: number; tightest_margin_L: number; tight_moves: number; high_foot_moves?: number; strenuous_moves?: number; big_shifts?: number; matches?: number; tops_out?: boolean; figures?: BetaPose[]; feedback: Feedback }
export interface Perspective {
  applied: boolean; reason?: string; detail?: string; bolts_used?: number; scale_change?: number; holds_on_fitted_face?: number; holds?: number; assumption?: string;
  tilt?: { status: string; angle_to_camera_deg?: number; top_toward_camera_deg?: number; turned_sideways_deg?: number; note?: string; reason?: string };
}
export interface WallGeometry { status: string; reason: string | null; grid_points: [number, number][]; summary: Perspective }
export interface BetaResult { perspective?: Perspective; status: "ready" | "setup_needed" | "no_candidate" | "no_map"; needs: string[]; candidates: BetaCandidate[]; hold_map: HoldMapSummary | null; assumptions?: string[]; note?: string; stuck?: { hands_reached: number[]; search_limit_reached: boolean } }
export interface ComparisonResult {
  status: "needs_labels" | "no_match" | "ready"; meaning: string;
  attempts: { id: string; title: string; outcome: string; is_current: boolean; metrics: { attempt_ms: number; foot_coverage: (number | null)[]; coverage_ok: boolean; foot_moves_per_analyzable_minute: number | null; reaches_evaluated: number; reaches_with_foot_setup: number | null } | null }[];
}
export interface ProposedHold { x: number; y: number; radius: number; role: "" | "start" | "finish"; use: "" | "hand" | "foot" | "both"; visited_by: string[] }
export interface RouteProposal { status: "proposed" | "not_possible"; reason?: string; holds: ProposedHold[]; notes: string[]; disclaimer?: string; seed_color: string; reference_frame_ms: number; wall: string; color_note: string }
export interface RouteWall { reference_frame_ms: number; width: number; height: number; detail: string; combined: boolean; image_url: string }
export interface RoleProposal { status: "proposed" | "not_possible"; reason?: string; notes: string[]; disclaimer?: string; holds: { id: string; current_role: string; current_use: string; role: Hold["role"]; use: Hold["use"]; visited_by: string[] }[] }
export interface Glance { attempt_ms: number; hand_moves: number; foot_moves: number; longest_gap_ms: number | null; longest_gap_at_ms: number | null; hand_tracked: (number | null)[]; foot_tracked: (number | null)[]; notes: string[] }
export interface ObservedRoute { visits: { limb: string; start_ms: number; end_ms: number; hold_index: number; anchor: string }[]; unvisited: number[]; note: string }
export const performanceApi = {
  routeWall: (runId: string) => request<RouteWall>(`/api/analyses/${runId}/route-wall`),
  routeProposal: (runId: string, body: { x: number; y: number; tolerance: string }) => request<RouteProposal>(`/api/analyses/${runId}/route-proposal`, jsonInit("POST", body)),
  roleProposal: (runId: string, mapId: string) => request<RoleProposal>(`/api/analyses/${runId}/hold-maps/${mapId}/role-proposal`),
  coaching: (runId: string) => request<Coaching>(`/api/analyses/${runId}/coaching`),
  putDecision: (runId: string, cueId: string, body: Feedback) => request<Feedback>(`/api/analyses/${runId}/coaching/${cueId}`, jsonInit("PUT", body)),
  putPlacement: (runId: string, id: string, body: PlacementReview) => request<PlacementReview>(`/api/analyses/${runId}/placements/${id}`, jsonInit("PUT", body)),
  checkAlignment: (runId: string, mapId: string) => request<unknown>(`/api/analyses/${runId}/hold-maps/${mapId}/alignment`, { method: "POST" }),
  candidateBeta: (runId: string) => request<BetaResult>(`/api/analyses/${runId}/candidate-beta`),
  comparison: (attemptId: string) => request<ComparisonResult>(`/api/attempts/${attemptId}/comparison`),
};

export const clock = (ms: number | null | undefined): string => {
  if (ms == null) return "n/a";
  const total = ms / 1000;
  const minutes = Math.floor(total / 60);
  return `${String(minutes).padStart(2, "0")}:${(total - minutes * 60).toFixed(1).padStart(4, "0")}`;
};
/** A duration in seconds, written tight against its unit: 52s, 4.5s. */
export const secs = (ms: number, digits = 0): string => `${(ms / 1000).toFixed(digits)}s`;
export const percent = (value: number | null | undefined): string =>
  value == null ? "unavailable" : `${(value * 100).toFixed(1)}%`;
