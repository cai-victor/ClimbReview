import { useCallback, useEffect, useRef, useState } from "react";
import { api, Attempt, clock, percent } from "./api";

const ACCEPT = "video/mp4,video/quicktime,image/jpeg,image/png,.mp4,.mov,.jpg,.jpeg,.png";
const LAST = "climbreview.lastAttempt";
const busyStatus = (a: Attempt) => a.status === "importing" || ["queued", "running"].includes(a.analyses[0]?.status ?? "");

/** What the user can do with this attempt right now, in a climber's words. */
export function attemptState(a: Attempt): { text: string; tone: "" | "accent" | "warn" | "bad"; action: string } {
  const run = a.analyses[0];
  if (a.status === "failed") return { text: "Couldn't prepare the video", tone: "bad", action: "See what happened" };
  if (a.status === "importing") return { text: "Preparing video…", tone: "accent", action: "View progress" };
  if (a.kind === "photo") return { text: "Wall photo", tone: "", action: "Plan a route" };
  if (!run) return { text: "Needs start and end", tone: "warn", action: "Set up" };
  if (run.status === "queued" || run.status === "running") return { text: "Analyzing…", tone: "accent", action: "View progress" };
  if (run.status === "complete") return { text: "Ready to review", tone: "", action: "Review" };
  return { text: a.analyses.some((j) => j.status === "complete") ? "Last analysis stopped" : "Analysis stopped", tone: "warn", action: "Try again" };
}
const thumbUrl = (a: Attempt) => `/api/attempts/${a.id}/frame?ms=${Math.round(((a.attempt_start_ms ?? 0) + (a.duration_ms ?? 0) * 0.35) / 100) * 100}`;
const dateText = (iso: string) => new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });

function Thumb({ attempt }: { attempt: Attempt }) {
  const [broken, setBroken] = useState(false);
  if (attempt.status !== "ready" || broken) return <span className="thumb empty" aria-hidden="true">{attempt.status === "importing" ? "…" : "no preview"}</span>;
  return <img className="thumb" src={attempt.kind === "photo" ? `/api/attempts/${attempt.id}/frame?ms=0` : thumbUrl(attempt)} alt="" loading="lazy" onError={() => setBroken(true)} />;
}

function Meta({ attempt }: { attempt: Attempt }) {
  const state = attemptState(attempt);
  const older = attempt.analyses[0]?.status === "complete" && attempt.analyses[0].detector_version === "detectors-v1";
  const label = attempt.problem_label || attempt.route_name;
  return (
    <span className="attempt-meta">
      <span className={`chip ${state.tone}`} data-testid="attempt-status">{state.text}</span>
      {older && <span className="chip outline" title="Analyzed before foot tracking was added. Reanalyze from the attempt to add it.">Hands only</span>}
      <span className="num">{[dateText(attempt.created_at), attempt.duration_ms && attempt.kind !== "photo" ? clock(attempt.duration_ms).slice(0, 5) : "",
        label ? `${label}${attempt.grade ? ` (${attempt.grade})` : ""}` : "", attempt.outcome].filter(Boolean).join(" · ")}</span>
    </span>
  );
}

export function Library() {
  const [attempts, setAttempts] = useState<Attempt[] | null>(null);
  const [error, setError] = useState("");
  const [title, setTitle] = useState("");
  const [uploading, setUploading] = useState<number | null>(null);
  const [over, setOver] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const [auto, setAuto] = useState(() => window.localStorage.getItem("climbreview.autoAnalyze") !== "off");

  const load = useCallback(() => api.listAttempts().then((list) => { setAttempts(list); return list; }).catch((e) => { setError(e.message); return null; }), []);
  useEffect(() => { void load(); }, [load]);
  // Jobs keep running after you leave an attempt, so the list follows them.
  const anyBusy = attempts?.some(busyStatus) ?? false;
  useEffect(() => {
    if (!anyBusy) return;
    const timer = setInterval(() => void load(), 2000);
    return () => clearInterval(timer);
  }, [anyBusy, load]);

  const upload = async (file: File | undefined) => {
    if (!file || uploading !== null) return;
    setError("");
    setUploading(0);
    try {
      const attempt = await api.upload(file, title, setUploading, auto);
      window.location.hash = `#/attempt/${attempt.id}`;
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setUploading(null);
      if (input.current) input.current.value = "";
    }
  };

  const lastId = window.localStorage.getItem(LAST);
  const resume = attempts?.find((a) => a.id === lastId && a.status === "ready" && a.analyses[0]?.status === "complete") ?? null;

  return (
    <div className="page">
      {resume && (
            <a className="card resume" href={`#/attempt/${resume.id}`} data-testid="resume">
              <Thumb attempt={resume} />
              <span><span className="label">Pick up where you left off</span><span className="attempt-title">{resume.title}</span><Meta attempt={resume} /></span>
              <span className="button primary">Review attempt</span>
            </a>
          )}
      <div className="home">
        <section className="new-attempt" aria-labelledby="new-heading">
          <div>
            <h1 id="new-heading">Review a new attempt</h1>
            <p className="muted">Add a video of one climb. ClimbReview finds the moments worth rewatching and what you could try next time.</p>
          </div>
          <div className={`drop ${over ? "over" : ""}`} onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
            onDrop={(e) => { e.preventDefault(); setOver(false); void upload(e.dataTransfer.files?.[0]); }}>
            <label className="button primary" aria-disabled={uploading !== null}>
              {uploading !== null ? "Uploading…" : "Choose a video"}
              <input ref={input} type="file" accept={ACCEPT} className="sr-only" data-testid="file-input" onChange={(e) => upload(e.target.files?.[0])} disabled={uploading !== null} />
            </label>
            <span className="small-text muted">MP4 or MOV, up to 5 minutes and 2.5 GB. Or drop a file here.</span>
            {uploading !== null && <div style={{ width: "100%" }} role="status"><progress max={1} value={uploading} aria-label="Upload progress" /><span className="small-text muted num">Uploading: {percent(uploading)}</span></div>}
          </div>
          {error && <div className="banner" role="alert"><span>{error} {title ? "Your title is kept. " : ""}Check the file and choose it again.</span></div>}
          <label>Name this attempt (optional)
            <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Blue problem, attempt 2" />
          </label>
          <div>
            <h2>Filming for a better review</h2>
            <ul className="tips">
              <li>Prop the phone up or use a tripod so the camera does not move.</li>
              <li>Keep your hands and feet in the frame for the whole climb.</li>
              <li>Film one climber at a time.</li>
            </ul>
          </div>
          <details>
            <summary>More options</summary>
            <label className="check"><input type="checkbox" checked={auto} data-testid="auto-analyze" onChange={(e) => { setAuto(e.target.checked); window.localStorage.setItem("climbreview.autoAnalyze", e.target.checked ? "on" : "off"); }} /> Analyze the whole video right after upload</label>
            <p className="small-text muted">Untick to choose where the attempt starts and ends first. To plan a route without a video, choose a JPG or PNG photo of the wall.</p>
          </details>
        </section>

        <section aria-labelledby="list-heading">
          <h2 id="list-heading">Your attempts{attempts?.length ? <span className="muted small-text num"> {attempts.length}</span> : null}</h2>
          {attempts === null && !error && <p className="muted">Loading…</p>}
          {attempts?.length === 0 && (
            <div className="card empty" data-testid="library-empty"><strong>No attempts yet</strong>Choose a video to get your first review. Analysis takes a minute or two for a short clip.</div>
          )}
          <ul className="attempt-list">
            {attempts?.map((a) => (
              <li key={a.id}>
                <a className="card attempt-row" href={`#/attempt/${a.id}`} data-testid="attempt-row">
                  <Thumb attempt={a} />
                  <span><span className="attempt-title">{a.title}</span><Meta attempt={a} /></span>
                  <span className="attempt-go" aria-hidden="true">{attemptState(a).action} →</span>
                </a>
              </li>
            ))}
          </ul>
        </section>
      </div>
    </div>
  );
}
