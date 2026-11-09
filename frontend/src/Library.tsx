import { useCallback, useEffect, useRef, useState } from "react";
import { api, Attempt, clock, percent } from "./api";

export function Library() {
  const [attempts, setAttempts] = useState<Attempt[] | null>(null);
  const [error, setError] = useState("");
  const [title, setTitle] = useState("");
  const [uploading, setUploading] = useState<number | null>(null);
  const input = useRef<HTMLInputElement>(null);

  const load = useCallback(() => api.listAttempts().then(setAttempts).catch((e) => setError(e.message)), []);
  useEffect(() => { void load(); }, [load]);

  const upload = async (file: File | undefined) => {
    if (!file) return;
    setError("");
    setUploading(0);
    try {
      const attempt = await api.upload(file, title, setUploading);
      window.location.hash = `#/attempt/${attempt.id}`;
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setUploading(null);
      if (input.current) input.current.value = "";
    }
  };

  return (
    <div className="page">
      <section className="card">
        <h1>Add an attempt</h1>
        <p className="muted">
          Use an MP4 or MOV up to 120 seconds and 250 MB, with one climber and a camera on a tripod. Keep hands and feet in frame.
        </p>
        <div className="row">
          <label className="grow">Title (optional)
            <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Blue problem, attempt 2" />
          </label>
          <label className="button primary">
            Choose video
            <input ref={input} type="file" accept="video/mp4,video/quicktime,.mp4,.mov" hidden
              data-testid="file-input" onChange={(e) => upload(e.target.files?.[0])} disabled={uploading !== null} />
          </label>
        </div>
        {uploading !== null && <p role="status">Uploading: {percent(uploading)}</p>}
        {error && <p className="error" role="alert">{error}</p>}
      </section>

      <section>
        <h2>Saved attempts</h2>
        {attempts === null && <p className="muted">Loading…</p>}
        {attempts?.length === 0 && <p className="muted">No attempts yet. Add one above to get started.</p>}
        <ul className="attempt-list">
          {attempts?.map((a) => {
            const run = a.analyses[0];
            return (
              <li key={a.id}>
                <a className="card attempt-row" href={`#/attempt/${a.id}`}>
                  <strong>{a.title}</strong>
                  <span className="muted">
                    {new Date(a.created_at).toLocaleDateString()} · {a.duration_ms ? clock(a.duration_ms) : "no video yet"}
                  </span>
                  <span className={`tag status-${a.status}`}>
                    {a.status === "ready" ? (run ? `analysis ${run.status}` : "ready to analyze") : a.status}
                  </span>
                  {run?.summary && (
                    <span className="muted">Low-movement tracking coverage: {percent(run.summary.low_movement_fraction)}</span>
                  )}
                </a>
              </li>
            );
          })}
        </ul>
      </section>
    </div>
  );
}
