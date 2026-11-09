import { useCallback, useEffect, useRef, useState } from "react";
import { annotationApi, AnnotationInterval, AnnotationSet, AnnotationSetSummary, api, Attempt, clock, IntervalBody } from "./api";

// Blind reference labeling. This page must never request poses, events, or forecasts.
type Kind = "low_movement" | "wrist_left" | "wrist_right" | "unscorable";
const KIND_LABEL: Record<Kind, string> = {
  low_movement: "Low visible movement", wrist_left: "Left wrist movement", wrist_right: "Right wrist movement", unscorable: "Unscorable (cannot judge)",
};
const DETECTORS: [string, string][] = [["all", "All"], ["low_movement", "Low movement"], ["wrist_motion_left", "Left wrist"], ["wrist_motion_right", "Right wrist"]];
const EMPTY = { kind: "low_movement" as Kind, start: "", end: "", applies: [] as string[], notes: "" };
const seconds = (ms: number) => (ms / 1000).toFixed(2);

function kindOf(interval: AnnotationInterval): Kind {
  if (interval.event_type === "wrist_motion") return interval.hand === "left" ? "wrist_left" : "wrist_right";
  return interval.event_type;
}

export function Annotate({ attemptId }: { attemptId: string }) {
  const video = useRef<HTMLVideoElement>(null);
  const [attempt, setAttempt] = useState<Attempt | null>(null);
  const [sets, setSets] = useState<AnnotationSetSummary[]>([]);
  const [active, setActive] = useState<AnnotationSet | null>(null);
  const [form, setForm] = useState(EMPTY);
  const [editing, setEditing] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [loop, setLoop] = useState(false);
  const [meta, setMeta] = useState({ rater_alias: "", clip_id: "", climber_id: "", route_id: "", split: "", synthetic_test_fixture: false });

  const refreshSets = useCallback(() => annotationApi.listSets(attemptId).then(setSets).catch((e) => setError(e.message)), [attemptId]);
  useEffect(() => { api.getAttempt(attemptId).then(setAttempt).catch((e) => setError(e.message)); void refreshSets(); }, [attemptId, refreshSets]);

  const now = () => Math.round((video.current?.currentTime ?? 0) * 1000);
  const markStart = useCallback(() => setForm((f) => ({ ...f, start: seconds(now()) })), []);
  const markEnd = useCallback(() => setForm((f) => ({ ...f, end: seconds(now()) })), []);
  const step = useCallback((delta: number) => {
    const element = video.current;
    if (element) { element.pause(); element.currentTime = Math.max(0, element.currentTime + delta); }
  }, []);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement;
      if (["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName) || !active) return;
      if (event.key === "[") { event.preventDefault(); markStart(); }
      else if (event.key === "]") { event.preventDefault(); markEnd(); }
      else if (event.key === ",") { event.preventDefault(); step(-0.1); }
      else if (event.key === ".") { event.preventDefault(); step(0.1); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [active, markStart, markEnd, step]);

  useEffect(() => {
    const element = video.current;
    if (!element || !loop) return;
    const start = parseFloat(form.start), end = parseFloat(form.end);
    if (!(end > start)) return;
    const onTime = () => { if (!element.paused && element.currentTime >= end) element.currentTime = start; };
    element.addEventListener("timeupdate", onTime);
    return () => element.removeEventListener("timeupdate", onTime);
  }, [loop, form.start, form.end]);

  const open = async (id: string) => {
    setError("");
    try { setActive(await annotationApi.getSet(id)); setForm(EMPTY); setEditing(null); } catch (e) { setError((e as Error).message); }
  };
  const create = async () => {
    setError("");
    try { const created = await annotationApi.createSet(attemptId, meta); setActive(created); void refreshSets(); }
    catch (e) { setError((e as Error).message); }
  };
  const save = async () => {
    if (!active) return;
    setError("");
    const start_ms = Math.round(parseFloat(form.start) * 1000), end_ms = Math.round(parseFloat(form.end) * 1000);
    const body: IntervalBody = {
      event_type: form.kind.startsWith("wrist") ? "wrist_motion" : (form.kind as "low_movement" | "unscorable"),
      hand: form.kind === "wrist_left" ? "left" : form.kind === "wrist_right" ? "right" : null,
      start_ms, end_ms, applies_to: form.kind === "unscorable" ? form.applies : [], notes: form.notes,
    };
    try {
      setActive(editing ? await annotationApi.editInterval(active.id, editing, body) : await annotationApi.addInterval(active.id, body));
      setForm(EMPTY); setEditing(null); void refreshSets();
    } catch (e) { setError((e as Error).message); }
  };
  const edit = (interval: AnnotationInterval) => {
    setEditing(interval.id);
    setForm({ kind: kindOf(interval), start: seconds(interval.start_ms), end: seconds(interval.end_ms), applies: interval.applies_to, notes: interval.notes });
    if (video.current) video.current.currentTime = interval.start_ms / 1000;
  };
  const remove = async (id: string) => {
    if (!active) return;
    try { setActive(await annotationApi.deleteInterval(active.id, id)); void refreshSets(); } catch (e) { setError((e as Error).message); }
  };
  const toggleApply = (value: string) => setForm((f) => {
    if (value === "all") return { ...f, applies: f.applies.includes("all") ? [] : ["all"] };
    const without = f.applies.filter((v) => v !== "all" && v !== value);
    return { ...f, applies: f.applies.includes(value) ? without : [...without, value] };
  });

  if (!attempt) return <div className="page">{error ? <p className="error" role="alert">{error}</p> : <p className="muted">Loading…</p>}</div>;

  return (
    <div className="page">
      <div className="page-head">
        <a href={`#/attempt/${attemptId}`}>← Back</a>
        <h1>Reference labeling: {attempt.title}</h1>
      </div>
      <p className="blind-note" role="note">
        Blind mode: no skeletons, detected events, explanations, or forecasts are shown or loaded here. Your labels are user-authored reference data, kept separate for each rater.
        Open this page before looking at the analysis results.
      </p>
      {error && <p className="error" role="alert">{error}</p>}
      <div className="annotate">
        <section className="card">
          <video ref={video} src={attempt.video_url ?? undefined} controls playsInline preload="auto" data-testid="annotate-video" />
          <div className="row tight">
            <button className="button small" onClick={() => step(-0.1)}>−0.1 s</button>
            <button className="button small" onClick={() => step(0.1)}>+0.1 s</button>
            <button className="button small" onClick={markStart} disabled={!active}>Mark start</button>
            <button className="button small" onClick={markEnd} disabled={!active}>Mark end</button>
            <label className="check"><input type="checkbox" checked={loop} onChange={(e) => setLoop(e.target.checked)} /> Loop marked range</label>
          </div>
          <p className="muted small-text">Keys, outside text fields: <span className="kbd">[</span> mark start, <span className="kbd">]</span> mark end, <span className="kbd">,</span> and <span className="kbd">.</span> step 0.1 s. Times are canonical video seconds.</p>
          <details>
            <summary>Annotation guide</summary>
            <ul>
              <li><strong>Low visible movement:</strong> at least 2 s when both wrists, both ankles, and hips look approximately stationary. Mark what you see, not intent.</li>
              <li><strong>Wrist movement:</strong> the climber's own left or right wrist, from leaving relative stillness until returning to it, at least 0.3 s. Do not require a new hold.</li>
              <li><strong>Unscorable:</strong> a person cannot judge the event because the body is hidden or off screen. Do not use it because tracking might fail.</li>
            </ul>
            <p className="muted small-text">Full protocol: docs/ANNOTATION_GUIDE.md.</p>
          </details>
        </section>

        <section className="card">
          {!active ? (
            <>
              <h2>Choose your rater set</h2>
              {sets.length > 0 && (
                <ul className="interval-list">
                  {sets.map((set) => (
                    <li key={set.id}>
                      <span>{set.rater_alias} {set.synthetic_test_fixture && <em>(synthetic test)</em>}</span>
                      <button className="button small" onClick={() => open(set.id)} aria-label={`Open set ${set.rater_alias}`}>Open</button>
                    </li>
                  ))}
                </ul>
              )}
              <h3>Start a new set</h3>
              <label>Alias (not your name)<input data-testid="rater-alias" value={meta.rater_alias} onChange={(e) => setMeta({ ...meta, rater_alias: e.target.value })} /></label>
              <div className="grid2">
                <label>Clip ID<input value={meta.clip_id} onChange={(e) => setMeta({ ...meta, clip_id: e.target.value })} placeholder={attemptId.slice(0, 8)} /></label>
                <label>Climber ID<input value={meta.climber_id} onChange={(e) => setMeta({ ...meta, climber_id: e.target.value })} /></label>
                <label>Route ID<input value={meta.route_id} onChange={(e) => setMeta({ ...meta, route_id: e.target.value })} /></label>
                <label>Split
                  <select value={meta.split} onChange={(e) => setMeta({ ...meta, split: e.target.value })}>
                    <option value="">Not assigned</option><option value="dev">Development</option><option value="test">Test</option>
                  </select>
                </label>
              </div>
              <label className="check"><input type="checkbox" checked={meta.synthetic_test_fixture} data-testid="synthetic-flag" onChange={(e) => setMeta({ ...meta, synthetic_test_fixture: e.target.checked })} /> Synthetic test data (never counted as real labels)</label>
              <button className="button primary" onClick={create} data-testid="create-set">Start labeling</button>
            </>
          ) : (
            <>
              <h2>Set: {active.rater_alias} {active.synthetic_test_fixture && <em>(synthetic test)</em>}</h2>
              <div className="row">
                <label className="grow">Class
                  <select data-testid="interval-kind" value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value as Kind, applies: [] })}>
                    {(Object.keys(KIND_LABEL) as Kind[]).map((k) => <option key={k} value={k}>{KIND_LABEL[k]}</option>)}
                  </select>
                </label>
              </div>
              <div className="grid2">
                <label>Start (s)<input data-testid="interval-start" type="number" step="0.01" min="0" value={form.start} onChange={(e) => setForm({ ...form, start: e.target.value })} /></label>
                <label>End (s)<input data-testid="interval-end" type="number" step="0.01" min="0" value={form.end} onChange={(e) => setForm({ ...form, end: e.target.value })} /></label>
              </div>
              {form.kind === "unscorable" && (
                <fieldset><legend>Applies to</legend>
                  {DETECTORS.map(([value, label]) => (
                    <label className="choice" key={value}><input type="checkbox" checked={form.applies.includes(value)} onChange={() => toggleApply(value)} /> {label}</label>
                  ))}
                </fieldset>
              )}
              <label>Note (optional)<textarea value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} /></label>
              <div className="row tight">
                <button className="button primary" onClick={save} data-testid="save-interval">{editing ? "Save change" : "Add interval"}</button>
                {editing && <button className="button" onClick={() => { setEditing(null); setForm(EMPTY); }}>Cancel edit</button>}
                <button className="button" onClick={() => { setActive(null); void refreshSets(); }}>Switch rater</button>
              </div>
              <h3>Intervals ({active.intervals.length})</h3>
              {active.intervals.length === 0 && <p className="muted">No intervals yet.</p>}
              <ul className="interval-list" data-testid="interval-list">
                {active.intervals.map((interval) => (
                  <li key={interval.id} className={editing === interval.id ? "editing" : ""}>
                    <span>{clock(interval.start_ms)} to {clock(interval.end_ms)}: {KIND_LABEL[kindOf(interval)]}{interval.applies_to.length ? ` (${interval.applies_to.join(", ")})` : ""}</span>
                    <span className="row tight">
                      <button className="button small" onClick={() => edit(interval)} aria-label={`Edit interval at ${clock(interval.start_ms)}`}>Edit</button>
                      <button className="button small" onClick={() => remove(interval.id)} aria-label={`Delete interval at ${clock(interval.start_ms)}`}>Delete</button>
                    </span>
                  </li>
                ))}
              </ul>
              <h3>Export</h3>
              <div className="row tight">
                <a className="button small" href={`/api/annotation-sets/${active.id}/export?format=csv`} download>This set (CSV)</a>
                <a className="button small" href={`/api/annotation-sets/${active.id}/export?format=json`} download>This set (JSON)</a>
                <a className="button small" href={`/api/attempts/${attemptId}/annotations/export`} download>All real raters (CSV)</a>
              </div>
              <p className="muted small-text">CSV matches evaluation/annotations_template.csv and scripts/evaluate.py. No agreement statistics are computed here.</p>
            </>
          )}
        </section>
      </div>
    </div>
  );
}
