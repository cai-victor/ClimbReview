import { useRef, useState } from "react";
import { api, Attempt, clock } from "./api";
import { OutcomeField } from "./Details";

export function Setup({ attempt, onChanged, onStarted }: { attempt: Attempt; onChanged: () => void; onStarted: () => void }) {
  const video = useRef<HTMLVideoElement>(null);
  const [start, setStart] = useState(attempt.attempt_start_ms ?? 0);
  const [end, setEnd] = useState(attempt.attempt_end_ms ?? attempt.duration_ms ?? 0);
  const [form, setForm] = useState({ route_name: attempt.route_name, grade: attempt.grade, outcome: attempt.outcome, focus: attempt.focus });
  const [single, setSingle] = useState(attempt.single_climber_confirmed);
  const [fixed, setFixed] = useState(attempt.fixed_camera_confirmed);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const here = () => Math.round((video.current?.currentTime ?? 0) * 1000);

  const start_analysis = async () => {
    setBusy(true); setError("");
    try {
      await api.patchAttempt(attempt.id, { ...form, attempt_start_ms: start, attempt_end_ms: end,
        single_climber_confirmed: single, fixed_camera_confirmed: fixed });
      await api.queueAnalysis(attempt.id);
      onStarted();
    } catch (e) { setError((e as Error).message); onChanged(); } finally { setBusy(false); }
  };
  const seconds = (value: number) => (value / 1000).toFixed(1);
  const parse = (text: string) => Math.max(0, Math.round(parseFloat(text || "0") * 1000));
  const valid = start < end && end <= (attempt.duration_ms ?? 0);

  return (
    <div className="setup">
      <section className="card">
        <video ref={video} src={attempt.video_url ?? undefined} controls playsInline className="preview" data-testid="preview" />
        <h2>Where does the attempt start and end?</h2>
        <p className="muted">Scrub to where you leave the ground and where you top out or come off. Leave out the walk-up. The video is {clock(attempt.duration_ms)} long.</p>
        <div className="row">
          <label>Start (s)<input type="number" step="0.1" min="0" value={seconds(start)} data-testid="start-input" onChange={(e) => setStart(parse(e.target.value))} /></label>
          <button className="button" onClick={() => setStart(here())}>Use current time</button>
          <label>End (s)<input type="number" step="0.1" min="0" value={seconds(end)} data-testid="end-input" onChange={(e) => setEnd(parse(e.target.value))} /></label>
          <button className="button" onClick={() => setEnd(here())}>Use current time</button>
        </div>
        {!valid && <p className="error" role="alert">The start must come before the end, and both must be inside the video.</p>}
      </section>
      <section className="card">
        <h2>About this attempt (optional)</h2>
        <div className="grid2">
          <label>Route<input value={form.route_name} onChange={(e) => setForm({ ...form, route_name: e.target.value })} /></label>
          <label>Grade<input value={form.grade} onChange={(e) => setForm({ ...form, grade: e.target.value })} /></label>
          <label>Your focus<input value={form.focus} onChange={(e) => setForm({ ...form, focus: e.target.value })} /></label>
        </div>
        <OutcomeField value={form.outcome} onChange={(outcome) => setForm({ ...form, outcome })} testid="setup-outcome" />
        <h2>About the recording</h2>
        <label className="check"><input type="checkbox" checked={single} onChange={(e) => setSingle(e.target.checked)} /> Only one climber is in the picture</label>
        <label className="check"><input type="checkbox" checked={fixed} onChange={(e) => setFixed(e.target.checked)} /> The camera stays still</label>
        {(!single || !fixed) && (
          <p className="notice-text">Results are less reliable without these. Parts where the camera appears to move are left out automatically.</p>
        )}
        {attempt.warnings.length > 0 && <ul className="warnings">{attempt.warnings.map((w) => <li key={w}>{w}</li>)}</ul>}
        <button className="button primary" disabled={busy || !valid} onClick={start_analysis} data-testid="start-analysis">{busy ? "Starting…" : "Analyze attempt"}</button>
        {error && <p className="error" role="alert">{error}</p>}
      </section>
    </div>
  );
}
