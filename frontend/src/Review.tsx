import { useEffect, useMemo, useRef, useState } from "react";
import { api, Attempt, ClimbEvent, clock, DetectorCoverage, Gap, Job, Limb, Movement, OverlaySample, percent, Result, Summary } from "./api";
import { DigestPanel } from "./DigestPanel";
import { EventCard, eventTitle } from "./EventCard";
import { isUncertain, limbOf, MovementChart } from "./MovementChart";
import { Focus, Player, PlayerHandle, Trail } from "./Player";

const CONTEXT_MS = 1000;
const REASONS: Record<string, string> = {
  no_pose: "no body was detected", non_finite: "the model returned no usable coordinate", out_of_frame: "the joint was outside the picture",
  visibility_missing: "the model gave no visibility value", low_visibility: "the joint was probably hidden or poorly seen",
  low_presence: "the model was unsure a joint was there", implausible_torso_scale: "the detected body shape was implausibly sized",
  camera_motion: "the camera appeared to move", repeated_source_frame: "the video repeated a frame, so no new movement was observed",
};

interface Track { key: string; label: string; events: ClimbEvent[]; detector: string }
type RowKey = "low" | Limb;
const ROWS: { key: RowKey; label: string; detector: string }[] = [
  { key: "left_foot", label: "Left foot", detector: "foot_motion_left" }, { key: "right_foot", label: "Right foot", detector: "foot_motion_right" },
  { key: "left_wrist", label: "Left wrist", detector: "wrist_motion_left" }, { key: "right_wrist", label: "Right wrist", detector: "wrist_motion_right" },
  { key: "low", label: "Low movement", detector: "low_movement" },
];
const FEET: RowKey[] = ["left_foot", "right_foot"], HANDS: RowKey[] = ["left_wrist", "right_wrist"], ALL: RowKey[] = ROWS.map((r) => r.key);
const rowOf = (event: ClimbEvent): RowKey => limbOf(event) ?? "low";

export function Review({ attempt, run, onReanalyze }: { attempt: Attempt; run: Job; onReanalyze: () => void }) {
  const [result, setResult] = useState<Result | null>(null);
  const [events, setEvents] = useState<ClimbEvent[]>([]);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [samples, setSamples] = useState<OverlaySample[]>([]);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [looping, setLooping] = useState(false);
  const [skeleton, setSkeleton] = useState(true);
  const [time, setTime] = useState(0);
  const [gapInfo, setGapInfo] = useState<{ gap: Gap; detector: string } | null>(null);
  const [movement, setMovement] = useState<Movement>({ available: false });
  const [shown, setShown] = useState<RowKey[]>(ALL);
  const [hideUncertain, setHideUncertain] = useState(false);
  const [focus, setFocus] = useState<Focus>("all");
  const player = useRef<PlayerHandle>(null);

  useEffect(() => {
    Promise.all([api.getAnalysis(run.id), api.getEvents(run.id), api.getPoses(run.id), api.getMovement(run.id)])
      .then(([analysis, eventData, poses, series]) => {
        setResult(analysis.result ?? null); setEvents(eventData.events); setSummary(eventData.summary); setSamples(poses.samples); setMovement(series);
      }).catch((e) => setError(e.message));
  }, [run.id]);

  const bounds = result?.attempt_bounds_ms;
  const span = bounds ? bounds.end - bounds.start : 1;
  const percentOf = (ms: number) => bounds ? ((ms - bounds.start) / span) * 100 : 0;
  const selectedEvent = events.find((e) => e.id === selected) ?? null;
  useEffect(() => {
    if (selectedEvent && (!shown.includes(rowOf(selectedEvent)) || (hideUncertain && isUncertain(selectedEvent)))) {
      setSelected(null);
      setLooping(false);
    }
  }, [selectedEvent, shown, hideUncertain]);
  const loopRange = useMemo(() => {
    if (!looping || !selectedEvent || !bounds) return null;
    return { start: Math.max(bounds.start, selectedEvent.start_ms - CONTEXT_MS), end: Math.min(bounds.end, selectedEvent.end_ms + CONTEXT_MS) };
  }, [looping, selectedEvent, bounds]);

  const trail = useMemo<Trail | null>(() => {
    const limb = selectedEvent && limbOf(selectedEvent);
    if (!selectedEvent || !limb || !movement.available || !selectedEvent.hand) return null;
    const data = movement.limbs[limb];
    const points = movement.t.flatMap((t, i) => (t >= selectedEvent.start_ms && t <= selectedEvent.end_ms && data.x[i] !== null ? [{ t, x: data.x[i]!, y: data.y[i]! }] : []));
    return { points, side: selectedEvent.hand };
  }, [selectedEvent, movement]);

  const select = (event: ClimbEvent) => {
    setSelected(event.id); setGapInfo(null);
    if (bounds) player.current?.seek(Math.max(bounds.start, event.start_ms - CONTEXT_MS));
    document.getElementById(`card-${event.id}`)?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  };

  if (error) return <p className="error" role="alert">{error}</p>;
  if (!result || !summary || !bounds) return <p className="muted">Loading the analysis…</p>;

  const coverage = result.coverage.detectors;
  const footAvailable = Boolean(summary.foot_analysis_available);
  const passes = (event: ClimbEvent) => shown.includes(rowOf(event)) && !(hideUncertain && isUncertain(event));
  const visibleEvents = events.filter(passes);
  const rows = ROWS.filter((row) => coverage[row.detector] && shown.includes(row.key));
  const tracks: Track[] = rows.map((row) => ({ key: row.key, label: row.label, detector: row.detector, events: visibleEvents.filter((e) => rowOf(e) === row.key) }));
  const toggle = (key: RowKey) => setShown((list) => list.includes(key) ? list.filter((k) => k !== key) : [...list, key]);
  const chartLimbs = shown.filter((key): key is Limb => key !== "low");
  const selectById = (id: string) => { const event = events.find((e) => e.id === id); if (event) { if (!passes(event)) { setShown(ALL); setHideUncertain(false); } select(event); } };
  const reasonText = (gap: Gap) => {
    const entries = Object.entries(gap.reasons ?? {});
    return entries.length ? entries.slice(0, 3).map(([key]) => REASONS[key] ?? key).join("; ") : "tracking was not continuous here";
  };

  const countOf = (value: number | null) => (value === null ? "unavailable" : String(value));
  const priority = summary.review_priority.event_ids.map((id) => events.find((e) => e.id === id)).filter(Boolean) as ClimbEvent[];

  return (
    <div className="review">
      <div className="review-main">
        <Player ref={player} src={attempt.video_url!} samples={samples} showSkeleton={skeleton} onTime={setTime} loop={loopRange} focus={focus} trail={trail} />
        <div className="row tight">
          <label className="check"><input type="checkbox" checked={skeleton} onChange={(e) => setSkeleton(e.target.checked)} /> Body skeleton</label>
          <label className="check"><input type="checkbox" checked={looping} disabled={!selectedEvent} onChange={(e) => setLooping(e.target.checked)} /> Loop selected event (±1 s)</label>
          <label className="check">Show on video
            <select data-testid="overlay-focus" value={focus} onChange={(e) => setFocus(e.target.value as Focus)}>
              <option value="all">Whole body</option><option value="feet">Legs and feet</option><option value="hands">Arms and hands</option>
            </select>
          </label>
          <span className="muted">Left is orange and right is blue, as labeled by the pose model. A selected movement draws its tracked path.</span>
        </div>

        {!footAvailable && (
          <section className="card notice" data-testid="old-run-notice" role="status">
            <strong>This older analysis has no foot movement.</strong> It was made before left and right foot tracking was added, and its hand results and notes are kept as they were.
            <div className="row tight"><button className="button primary" data-testid="reanalyze-feet" onClick={onReanalyze}>Reanalyze to add foot movement</button></div>
          </section>
        )}

        {footAvailable && (
          <section className="card filters" aria-label="Filters">
            <div className="row tight">
              <span className="muted">Show</span>
              <button className={`button small ${shown.length === ALL.length ? "active" : ""}`} data-testid="filter-all" onClick={() => setShown(ALL)}>Everything</button>
              <button className={`button small ${shown.length === 2 && FEET.every((k) => shown.includes(k)) ? "active" : ""}`} data-testid="filter-feet" onClick={() => { setShown(FEET); setFocus("feet"); }}>Feet only</button>
              <button className={`button small ${shown.length === 2 && HANDS.every((k) => shown.includes(k)) ? "active" : ""}`} data-testid="filter-hands" onClick={() => { setShown(HANDS); setFocus("hands"); }}>Hands only</button>
              {ROWS.map((row) => <label className="choice" key={row.key}><input type="checkbox" data-testid={`filter-${row.key}`} checked={shown.includes(row.key)} onChange={() => toggle(row.key)} /> {row.label}</label>)}
              <label className="choice"><input type="checkbox" data-testid="hide-uncertain" checked={hideUncertain} onChange={(e) => setHideUncertain(e.target.checked)} /> Hide uncertain foot episodes</label>
            </div>
          </section>
        )}

        <section className="card" aria-label="Timeline">
          <h2>Timeline <span className="muted small-text">{clock(bounds.start)} to {clock(bounds.end)}</span></h2>
          <div className="timeline">
            {tracks.map((track) => {
              const item: DetectorCoverage = coverage[track.detector];
              return (
                <div className="track" key={track.key}>
                  <div className="track-label">{track.label}</div>
                  <div className="track-bar">
                    {item.gaps.map((gap) => (
                      <button key={`g${gap.start_ms}`} className="gap" title={`Not analyzable ${clock(gap.start_ms)} to ${clock(gap.end_ms)}`}
                        aria-label={`Tracking gap ${clock(gap.start_ms)} to ${clock(gap.end_ms)}`}
                        style={{ left: `${percentOf(gap.start_ms)}%`, width: `${(gap.duration_ms / span) * 100}%` }}
                        onClick={() => { setGapInfo({ gap, detector: track.label }); setSelected(null); player.current?.seek(gap.start_ms); }} />
                    ))}
                    {track.events.map((event) => (
                      <button key={event.id} data-testid="timeline-event" className={`event-mark ${event.type} ${isUncertain(event) ? "uncertain" : ""} ${selected === event.id ? "selected" : ""}`}
                        title={eventTitle(event)} aria-label={`${eventTitle(event)} ${clock(event.start_ms)}`}
                        style={{ left: `${percentOf(event.start_ms)}%`, width: `${Math.max(0.6, ((event.end_ms - event.start_ms) / span) * 100)}%` }}
                        onClick={() => select(event)} />
                    ))}
                    <div className="playhead" style={{ left: `${Math.min(100, Math.max(0, percentOf(time)))}%` }} />
                    {item.status !== "available" && <span className="track-empty">Unavailable: not enough tracking</span>}
                  </div>
                </div>
              );
            })}
          </div>
          <p className="legend"><span className="swatch gap-swatch" /> Not analyzable <span className="swatch low-swatch" /> Low movement <span className="swatch wrist-swatch" /> Wrist movement{footAvailable && <><span className="swatch foot-swatch" /> Foot movement <span className="swatch uncertain-swatch" /> Uncertain foot episode</>}</p>
          {gapInfo && (
            <p className="notice-text" role="status">
              {gapInfo.detector}: no analysis from {clock(gapInfo.gap.start_ms)} to {clock(gapInfo.gap.end_ms)} because {reasonText(gapInfo.gap)}.
            </p>
          )}
        </section>

        {movement.available && chartLimbs.length > 0 && (
          <section className="card" aria-label="Movement chart">
            <h2>How fast each limb moved</h2>
            <MovementChart movement={movement} events={visibleEvents} limbs={chartLimbs} bounds={bounds} time={time} selected={selected} onSeek={(ms) => player.current?.seek(ms)} />
          </section>
        )}

        {summary.digest && <DigestPanel digest={summary.digest} onEvent={selectById} />}

        {result.warnings.length > 0 && <section className="card notice"><h2>About this recording</h2><ul className="warnings">{result.warnings.map((w) => <li key={w}>{w}</li>)}</ul></section>}

        <section className="card">
          <h2>Summary</h2>
          <table className="facts"><tbody>
            <tr><th>Attempt duration</th><td>{clock(summary.attempt_duration_ms)}</td></tr>
            <tr><th>Time analyzable for low movement</th><td>{percent(summary.eligible.low_movement.fraction)}</td></tr>
            <tr><th>Time analyzable for left / right wrist</th><td>{percent(summary.eligible.wrist_motion_left.fraction)} / {percent(summary.eligible.wrist_motion_right.fraction)}</td></tr>
            {footAvailable && <tr><th>Time analyzable for left / right foot</th><td>{percent(summary.eligible.foot_motion_left.fraction)} / {percent(summary.eligible.foot_motion_right.fraction)}</td></tr>}
            <tr><th>Low movement, of analyzable time</th><td>{percent(summary.low_movement_fraction_of_eligible)}</td></tr>
            <tr><th>Left / right wrist episodes</th><td>{countOf(summary.wrist_episode_counts.left)} / {countOf(summary.wrist_episode_counts.right)}</td></tr>
            {footAvailable && <tr><th>Left / right foot episodes</th><td>{countOf(summary.foot_episode_counts!.left)} / {countOf(summary.foot_episode_counts!.right)}</td></tr>}
          </tbody></table>
          <p className="muted">These describe what was visible. They are not a technique score, and fewer pauses or movements do not mean better climbing.</p>
          {priority.length > 0 && (<>
            <h3>Suggested order to rewatch</h3>
            <p className="muted">{summary.review_priority.meaning}</p>
            <ol>{priority.filter(passes).map((event) => <li key={event.id}><button className="link" onClick={() => select(event)}>{clock(event.start_ms)}: {eventTitle(event)}</button></li>)}</ol>
          </>)}
        </section>
        <ReflectionPanel attemptId={attempt.id} />
        <section className="card">
          <h2>Export</h2>
          <div className="row">
            {(["json", "csv", "html"] as const).map((format) => (
              <a key={format} className="button" href={`/api/analyses/${run.id}/export?format=${format}`} download>{format === "html" ? "HTML report" : format.toUpperCase()}</a>
            ))}
            <button className="button" onClick={onReanalyze}>Change bounds and reanalyze</button>
          </div>
          <p className="muted small-text">Pipeline {result.pipeline_version} · {result.detection.detector_version} · configuration {result.config_hash.slice(0, 12)}. Thresholds are unvalidated starting values.</p>
        </section>
      </div>
      <aside className="review-side" aria-label="Events">
        <h2>Events ({visibleEvents.length}{visibleEvents.length !== events.length ? ` of ${events.length}` : ""})</h2>
        {events.length === 0 && (
          <p className="muted">
            No events were detected in the analyzable parts of this attempt. That is not a judgment of the climb, and any tracking gaps are shown on the timeline.
          </p>
        )}
        {visibleEvents.map((event) => (
          <EventCard key={event.id} event={event} runId={run.id} selected={selected === event.id} movement={movement} time={time} onSeek={(ms) => player.current?.seek(ms)}
            onSelect={() => select(event)} onSaved={(saved) => setEvents((list) => list.map((e) => (e.id === event.id ? { ...e, review: saved } : e)))} />
        ))}
      </aside>
    </div>
  );
}

function ReflectionPanel({ attemptId }: { attemptId: string }) {
  const [value, setValue] = useState({ observation: "", next_focus: "" });
  const [status, setStatus] = useState("");
  useEffect(() => { api.getReflection(attemptId).then(setValue).catch(() => setStatus("Could not load the saved reflection.")); }, [attemptId]);
  const save = async () => {
    try { setValue(await api.putReflection(attemptId, value)); setStatus("Saved."); }
    catch (e) { setStatus((e as Error).message); }
  };
  return (
    <section className="card">
      <h2>Your reflection</h2>
      <label>One observation from this attempt<textarea data-testid="reflection-observation" value={value.observation} onChange={(e) => setValue({ ...value, observation: e.target.value })} /></label>
      <label>One focus for your next attempt<textarea data-testid="reflection-focus" value={value.next_focus} onChange={(e) => setValue({ ...value, next_focus: e.target.value })} /></label>
      <button className="button primary" data-testid="save-reflection" onClick={save}>Save reflection</button>
      {status && <span className="muted" role="status"> {status}</span>}
    </section>
  );
}
