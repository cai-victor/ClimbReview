import { useCallback, useEffect, useState } from "react";
import { api, Attempt, Job } from "./api";
import { Progress } from "./Progress";
import { Review } from "./Review";
import { Setup } from "./Setup";

export function AttemptPage({ id }: { id: string }) {
  const [attempt, setAttempt] = useState<Attempt | null>(null);
  const [error, setError] = useState("");
  const [showSetup, setShowSetup] = useState(false);
  const [chosenRun, setChosenRun] = useState<string | null>(null);

  const load = useCallback(async () => {
    try { setAttempt(await api.getAttempt(id)); setError(""); }
    catch (e) { setError((e as Error).message); }
  }, [id]);
  useEffect(() => { void load(); }, [load]);

  const latest: Job | undefined = attempt?.analyses[0];
  const importing = attempt?.import_job && ["queued", "running"].includes(attempt.import_job.status);
  const analyzing = latest && ["queued", "running"].includes(latest.status);

  useEffect(() => {
    if (!importing && !analyzing) return;
    const timer = setInterval(() => void load(), 800);
    return () => clearInterval(timer);
  }, [importing, analyzing, load]);

  if (error && !attempt) return <div className="page"><p className="error" role="alert">{error}</p><a href="#/">Back to attempts</a></div>;
  if (!attempt) return <div className="page"><p className="muted">Loading…</p></div>;

  const remove = async () => {
    if (!window.confirm("Delete this attempt, its video copies, analyses, and notes from this computer?")) return;
    try { await api.deleteAttempt(id); window.location.hash = "#/"; }
    catch (e) { setError((e as Error).message); }
  };

  let body;
  if (importing && attempt.import_job) body = <Progress job={attempt.import_job} onChange={load} title="Preparing the video" />;
  else if (attempt.status === "failed") {
    body = (
      <section className="card">
        <h2>Video could not be prepared</h2>
        <p className="error" role="alert">{attempt.error}</p>
        <button className="button" onClick={() => api.retryImport(id).then(load).catch((e) => setError(e.message))}>Retry import</button>
      </section>
    );
  } else if (analyzing && latest) body = <Progress job={latest} onChange={load} title="Analyzing the attempt" />;
  else if (latest?.status === "complete" && !showSetup) {
    const completed = attempt.analyses.filter((job) => job.status === "complete");
    const shown = completed.find((job) => job.id === chosenRun) ?? latest;
    body = (
      <>
        {completed.length > 1 && (
          <section className="card run-picker">
            <label>Analysis shown
              <select data-testid="run-picker" value={shown.id} onChange={(e) => setChosenRun(e.target.value)}>
                {completed.map((job, index) => (
                  <option key={job.id} value={job.id}>
                    {new Date(job.created_at).toLocaleString()} · {job.detector_version ?? "unknown version"}{index === 0 ? " (latest)" : " (older, with its own notes)"}
                  </option>
                ))}
              </select>
            </label>
            <p className="muted small-text">Each analysis keeps its own event judgments and notes. Reanalyzing never changes an older one.</p>
          </section>
        )}
        <Review key={shown.id} attempt={attempt} run={shown} onReanalyze={() => { setChosenRun(null); setShowSetup(true); }} onAttemptChanged={() => void load()} />
      </>
    );
  } else {
    body = (
      <>
        {latest && latest.status !== "complete" && (
          <section className="card notice" role="alert">
            <strong>Last analysis {latest.status}.</strong> {latest.error ?? ""} The video is kept. You can start it again below.
          </section>
        )}
        <Setup attempt={attempt} onChanged={load} onStarted={() => { setShowSetup(false); void load(); }} />
      </>
    );
  }

  return (
    <div className="page">
      <div className="page-head">
        <a href="#/">← Attempts</a>
        <h1>{attempt.title}</h1>
        {attempt.status === "ready" && <a className="button" href={`#/annotate/${attempt.id}`}>Reference labeling</a>}
        {attempt.status === "ready" && <a className="button" href={`#/holds/${attempt.id}`}>Mark holds</a>}
        <button className="button danger" onClick={remove} disabled={Boolean(importing || analyzing)}>Delete</button>
      </div>
      {error && <p className="error" role="alert">{error}</p>}
      {body}
    </div>
  );
}
