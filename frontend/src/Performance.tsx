import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Attempt, BetaCandidate, BetaResult, Coaching, CoachingCard, clock, ComparisonResult, Feedback, performanceApi, Placement, PlacementReview, api, HoldMapSummary } from "./api";

const LIMB_WORD: Record<string, string> = { left_foot: "Left foot", right_foot: "Right foot", left_hand: "Left hand", right_hand: "Right hand", left_wrist: "Left hand", right_wrist: "Right hand" };
const holdName = (index: number) => `H${index + 1}`;

function DecisionBar({ feedback, onChange, testid }: { feedback: Feedback; onChange: (next: Feedback) => void; testid: string }) {
  const [note, setNote] = useState(feedback.note);
  const timer = useRef<number | undefined>(undefined);
  const latest = useRef(feedback);
  latest.current = feedback;
  const choose = (decision: Feedback["decision"]) => onChange({ ...latest.current, decision: latest.current.decision === decision ? "unreviewed" : decision, trial_outcome: "not_tried" });
  const option = (value: Feedback["decision"], label: string) => (
    <button className={`button small ${feedback.decision === value ? "active" : ""}`} aria-pressed={feedback.decision === value} data-testid={`${testid}-${value}`} onClick={() => choose(value)}>{label}</button>
  );
  const outcome = (value: Feedback["trial_outcome"], label: string) => (
    <button className={`button small ${feedback.trial_outcome === value ? "active" : ""}`} aria-pressed={feedback.trial_outcome === value} data-testid={`${testid}-outcome-${value}`} onClick={() => onChange({ ...latest.current, trial_outcome: value })}>{label}</button>
  );
  return (
    <div className="decision">
      <div className="row tight">{option("will_try", "I'll try this")}{option("intentional", "Was intentional")}{option("disagree", "Doesn't apply")}{option("cannot_tell", "Can't tell")}</div>
      {feedback.decision === "will_try" && (
        <div className="row tight"><span className="muted small-text">After trying it:</span>{outcome("helped", "Helped")}{outcome("no_change", "No change")}{outcome("worse", "Worse")}{outcome("unclear", "Unclear")}</div>
      )}
      <label className="small-text">Note<textarea value={note} data-testid={`${testid}-note`} onChange={(e) => {
        const value = e.target.value; setNote(value); window.clearTimeout(timer.current);
        timer.current = window.setTimeout(() => onChange({ ...latest.current, note: value }), 500);
      }} /></label>
    </div>
  );
}

export function CoachingCardView({ card, selected, onSelect, onFeedback }: { card: CoachingCard; selected: boolean; onSelect: () => void; onFeedback: (next: Feedback) => void }) {
  return (
    <article id={`cue-${card.id}`} className={`card cue-card ${selected ? "selected" : ""}`} data-testid="cue-card" data-kind={card.kind}>
      <button className="cue-head" onClick={onSelect} data-testid="cue-open"><strong>{card.title}</strong><span>{clock(card.start_ms)} to {clock(card.end_ms)}</span></button>
      <p className="cue-label">{card.status_label}</p>
      <p><span className="label">What happened</span> {card.moment}</p>
      <p className="try-this"><span className="label">Try this</span> {card.try_this}</p>
      {card.alternatives.length > 0 && (
        <ul className="plain-list" data-testid="cue-alternatives">
          {card.alternatives.map((option) => (
            <li key={`${option.limb}${option.hold_id}`}>{LIMB_WORD[option.limb]} to marked hold {holdName(option.hold_index)}, a {option.step_L.toFixed(2)} L step
              {option.margin_L !== null && card.observed_margin_L !== undefined ? `. 2D reach margin ${option.margin_L.toFixed(2)} L compared with ${card.observed_margin_L.toFixed(2)} L from your observed feet.` : "."}</li>
          ))}
        </ul>
      )}
      {card.alternative_note && <p className="muted small-text">{card.alternative_note}</p>}
      {card.alternative_summary && <p className="muted small-text">{card.alternative_summary}</p>}
      {card.map_action && <p className="muted small-text">{card.map_action}</p>}
      <p><span className="label">Why it could matter</span> {card.why}</p>
      <p><span className="label">Keep your way if</span> {card.keep_if}</p>
      <details>
        <summary>Measurements and limits</summary>
        <table className="facts measurements"><thead><tr><th>Measure</th><th>Value</th><th>Rule</th></tr></thead><tbody>
          {card.measurements.map((row) => <tr key={row.label}><td>{row.label}</td><td>{row.value}</td><td>{row.criterion}</td></tr>)}
        </tbody></table>
        <ul className="plain-list small-text">{card.uncertainty.map((text) => <li key={text}>{text}</li>)}</ul>
      </details>
      <DecisionBar feedback={card.feedback} onChange={onFeedback} testid="cue" />
    </article>
  );
}

export function NextAttempt({ coaching, onCue }: { coaching: Coaching; onCue: (id: string) => void }) {
  const plan = coaching.plan;
  if (!plan) return null;
  const empty = plan.chosen.length === 0 && !plan.suggested;
  return (
    <section className="card next-attempt" data-testid="next-attempt">
      <h2>For your next attempt</h2>
      {plan.chosen.map((item) => (
        <p key={item.id}><button className="link" onClick={() => onCue(item.id)}>{clock(item.start_ms)}</button> {item.try_this}{item.trial_outcome !== "not_tried" && <em> Your result: {item.trial_outcome.replace("_", " ")}.</em>}</p>
      ))}
      {plan.suggested && <p><span className="label">Suggested first</span> <button className="link" onClick={() => onCue(plan.suggested!.id)}>{clock(plan.suggested.start_ms)}</button> {plan.suggested.try_this}</p>}
      {empty && <p className="muted">No open suggestion from this attempt. See what was reviewed and why below the suggestion list.</p>}
      <p className="muted small-text">{coaching.disclaimer}</p>
    </section>
  );
}

export function ReviewedLists({ coaching }: { coaching: Coaching }) {
  return (
    <>
      {coaching.cannot_evaluate.length > 0 && <details className="card" data-testid="cannot-evaluate"><summary>Could not be judged ({coaching.cannot_evaluate.length})</summary><ul className="plain-list small-text">{coaching.cannot_evaluate.map((item) => <li key={item.text}>{item.text}</li>)}</ul></details>}
      {coaching.not_flagged.length > 0 && <details className="card" data-testid="not-flagged"><summary>Checked and not flagged ({coaching.not_flagged.length})</summary><ul className="plain-list small-text">{coaching.not_flagged.map((item) => <li key={item.text}>{item.text}</li>)}</ul></details>}
      {coaching.cards_omitted > 0 && <p className="muted small-text">{coaching.cards_omitted} more possible suggestions were left out, so this list stays short.</p>}
    </>
  );
}

const PROXIMITY: Record<string, string> = {
  map_unavailable: "Marked holds cannot be compared here.", no_foot_hold_marked: "No marked foothold on this route yet.",
  within_marked_region: "The tracked point is inside a marked region. That is proximity, not confirmed contact.",
  near_marked_region: "The tracked point is close to a marked region. That is proximity, not confirmed contact.",
  no_marked_hold_nearby: "No marked hold is close by. It could be a smear, an unmarked hold, or a foot off the wall.",
};
const STATUS: [PlacementReview["status"], string][] = [["on_marked_hold", "On a marked hold"], ["on_unmarked_hold", "On an unmarked hold"], ["intentional_smear", "Intentional smear"], ["not_placed", "Not placed"], ["cannot_tell", "Can't tell"]];

export function FootPlacements({ coaching, onSeek, onSave, attemptId }: { coaching: Coaching; onSeek: (item: Placement) => void; onSave: (item: Placement, review: PlacementReview) => void; attemptId: string }) {
  const holds = coaching.hold_map?.holds ?? [];
  return (
    <section className="card" data-testid="foot-placements" aria-label="Foot placements">
      <h2>Foot placements to check</h2>
      <p className="muted small-text">These are moments where a foot appeared to settle after moving. Video cannot show contact, sole angle, friction, or pressure, so a smear can only be confirmed by you. <a href="https://philarockgym.com/?p=26439" target="_blank" rel="noreferrer">What smearing relies on</a>.</p>
      {coaching.placements.length === 0 && <p className="muted">No foot settled clearly enough to review in this attempt.</p>}
      <ul className="placement-list">
        {coaching.placements.map((item) => (
          <li key={item.id} data-testid="placement">
            <div className="row tight"><button className="link" data-testid="placement-seek" onClick={() => onSeek(item)}>{clock(item.landing_ms)}</button><strong>{LIMB_WORD[item.limb]}</strong>
              <span className="muted small-text">using the {item.anchor} point</span></div>
            <p className="small-text">{PROXIMITY[item.proximity]}{item.nearest_hold ? ` Nearest marked hold: ${holdName(item.nearest_hold.hold_index)}, ${item.nearest_hold.edge_L.toFixed(2)} L from its edge.` : ""}</p>
            <div className="row tight">
              {STATUS.map(([value, label]) => (
                <button key={value} className={`button small ${item.review.status === value ? "active" : ""}`} aria-pressed={item.review.status === value} data-testid={`placement-${value}`} disabled={value === "on_marked_hold" && holds.length === 0}
                  onClick={() => onSave(item, { status: item.review.status === value ? "unreviewed" : value, note: item.review.note, hold_id: value === "on_marked_hold" && item.review.status !== value ? (item.nearest_hold?.hold_id ?? holds[0]?.id ?? null) : null })}>{label}</button>
              ))}
            </div>
            {item.review.status === "on_marked_hold" && (
              <label className="small-text">Which hold
                <select value={item.review.hold_id ?? ""} data-testid="placement-hold" onChange={(e) => onSave(item, { ...item.review, hold_id: e.target.value })}>
                  {holds.map((hold, index) => <option key={hold.id} value={hold.id}>{holdName(index)}</option>)}
                </select>
              </label>
            )}
          </li>
        ))}
      </ul>
      {!coaching.hold_map && <a className="button small" href={`#/holds/${attemptId}`}>Mark holds on this route</a>}
    </section>
  );
}

function BetaFigure({ map, candidate, stepIndex, width, height }: { map: HoldMapSummary; candidate: BetaCandidate | null; stepIndex: number; width: number; height: number }) {
  const point = (index: number) => [map.holds[index].x * width, map.holds[index].y * height] as const;
  const stroke = Math.max(2, width / 300);
  return (
    <div className="beta-stage" style={{ aspectRatio: `${width} / ${height}` }} data-testid="beta-figure">
      <img src={map.frame_url} alt={`Reference frame at ${clock(map.reference_frame_ms)} with marked holds`} />
      <svg viewBox={`0 0 ${width} ${height}`} aria-hidden="true">
        {candidate?.steps.map((step, index) => {
          const [x1, y1] = point(step.from_hold), [x2, y2] = point(step.to_hold);
          const foot = step.limb.endsWith("foot"), left = step.limb.startsWith("left");
          return <line key={index} x1={x1} y1={y1} x2={x2} y2={y2} stroke={left ? "#f28c28" : "#2ab7f5"} strokeWidth={index === stepIndex ? stroke * 2 : stroke} strokeDasharray={foot ? `${stroke * 3} ${stroke * 2}` : undefined} opacity={index === stepIndex ? 1 : 0.55} />;
        })}
        {map.holds.map((hold, index) => (
          <g key={hold.id}>
            <circle cx={hold.x * width} cy={hold.y * height} r={hold.radius * width} fill="none" stroke={hold.role === "start" ? "#2fbf71" : hold.role === "finish" ? "#e0245e" : "#ffc800"} strokeWidth={stroke} />
            <text x={hold.x * width} y={hold.y * height} textAnchor="middle" dominantBaseline="middle" fontSize={width / 34} fontWeight="700" fill="#fff" stroke="#000" strokeWidth={stroke / 2} paintOrder="stroke">{index + 1}</text>
          </g>
        ))}
      </svg>
    </div>
  );
}

export function BetaPanel({ attempt, runId, reloadKey, onFeedback }: { attempt: Attempt; runId: string; reloadKey: number; onFeedback: () => void }) {
  const [result, setResult] = useState<BetaResult | null>(null);
  const [active, setActive] = useState(0);
  const [step, setStep] = useState(0);
  const [error, setError] = useState("");
  const load = useCallback(() => performanceApi.candidateBeta(runId).then(setResult).catch((e) => setError(e.message)), [runId]);
  useEffect(() => { void load(); }, [load, reloadKey]);
  if (error) return <section className="card"><h2>Alternative beta to try</h2><p className="error" role="alert">{error}</p></section>;
  if (!result) return null;
  const candidate = result.candidates[Math.min(active, result.candidates.length - 1)] ?? null;
  const save = async (next: Feedback) => { if (candidate) { await performanceApi.putDecision(runId, candidate.id, next); await load(); onFeedback(); } };
  return (
    <section className="card" data-testid="beta-panel" aria-label="Alternative beta">
      <h2>Alternative beta to try</h2>
      {result.status !== "ready" && (
        <>
          {result.status === "no_candidate" ? <p>{result.note}</p> : <ul className="plain-list" data-testid="beta-needs">{result.needs.map((need) => <li key={need}>{need}</li>)}</ul>}
          <a className="button primary" data-testid="beta-setup" href={`#/holds/${attempt.id}`}>{result.hold_map ? "Finish marking this route" : "Mark holds on this route"}</a>
        </>
      )}
      {result.hold_map && <BetaFigure map={result.hold_map} candidate={candidate} stepIndex={step} width={attempt.width ?? 1} height={attempt.height ?? 1} />}
      {candidate && (
        <>
          <div className="row tight" role="tablist">
            {result.candidates.map((item, index) => <button key={item.id} role="tab" aria-selected={index === active} className={`button small ${index === active ? "active" : ""}`} data-testid="beta-candidate" onClick={() => { setActive(index); setStep(0); }}>{item.label}</button>)}
          </div>
          <p className="small-text">{candidate.move_count} moves, {candidate.total_distance_L.toFixed(1)} L of limb travel, largest single move {candidate.largest_move_L.toFixed(2)} L. Tightest 2D reach margin {candidate.tightest_margin_L.toFixed(2)} L{candidate.tight_moves ? `, with ${candidate.tight_moves} tight move${candidate.tight_moves > 1 ? "s" : ""}` : ""}.</p>
          <p className="small-text"><strong>Start:</strong> {Object.entries(candidate.start).map(([limb, hold]) => `${LIMB_WORD[limb]} ${holdName(hold)}`).join(", ")}</p>
          <ol className="phase-list" data-testid="beta-steps">
            {candidate.steps.map((item, index) => (
              <li key={index}><button className={`link ${index === step ? "strong" : ""}`} onClick={() => setStep(index)}>{LIMB_WORD[item.limb]} to {holdName(item.to_hold)}</button> <span className="muted small-text">{item.distance_L.toFixed(2)} L move, {item.margin_L.toFixed(2)} L margin{item.tight ? ", tight" : ""}</span></li>
            ))}
          </ol>
          <DecisionBar key={candidate.id} feedback={candidate.feedback} onChange={save} testid="beta" />
        </>
      )}
      {result.note && result.status === "ready" && <p className="notice-text small-text">{result.note}</p>}
      {result.assumptions && result.status !== "setup_needed" && <details><summary>Assumptions</summary><ul className="plain-list small-text">{result.assumptions.map((text) => <li key={text}>{text}</li>)}</ul></details>}
      {result.hold_map && !result.hold_map.usable && <p className="muted small-text">{result.hold_map.message} Candidate sequences stay on the reference frame.</p>}
    </section>
  );
}

export function ComparePanel({ attempt, onSaved }: { attempt: Attempt; onSaved: () => void }) {
  const [form, setForm] = useState({ problem_label: attempt.problem_label ?? "", climber_label: attempt.climber_label ?? "", outcome: attempt.outcome ?? "" });
  const [data, setData] = useState<ComparisonResult | null>(null);
  const [status, setStatus] = useState("");
  const load = useCallback(() => performanceApi.comparison(attempt.id).then(setData).catch((e) => setStatus(e.message)), [attempt.id]);
  useEffect(() => { void load(); }, [load]);
  const save = async () => {
    try { await api.patchAttempt(attempt.id, form); setStatus("Saved."); await load(); onSaved(); }
    catch (e) { setStatus((e as Error).message); }
  };
  const rows = useMemo(() => data?.attempts.filter((a) => a.metrics) ?? [], [data]);
  const cell = (value: number | null | undefined, suffix = "") => (value === null || value === undefined ? "not comparable" : `${value}${suffix}`);
  return (
    <section className="card" data-testid="compare-panel" aria-label="Compare attempts">
      <h2>Compare attempts on the same problem</h2>
      <p className="muted small-text">Attempts are compared only when you give them the same problem name and climber name.</p>
      <div className="grid3">
        <label>Problem name<input value={form.problem_label} data-testid="problem-label" onChange={(e) => setForm({ ...form, problem_label: e.target.value })} /></label>
        <label>Climber<input value={form.climber_label} data-testid="climber-label" onChange={(e) => setForm({ ...form, climber_label: e.target.value })} /></label>
        <label>Outcome<input value={form.outcome} data-testid="outcome-label" placeholder="Topped, fell at move 4…" onChange={(e) => setForm({ ...form, outcome: e.target.value })} /></label>
      </div>
      <button className="button" data-testid="save-compare" onClick={save}>Save</button>{status && <span className="muted" role="status"> {status}</span>}
      {data?.status === "needs_labels" && <p className="muted">Add a problem and climber name to compare this attempt with others.</p>}
      {data?.status === "no_match" && <p className="muted" data-testid="compare-none">No other analyzed attempt has this same problem and climber yet.</p>}
      {data?.status === "ready" && (
        <>
          <div className="table-scroll"><table className="facts" data-testid="compare-table"><thead><tr><th>Attempt</th><th>Your outcome</th><th>Time</th><th>Foot coverage L / R</th><th>Foot moves per analyzable min</th><th>Reaches with a foot step first</th></tr></thead><tbody>
            {rows.map((row) => (
              <tr key={row.id} className={row.is_current ? "current-row" : ""}><td>{row.title}{row.is_current ? " (this one)" : ""}</td><td>{row.outcome || "not recorded"}</td><td>{clock(row.metrics!.attempt_ms)}</td>
                <td>{row.metrics!.foot_coverage.map((f) => (f === null ? "n/a" : `${Math.round(f * 100)}%`)).join(" / ")}</td>
                <td>{cell(row.metrics!.foot_moves_per_analyzable_minute)}</td>
                <td>{row.metrics!.reaches_with_foot_setup === null ? "not comparable" : `${row.metrics!.reaches_with_foot_setup} of ${row.metrics!.reaches_evaluated}`}</td></tr>
            ))}
          </tbody></table></div>
          <p className="muted small-text">{data.meaning}</p>
        </>
      )}
    </section>
  );
}
