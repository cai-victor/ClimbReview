import { useState } from "react";
import { api, Job, percent } from "./api";

const STAGES: Record<string, string> = {
  queued: "Waiting to start", normalizing: "Making an upright copy for playback", extracting_pose: "Tracking the climber's body",
  computing_features: "Measuring movement", detecting_events: "Finding moments to review", generating_report: "Saving the review",
};

export function Progress({ job, title, onChange }: { job: Job; title: string; onChange: () => void }) {
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const { done, total } = job.progress;
  const fraction = total ? done / total : null;
  return (
    <section className="card" aria-live="polite" data-testid="progress">
      <h2>{title}</h2>
      <p>{STAGES[job.stage] ?? job.stage}{job.cancel_requested ? " (stopping…)" : ""}</p>
      {fraction !== null
        ? <><progress max={1} value={fraction} /><p className="muted small-text num">{percent(fraction)} · {done} of {total} frames</p></>
        : <progress aria-label="Working" />}
      <p className="muted small-text">You can leave this page. The work continues and the attempt shows its status in your list.</p>
      <button className="button" disabled={job.cancel_requested || busy} data-testid="cancel-job"
        onClick={() => { setBusy(true); (job.kind === "import" ? api.cancelImport(job.attempt_id) : api.cancelJob(job.id)).then(onChange).catch((e) => setError(e.message)).finally(() => setBusy(false)); }}>Cancel</button>
      {error && <p className="error" role="alert">{error}</p>}
    </section>
  );
}
