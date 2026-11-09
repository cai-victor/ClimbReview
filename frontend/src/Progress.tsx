import { useState } from "react";
import { api, Job, percent } from "./api";

const STAGES: Record<string, string> = {
  queued: "Waiting for the worker", normalizing: "Creating the upright playback copy", extracting_pose: "Extracting pose",
  computing_features: "Computing movement features", detecting_events: "Detecting events", generating_report: "Saving results",
};

export function Progress({ job, title, onChange }: { job: Job; title: string; onChange: () => void }) {
  const [error, setError] = useState("");
  const { done, total } = job.progress;
  const fraction = total ? done / total : null;
  return (
    <section className="card" aria-live="polite">
      <h2>{title}</h2>
      <p>{STAGES[job.stage] ?? job.stage}{job.cancel_requested ? " (cancelling…)" : ""}</p>
      {fraction !== null && (
        <>
          <progress max={1} value={fraction} />
          <p className="muted">{done} of {total} frames sampled ({percent(fraction)})</p>
        </>
      )}
      {job.kind === "analysis" && (
        <button className="button" disabled={job.cancel_requested}
          onClick={() => api.cancelJob(job.id).then(onChange).catch((e) => setError(e.message))}>Cancel</button>
      )}
      {error && <p className="error" role="alert">{error}</p>}
    </section>
  );
}
