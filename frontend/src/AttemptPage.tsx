import { useCallback, useEffect, useState } from "react";
import { api, Attempt, Job } from "./api";
import { Progress } from "./Progress";
import { Review } from "./Review";
import { Setup } from "./Setup";
import { Menu } from "./ui";

const when = (iso: string) => new Date(iso).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
const handsOnly = (job: Job) => job.detector_version === "detectors-v1";

export function AttemptPage({ id }: { id: string }) {
  const [attempt, setAttempt] = useState<Attempt | null>(null);
  const [error, setError] = useState("");
  const [showSetup, setShowSetup] = useState(false);
  const [chosenRun, setChosenRun] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try { setAttempt(await api.getAttempt(id)); setError(""); }
    catch (e) { setError((e as Error).message); }
  }, [id]);
  useEffect(() => { void load(); }, [load]);
  useEffect(() => { if (attempt?.status === "ready") window.localStorage.setItem("climbreview.lastAttempt", id); }, [attempt?.status, id]);

  const latest: Job | undefined = attempt?.analyses[0];
  const importing = attempt?.import_job && ["queued", "running"].includes(attempt.import_job.status);
  const analyzing = latest && ["queued", "running"].includes(latest.status);

  useEffect(() => {
    if (!importing && !analyzing) return;
    const timer = setInterval(() => void load(), 800);
    return () => clearInterval(timer);
  }, [importing, analyzing, load]);

  if (error && !attempt) return (
    <div className="page narrow">
      <section className="card empty"><strong>This attempt could not be opened</strong><span role="alert">{error}</span>
        <div className="row tight" style={{ justifyContent: "center" }}><button className="button" onClick={() => void load()}>Try again</button><a className="button primary" href="#/">All attempts</a></div></section>
    </div>
  );
  if (!attempt) return <div className="page"><p className="muted">Loading…</p></div>;

  const remove = async () => {
    if (!window.confirm("Delete this attempt, its video copies, analyses, and notes from this computer?")) return;
    try { await api.deleteAttempt(id); window.localStorage.removeItem("climbreview.lastAttempt"); window.location.hash = "#/"; }
    catch (e) { setError((e as Error).message); }
  };
  const retry = async () => {
    setBusy(true);
    try { await api.retryImport(id); await load(); } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };

  const completed = attempt.analyses.filter((job) => job.status === "complete");
  const shown = completed.find((job) => job.id === chosenRun) ?? completed[0];
  const reviewing = attempt.status === "ready" && attempt.kind !== "photo" && !importing && !analyzing && !showSetup && Boolean(shown);
  const stopped = latest && !["complete", "queued", "running"].includes(latest.status) ? latest : null;

  let body;
  if (importing && attempt.import_job) body = <Progress job={attempt.import_job} onChange={load} title="Preparing the video" />;
  else if (attempt.status === "failed") {
    body = (
      <section className="card" data-testid="import-failed">
        <h2>The video could not be prepared</h2>
        <p className="error" role="alert">{attempt.error}</p>
        <p className="muted small-text">Your upload is kept. Try once more, or delete this attempt and upload an MP4 or MOV exported from your phone's camera app.</p>
        <div className="row tight"><button className="button primary" disabled={busy} onClick={() => void retry()}>Retry import</button></div>
      </section>
    );
  } else if (attempt.kind === "photo") {
    body = (
      <section className="card" data-testid="photo-attempt">
        <h2>Photo of a climb</h2>
        <p className="muted">A photo has no movement to review. Mark the route's holds, then plan sequences to try using your height and wingspan.</p>
        <img className="photo-preview" src={`/api/attempts/${attempt.id}/frame?ms=0`} alt={`Photo: ${attempt.title}`} />
        <div className="row tight"><a className="button primary" href={`#/holds/${attempt.id}`}>Mark route holds</a><a className="button" data-testid="photo-plan" href={`#/plan/${attempt.id}`}>Plan a route</a></div>
      </section>
    );
  } else if (analyzing && latest) body = <Progress job={latest} onChange={load} title="Analyzing the attempt" />;
  else if (reviewing) {
    body = (
      <>
        {stopped && (
          <section className="card notice" role="status" data-testid="stopped-notice">
            <strong>Your newest analysis {stopped.status === "cancelled" ? "was cancelled" : "did not finish"}.</strong> {stopped.error ?? ""} You are looking at the last finished one.
            <div className="row tight"><button className="button small" onClick={() => setShowSetup(true)}>Analyze again</button></div>
          </section>
        )}
        <Review key={shown.id} attempt={attempt} run={shown} onReanalyze={() => { setChosenRun(null); setShowSetup(true); }} onAttemptChanged={() => void load()} />
      </>
    );
  } else {
    body = (
      <>
        {stopped && !shown && (
          <section className="card notice" role="alert">
            <strong>The analysis {stopped.status === "cancelled" ? "was cancelled" : "did not finish"}.</strong> {stopped.error ?? ""} Your video is kept. Check the start and end below and start it again.
          </section>
        )}
        {shown && <div><button className="button" data-testid="back-to-review" onClick={() => setShowSetup(false)}>← Back to the review</button></div>}
        <Setup attempt={attempt} onChanged={load} onStarted={() => { setShowSetup(false); void load(); }} />
      </>
    );
  }

  const ready = attempt.status === "ready";
  return (
    <div className="page">
      <a className="back" href="#/">← All attempts</a>
      <div className="attempt-head">
        <div className="titles">
          <h1>{attempt.title}</h1>
          {reviewing && (
            <div className="run-line">
              {completed.length > 1 ? (
                <label className="sr-only" htmlFor="run-picker">Analysis shown</label>
              ) : <span>Analyzed {when(shown.created_at)}{handsOnly(shown) ? " · hands only" : ""}</span>}
              {completed.length > 1 && (
                <>
                  <span>Analysis</span>
                  <select id="run-picker" data-testid="run-picker" value={shown.id} onChange={(e) => setChosenRun(e.target.value)}>
                    {completed.map((job, index) => (
                      <option key={job.id} value={job.id}>{when(job.created_at)}{index === 0 ? " · latest" : " · older"}{handsOnly(job) ? ", hands only" : ""}</option>
                    ))}
                  </select>
                  {shown.id !== completed[0].id && <span className="chip warn">Older analysis</span>}
                  <span title="Reanalyzing never changes an older analysis.">Each keeps its own notes.</span>
                </>
              )}
            </div>
          )}
        </div>
        <div className="actions">
          {ready && attempt.kind !== "photo" && <a className="button" href={`#/holds/${attempt.id}`}>Mark route holds</a>}
          <Menu label="More" testid="attempt-menu">
            {ready && <a href={`#/plan/${attempt.id}`}>Plan a route from marked holds</a>}
            {reviewing && <button onClick={() => { setChosenRun(null); setShowSetup(true); }}>Change start and end, reanalyze</button>}
            {reviewing && <>
              <div className="menu-sep" /><div className="menu-note">Download this analysis</div>
              <a href={`/api/analyses/${shown.id}/export?format=html`} download>Report to read or print (HTML)</a>
              <a href={`/api/analyses/${shown.id}/export?format=csv`} download>Moments as a spreadsheet (CSV)</a>
              <a href={`/api/analyses/${shown.id}/export?format=json`} download>Everything, for other tools (JSON)</a>
            </>}
            {ready && attempt.kind !== "photo" && <><div className="menu-sep" /><div className="menu-note">For evaluating the app</div><a href={`#/annotate/${attempt.id}`}>Label reference events</a></>}
            <div className="menu-sep" />
            <button className="danger" onClick={remove} disabled={Boolean(importing || analyzing)}>Delete attempt</button>
          </Menu>
        </div>
      </div>
      {error && <div className="banner" role="alert"><span>{error}</span><button className="button small" onClick={() => setError("")}>Dismiss</button></div>}
      {body}
    </div>
  );
}
