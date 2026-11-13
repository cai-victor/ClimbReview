import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Perspective } from "./api";
import { Glance, holdApi, ObservedRoute, ProposedHold, RoleProposal, RouteProposal, RouteWall } from "./api";
import { Attempt, BetaCandidate, BetaResult, Coaching, CoachingCard, clock, ComparisonResult, Feedback, performanceApi, Placement, PlacementReview, api, HoldMapSummary } from "./api";

export const LIMB_WORD: Record<string, string> = { left_foot: "Left foot", right_foot: "Right foot", left_hand: "Left hand", right_hand: "Right hand", left_wrist: "Left hand", right_wrist: "Right hand" };
export const holdName = (index: number) => `H${index + 1}`;

const LIMB_SHORT: Record<string, string> = { left_foot: "L foot", right_foot: "R foot", left_hand: "L hand", right_hand: "R hand", left_wrist: "L hand", right_wrist: "R hand" };
const DECISION_WORD: Record<Feedback["decision"], string> = { unreviewed: "", will_try: "You'll try this", intentional: "Intentional", disagree: "Doesn't apply", cannot_tell: "Can't tell" };
export const cueHasFeet = (card: CoachingCard) => card.limbs.some((limb) => limb.endsWith("foot"));
export const cueHasHands = (card: CoachingCard) => card.limbs.some((limb) => !limb.endsWith("foot"));

function DecisionBar({ feedback, onChange, testid, busy = false }: { feedback: Feedback; onChange: (next: Feedback) => void; testid: string; busy?: boolean }) {
  const [note, setNote] = useState(feedback.note);
  const timer = useRef<number | undefined>(undefined);
  const latest = useRef(feedback);
  latest.current = feedback;
  const choose = (decision: Feedback["decision"]) => onChange({ ...latest.current, note, decision: latest.current.decision === decision ? "unreviewed" : decision, trial_outcome: "not_tried" });
  const option = (value: Feedback["decision"], label: string) => (
    <button className="button small" aria-pressed={feedback.decision === value} disabled={busy} data-testid={`${testid}-${value}`} onClick={() => choose(value)}>{label}</button>
  );
  const outcome = (value: Feedback["trial_outcome"], label: string) => (
    <button className="button small" aria-pressed={feedback.trial_outcome === value} disabled={busy} data-testid={`${testid}-outcome-${value}`} onClick={() => onChange({ ...latest.current, note, trial_outcome: value })}>{label}</button>
  );
  const flush = () => { window.clearTimeout(timer.current); if (note !== latest.current.note) onChange({ ...latest.current, note }); };
  return (
    <div className="decision">
      <div className="row tight" role="group" aria-label="Your call on this suggestion" style={{ margin: 0 }}>{option("will_try", "I'll try this")}{option("intentional", "Was intentional")}{option("disagree", "Doesn't apply")}{option("cannot_tell", "Can't tell")}</div>
      {feedback.decision === "will_try" && (
        <div className="row tight" role="group" aria-label="What happened when you tried it" style={{ margin: 0 }}><span className="muted small-text">After trying it:</span>{outcome("helped", "Helped")}{outcome("no_change", "No change")}{outcome("worse", "Worse")}{outcome("unclear", "Unclear")}</div>
      )}
      <label className="small-text">Note to yourself<textarea value={note} data-testid={`${testid}-note`} placeholder="Optional" onBlur={flush} onChange={(e) => {
        const value = e.target.value; setNote(value); window.clearTimeout(timer.current);
        timer.current = window.setTimeout(() => onChange({ ...latest.current, note: value }), 500);
      }} /></label>
    </div>
  );
}

/** One coaching opportunity. Collapsed it says when, which limb, and why to look; open it reads what happened, why, what to try, what to verify. */
export function CoachingCardView({ card, selected, onSelect, onWatch, onFeedback, busy = false }: { card: CoachingCard; selected: boolean; onSelect: () => void; onWatch: () => void; onFeedback: (next: Feedback) => void; busy?: boolean }) {
  const lead = card.uncertainty.slice(0, 2), rest = card.uncertainty.slice(2);
  return (
    <article id={`cue-${card.id}`} className={`card cue-card ${selected ? "selected" : ""}`} data-testid="cue-card" data-kind={card.kind}>
      <button className="cue-head" onClick={onSelect} data-testid="cue-open" aria-expanded={selected} aria-controls={`cue-body-${card.id}`}>
        <span className="cue-time">{clock(card.start_ms)}</span>
        <span>
          <span className="cue-title">{card.title}</span>
          <span className="cue-sub">
            {card.limbs.map((limb) => <span className="chip" key={limb}>{LIMB_SHORT[limb] ?? limb}</span>)}
            <span className="chip outline">{card.status_label}</span>
            {card.feedback.decision !== "unreviewed" && <span className="chip accent">{DECISION_WORD[card.feedback.decision]}</span>}
          </span>
        </span>
        <span className="chev" aria-hidden="true">▶</span>
      </button>
      {selected && (
        <div className="cue-body" id={`cue-body-${card.id}`}>
          <div className="row tight" style={{ margin: 0 }}>
            <button className="button primary small" data-testid="cue-watch" onClick={onWatch}>▶ Watch this moment</button>
            <span className="muted small-text num">{clock(card.start_ms)} to {clock(card.end_ms)}, with 1 s of lead-in</span>
          </div>
          <div className="cue-section">
            <h3>What happened</h3>
            <p>{card.moment}</p>
            {card.measurements.length > 0 && <ul className="cue-facts">{card.measurements.slice(0, 2).map((row) => <li key={row.label}>{row.label}: <strong>{row.value}</strong></li>)}</ul>}
          </div>
          <div className="cue-section"><h3>Why it might matter</h3><p>{card.why}</p></div>
          <div className="cue-section try">
            <h3>What to try</h3>
            <p>{card.try_this}</p>
            {card.alternatives.length > 0 && (
              <ul className="plain-list" data-testid="cue-alternatives">
                {card.alternatives.map((option) => (
                  <li key={`${option.limb}${option.hold_id}`}>{LIMB_WORD[option.limb]} to marked hold {holdName(option.hold_index)}, a {option.step_L.toFixed(2)} L step
                    {option.margin_L !== null && card.observed_margin_L !== undefined ? `. 2D reach margin ${option.margin_L.toFixed(2)} L compared with ${card.observed_margin_L.toFixed(2)} L from your observed feet.` : "."}</li>
                ))}
              </ul>
            )}
            {card.alternative_note && <p className="small-text">{card.alternative_note}</p>}
            {card.alternative_summary && <p className="small-text">{card.alternative_summary}</p>}
            <p className="small-text"><strong>When to keep your way:</strong> {card.keep_if}</p>
          </div>
          <div className="cue-section verify">
            <h3>What to verify</h3>
            {lead.length > 0 ? <ul className="plain-list" style={{ margin: 0 }}>{lead.map((text) => <li key={text}>{text}</li>)}</ul> : <p>Watch the moment and check that it matches what you felt.</p>}
            {card.map_action && <p className="small-text">{card.map_action}</p>}
            <details>
              <summary>All measurements and limits</summary>
              <table className="facts measurements"><thead><tr><th>Measure</th><th>Value</th><th>Rule</th></tr></thead><tbody>
                {card.measurements.map((row) => <tr key={row.label}><td>{row.label}</td><td>{row.value}</td><td>{row.criterion}</td></tr>)}
              </tbody></table>
              {rest.length > 0 && <ul className="plain-list small-text">{rest.map((text) => <li key={text}>{text}</li>)}</ul>}
            </details>
          </div>
          <DecisionBar feedback={card.feedback} onChange={onFeedback} testid="cue" busy={busy} />
        </div>
      )}
    </article>
  );
}

const RESULT_WORD: Record<string, string> = { helped: "helped", no_change: "no change", worse: "worse", unclear: "unclear" };

export function NextAttempt({ coaching, onCue }: { coaching: Coaching; onCue: (id: string) => void }) {
  const plan = coaching.plan;
  if (!plan) return null;
  const empty = plan.chosen.length === 0 && !plan.suggested;
  return (
    <section className="card next-attempt" data-testid="next-attempt">
      <h2>Try on your next attempt</h2>
      {plan.chosen.length > 0 && <p className="muted small-text">Suggestions you chose. Open one to record what happened when you tried it.</p>}
      {plan.chosen.map((item) => (
        <div className="plan-item" key={item.id}>
          <button className="link num" onClick={() => onCue(item.id)}>{clock(item.start_ms)}</button>
          <div>{item.try_this}{item.trial_outcome !== "not_tried" ? <em> Your result: {RESULT_WORD[item.trial_outcome] ?? item.trial_outcome}.</em> : <span className="muted small-text"> Not tried yet.</span>}</div>
        </div>
      ))}
      {plan.suggested && <p><span className="label">Suggested first</span> <button className="link num" onClick={() => onCue(plan.suggested!.id)}>{clock(plan.suggested.start_ms)}</button> {plan.suggested.try_this}</p>}
      {empty && <p className="muted">Nothing chosen yet. Open an opportunity and choose "I'll try this" to build your list.</p>}
      <p className="muted small-text">{coaching.disclaimer}</p>
    </section>
  );
}

export function ReviewedLists({ coaching }: { coaching: Coaching }) {
  return (
    <>
      {coaching.cannot_evaluate.length > 0 && <details className="card" data-testid="cannot-evaluate"><summary>Couldn't be judged from this video ({coaching.cannot_evaluate.length})</summary><p className="muted small-text">Usually a hand or foot was hidden or out of frame at the moment that mattered.</p><ul className="plain-list small-text">{coaching.cannot_evaluate.map((item) => <li key={item.text}>{item.text}</li>)}</ul></details>}
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
    <section data-testid="foot-placements" aria-label="Foot placements">
      <p className="muted small-text">Moments where a foot appeared to settle after moving. Tell the app what it was. Video cannot show contact, sole angle, friction, or pressure, so a smear can only be confirmed by you. <a href="https://philarockgym.com/?p=26439" target="_blank" rel="noreferrer">What smearing relies on</a>.</p>
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

export function BetaFigure({ map, candidate, stepIndex, width, height }: { map: HoldMapSummary; candidate: BetaCandidate | null; stepIndex: number; width: number; height: number }) {
  const point = (index: number) => [map.holds[index].x * width, map.holds[index].y * height] as const;
  const stroke = Math.max(2, width / 300);
  return (
    <div className="beta-stage" style={{ aspectRatio: `${width} / ${height}` }} data-testid="beta-figure">
      <img src={map.frame_url} alt={`Reference frame at ${clock(map.reference_frame_ms)} with marked holds`} />
      <svg viewBox={`0 0 ${width} ${height}`} aria-hidden="true">
        {candidate?.steps.map((step, index) => {
          if (step.from_hold < 0) return null;
          const [x1, y1] = point(step.from_hold), [x2, y2] = point(step.to_hold);
          const foot = step.limb.endsWith("foot"), left = step.limb.startsWith("left");
          return <line key={index} x1={x1} y1={y1} x2={x2} y2={y2} stroke={left ? "#f28c28" : "#2ab7f5"} strokeWidth={index === stepIndex ? stroke * 2 : stroke} strokeDasharray={foot ? `${stroke * 3} ${stroke * 2}` : undefined} opacity={index === stepIndex ? 1 : 0.55} />;
        })}
        {map.holds.map((hold, index) => (
          <g key={hold.id}>
            <circle cx={hold.x * width} cy={hold.y * height} r={hold.radius * width} fill="none" stroke={hold.role === "start" ? "#2fbf71" : hold.role === "finish" ? "#e0245e" : "#ffc800"} strokeWidth={stroke} />
            <text x={hold.x * width} y={hold.y * height} textAnchor="middle" dominantBaseline="middle" fontSize={width / 22} fontWeight="700" fill="#fff" stroke="#000" strokeWidth={stroke / 2} paintOrder="stroke">{index + 1}</text>
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
  if (error) return <section className="card"><h2>Other sequences to test</h2><p className="error" role="alert">{error}</p></section>;
  if (!result) return <section className="card" aria-label="Alternative beta"><h2>Other sequences to test</h2><p className="muted" role="status" data-testid="beta-loading">Reading the wall and working out your route. The first time takes several seconds.</p></section>;
  const candidate = result.candidates[Math.min(active, result.candidates.length - 1)] ?? null;
  const save = async (next: Feedback) => { if (candidate) { await performanceApi.putDecision(runId, candidate.id, next); await load(); onFeedback(); } };
  return (
    <section className="card" data-testid="beta-panel" aria-label="Alternative beta">
      <h2>Other sequences to test</h2>
      <p className="muted small-text">Built from the holds marked on this route and your tracked reach. Each is an option to try on the wall, not a ranking.</p>
      {result.status === "no_map" && <RouteSetup runId={runId} attemptId={attempt.id} onDone={() => { void load(); onFeedback(); }} />}
      {result.hold_map && result.status === "setup_needed" && <FillRoles runId={runId} mapId={result.hold_map.id} onDone={() => { void load(); onFeedback(); }} />}
      {result.status !== "ready" && (
        <>
          {result.status === "no_candidate" ? <p>{result.note}</p> : <ul className="plain-list" data-testid="beta-needs">{result.needs.map((need) => <li key={need}>{need}</li>)}</ul>}
          <a className={result.hold_map ? "button primary" : "button"} data-testid="beta-setup" href={`#/holds/${attempt.id}`}>{result.hold_map ? "Finish marking this route" : "Mark route holds by hand instead"}</a>
        </>
      )}
      {result.hold_map && <BetaFigure map={result.hold_map} candidate={candidate} stepIndex={step} width={attempt.width ?? 1} height={attempt.height ?? 1} />}
      {candidate && (
        <>
          <div className="row tight" role="group" aria-label="Sequence shown">
            {result.candidates.map((item, index) => <button key={item.id} aria-pressed={index === active} className="button small" data-testid="beta-candidate" onClick={() => { setActive(index); setStep(0); }}>{item.label}</button>)}
          </div>
          <p className="small-text">{candidate.move_count} moves, {candidate.total_distance_L.toFixed(1)} L of limb travel, largest single move {candidate.largest_move_L.toFixed(2)} L. Tightest 2D reach margin {candidate.tightest_margin_L.toFixed(2)} L{candidate.tight_moves ? `, with ${candidate.tight_moves} tight move${candidate.tight_moves > 1 ? "s" : ""}` : ""}.</p>
          <p className="small-text"><strong>Start:</strong> {Object.entries(candidate.start).map(([limb, hold]) => `${LIMB_WORD[limb]} ${hold < 0 ? "from the ground" : holdName(hold)}`).join(", ")}</p>
          <ol className="phase-list" data-testid="beta-steps">
            {candidate.steps.map((item, index) => (
              <li key={index}><button className={`link ${index === step ? "strong" : ""}`} onClick={() => setStep(index)}>{LIMB_WORD[item.limb]} to {holdName(item.to_hold)}</button> <span className="muted small-text">{item.from_hold < 0 ? "first placement" : `${item.distance_L.toFixed(2)} L move`}, {item.margin_L.toFixed(2)} L margin{item.tight ? ", tight" : ""}</span></li>
            ))}
          </ol>
          <DecisionBar key={candidate.id} feedback={candidate.feedback} onChange={save} testid="beta" />
        </>
      )}
      {result.note && result.status === "ready" && <p className="notice-text small-text">{result.note}</p>}
      {result.status !== "no_map" && result.status !== "setup_needed" && <PerspectiveNote perspective={result.perspective} />}
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
  const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true);
    try { await api.patchAttempt(attempt.id, form); setStatus("Saved."); await load(); onSaved(); }
    catch (e) { setStatus(`Not saved: ${(e as Error).message}`); }
    finally { setBusy(false); }
  };
  const rows = useMemo(() => data?.attempts.filter((a) => a.metrics) ?? [], [data]);
  const cell = (value: number | null | undefined, suffix = "") => (value === null || value === undefined ? "not comparable" : `${value}${suffix}`);
  return (
    <section className="card" data-testid="compare-panel" aria-label="Compare attempts">
      <h2>Compare attempts on the same problem</h2>
      <p className="muted small-text">Name the problem and the climber. Attempts are matched only when both names are the same, so you decide what counts as the same problem.</p>
      <div className="grid3">
        <label>Problem name<input value={form.problem_label} data-testid="problem-label" onChange={(e) => setForm({ ...form, problem_label: e.target.value })} /></label>
        <label>Climber<input value={form.climber_label} data-testid="climber-label" onChange={(e) => setForm({ ...form, climber_label: e.target.value })} /></label>
        <label>Outcome<input value={form.outcome} data-testid="outcome-label" placeholder="Topped, fell at move 4…" onChange={(e) => setForm({ ...form, outcome: e.target.value })} /></label>
      </div>
      <button className="button primary" data-testid="save-compare" disabled={busy} onClick={save}>{busy ? "Saving…" : "Save and compare"}</button>{status && <span className="muted" role="status"> {status}</span>}
      {data?.status === "needs_labels" && <p className="muted">Add a problem and climber name to compare this attempt with others.</p>}
      {!data && !status && <p className="muted" role="status">Loading…</p>}
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

/** Says whether distances were measured on the wall plane, and what that rests on. */
export function PerspectiveNote({ perspective }: { perspective?: Perspective | null }) {
  if (!perspective) return null;
  const tilt = perspective.tilt;
  return (
    <div className="small-text" data-testid="perspective-note" data-applied={perspective.applied ? "yes" : "no"}>
      <p><strong>{perspective.applied ? "Corrected for the wall's angle." : "Not corrected for the wall's angle."}</strong> {perspective.applied ? perspective.detail : perspective.reason}</p>
      {tilt?.status === "ok" && <p className="muted">The wall is turned about {tilt.angle_to_camera_deg}° from facing the camera: the top leans {Math.abs(tilt.top_toward_camera_deg!)}° {tilt.top_toward_camera_deg! >= 0 ? "toward" : "away from"} the camera, and it is turned {Math.abs(tilt.turned_sideways_deg!)}° sideways. {tilt.note}</p>}
      {tilt?.status === "unknown" && perspective.applied && <p className="muted">{tilt.reason}</p>}
      {perspective.assumption && <p className="muted">{perspective.assumption}</p>}
    </div>
  );
}

const USE_WORD: Record<string, string> = { hand: "hands", foot: "feet", both: "hands and feet", "": "not set" };

/** Two taps and a confirmation: pick the route color, pick the start, then save. Everything shown is a proposal until saved. */
export function RouteSetup({ runId, attemptId, onDone }: { runId: string; attemptId: string; onDone: () => void }) {
  const [wall, setWall] = useState<RouteWall | null>(null);
  const [proposal, setProposal] = useState<RouteProposal | null>(null);
  const [holds, setHolds] = useState<(ProposedHold & { skip: boolean })[]>([]);
  const [tolerance, setTolerance] = useState("normal");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [open, setOpen] = useState(false);
  const svg = useRef<SVGSVGElement>(null);
  useEffect(() => { if (open && !wall) performanceApi.routeWall(runId).then(setWall).catch((e) => setError(e.message)); }, [open, wall, runId]);

  const tap = (event: React.MouseEvent<SVGSVGElement>) => {
    if (!wall || !svg.current || event.target !== svg.current || busy) return;
    const point = new DOMPoint(event.clientX, event.clientY).matrixTransform(svg.current.getScreenCTM()!.inverse());
    const x = point.x / wall.width, y = point.y / wall.height;
    if (x < 0 || x > 1 || y < 0 || y > 1) return;
    setBusy(true); setError("");
    performanceApi.routeProposal(runId, { x, y, tolerance })
      .then((result) => { setProposal(result); setHolds(result.holds.map((h) => ({ ...h, skip: false }))); })
      .catch((e) => { setError((e as Error).message); })
      .finally(() => setBusy(false));
  };
  // Clicking a proposed hold cycles it: route hold, start hold, left out.
  const cycle = (index: number) => setHolds((list) => list.map((h, i) => i !== index ? h
    : h.skip ? { ...h, skip: false } : h.role === "start" ? { ...h, role: "", skip: true } : h.role === "finish" ? { ...h, role: "", skip: true } : { ...h, role: "start" }));
  const kept = holds.filter((h) => !h.skip);
  const starts = kept.filter((h) => h.role === "start").length, finish = kept.some((h) => h.role === "finish");
  const save = async () => {
    if (!wall) return;
    setBusy(true); setError("");
    try {
      const map = await holdApi.create(attemptId, { name: "My route", reference_frame_ms: wall.reference_frame_ms });
      for (const h of kept) await holdApi.addHold(map.id, { x: h.x, y: h.y, radius: h.radius, route: "", hold_type: "", role: h.role, use: h.role === "start" && h.use !== "hand" ? "both" : h.use });   // a start hold is always usable by hands
      onDone();
    } catch (e) { setError((e as Error).message); setBusy(false); }
  };

  if (!open) return (
    <div data-testid="route-setup-intro">
      <p>Set up your route in two clicks: click one hold of your route, then click your start hold. The app finds the other holds of that color and proposes the finish and which holds your hands and feet used.</p>
      <button className="button primary" data-testid="route-setup-open" onClick={() => setOpen(true)}>Set up my route</button>
    </div>
  );
  return (
    <div data-testid="route-setup">
      {error && <p className="error" role="alert">{error}</p>}
      {!wall ? <p className="muted" role="status">Building a clear picture of the wall…</p> : (
        <>
          <p className="notice-text small-text" role="status" data-testid="route-step">
            {!proposal ? "Step 1 of 2: click directly on one hold of your route, on its most colorful part."
              : proposal.status !== "proposed" ? proposal.reason
              : starts === 0 ? "Step 2 of 2: click your start hold or holds. Click a wrong outline twice to leave it out."
              : "Check the outlines, then save. You can still adjust everything in the hold editor."}
          </p>
          <div className="beta-stage" style={{ aspectRatio: `${wall.width} / ${wall.height}` }}>
            <img src={wall.image_url} alt="Wall picture combined from the video, with the climber removed" />
            <svg ref={svg} viewBox={`0 0 ${wall.width} ${wall.height}`} onClick={tap} data-testid="route-setup-svg" style={{ cursor: proposal ? "default" : "crosshair" }}>
              {holds.map((h, index) => (
                <g key={index} opacity={h.skip ? 0.35 : 1}>
                  <circle cx={h.x * wall.width} cy={h.y * wall.height} r={h.radius * wall.width + wall.width / 200} fill="rgba(0,0,0,0.001)"
                    stroke={h.skip ? "#999" : h.role === "start" ? "#2fbf71" : h.role === "finish" ? "#e0245e" : "#ffc800"} strokeWidth={wall.width / 160} strokeDasharray={h.visited_by.length ? undefined : `${wall.width / 90}`}
                    role="button" tabIndex={0} data-testid="proposed-hold" data-role={h.skip ? "skip" : h.role} aria-label={`Proposed hold ${index + 1}: ${h.skip ? "left out" : h.role || "route hold"}, use ${USE_WORD[h.use]}. Activate to change.`}
                    onClick={(e) => { e.stopPropagation(); cycle(index); }} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); cycle(index); } }} style={{ cursor: "pointer" }} />
                  <text x={h.x * wall.width} y={h.y * wall.height - h.radius * wall.width - wall.width / 90} textAnchor="middle" fontSize={wall.width / 30} fontWeight="700" fill="#fff" stroke="#000" strokeWidth={wall.width / 400} paintOrder="stroke" pointerEvents="none">{h.skip ? "" : h.role === "start" ? "START" : h.role === "finish" ? "FINISH" : ""}</text>
                </g>
              ))}
            </svg>
          </div>
          <p className="muted small-text">{wall.detail}</p>
          {proposal?.status === "proposed" && (
            <>
              <p className="small-text" data-testid="route-summary">{kept.length} holds. Green is start, red is the proposed finish (the highest hold), yellow is the rest. Solid outlines are holds a tracked hand or foot rested near; dashed ones share the color only. Proposed use is set for {kept.filter((h) => h.use).length} of them.</p>
              <ul className="plain-list small-text">{[...proposal.notes.filter((n) => starts === 0 || !n.startsWith("Choose your start")), proposal.disclaimer ?? "", proposal.color_note].filter(Boolean).map((note) => <li key={note}>{note}</li>)}</ul>
            </>
          )}
          <div className="row tight">
            <button className="button primary" data-testid="route-save" disabled={busy || starts === 0 || !finish || kept.length < 3} onClick={() => void save()}>Use this route</button>
            {proposal && <button className="button" data-testid="route-retry" onClick={() => { setProposal(null); setHolds([]); }}>Pick a different hold</button>}
            <label className="small-text">Color match <select value={tolerance} data-testid="route-tolerance" onChange={(e) => setTolerance(e.target.value)}><option value="strict">Strict</option><option value="normal">Normal</option><option value="loose">Loose</option></select></label>
          </div>
          {proposal?.status === "proposed" && !finish && <p className="muted small-text">The proposed finish was left out. Set the finish in the hold editor after saving, or pick again.</p>}
        </>
      )}
    </div>
  );
}

/** For a map marked by hand: propose the finish and each hold's use, and apply them only to fields the climber left empty. */
export function FillRoles({ runId, mapId, onDone }: { runId: string; mapId: string; onDone: () => void }) {
  const [proposal, setProposal] = useState<RoleProposal | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const changes = proposal?.status === "proposed" ? proposal.holds.filter((h) => (!h.current_role && h.role) || (!h.current_use && h.use)) : [];
  const hasFinish = proposal?.holds.some((h) => h.current_role === "finish");
  const apply = async () => {
    setBusy(true);
    try {
      const map = await holdApi.get(mapId);
      for (const change of changes) {
        const hold = map.holds.find((h) => h.id === change.id);
        if (!hold) continue;
        await holdApi.editHold(mapId, hold.id, { x: hold.x, y: hold.y, radius: hold.radius, route: hold.route, hold_type: hold.hold_type,
          role: hold.role || (change.role === "finish" && hasFinish ? "" : change.role), use: hold.use || change.use });
      }
      onDone();
    } catch (e) { setError((e as Error).message); setBusy(false); }
  };
  return (
    <div data-testid="fill-roles">
      {error && <p className="error" role="alert">{error}</p>}
      {!proposal && <button className="button primary" data-testid="fill-roles-open" onClick={() => performanceApi.roleProposal(runId, mapId).then(setProposal).catch((e) => setError(e.message))}>Propose finish and uses from my movement</button>}
      {proposal?.status === "not_possible" && <p className="muted">{proposal.reason}</p>}
      {proposal?.status === "proposed" && (
        <>
          <p className="small-text" data-testid="fill-roles-summary">{changes.length === 0 ? "Nothing to add: no tracked limb rested near the holds that are still unset." : `This would fill in ${changes.length} holds you left unset: ${changes.map((c) => `${[c.current_role ? "" : c.role, c.current_use ? "" : USE_WORD[c.use]].filter(Boolean).join(", ")}`).join("; ")}. Nothing you already set is changed.`}</p>
          <ul className="plain-list small-text">{[...proposal.notes, proposal.disclaimer ?? ""].filter(Boolean).map((note) => <li key={note}>{note}</li>)}</ul>
          {changes.length > 0 && <button className="button primary" data-testid="fill-roles-apply" disabled={busy} onClick={() => void apply()}>Apply these</button>}
        </>
      )}
    </div>
  );
}

const share = (values: (number | null)[]) => values.map((v) => (v === null ? "n/a" : `${Math.round(v * 100)}%`)).join(" / ");

export function GlancePanel({ glance, onSeek }: { glance: Glance; onSeek: (ms: number) => void }) {
  return (
    <section className="card" data-testid="glance" aria-label="At a glance">
      <h2>At a glance</h2>
      <div className="stat-row">
        <div className="stat"><span className="stat-value">{clock(glance.attempt_ms)}</span><span className="stat-label">analyzed</span></div>
        <div className="stat"><span className="stat-value">{glance.hand_moves}</span><span className="stat-label">hand moves tracked</span></div>
        <div className="stat"><span className="stat-value">{glance.foot_moves}</span><span className="stat-label">foot moves tracked</span></div>
        <div className="stat"><span className="stat-value">{glance.longest_gap_ms === null ? "n/a" : `${(glance.longest_gap_ms / 1000).toFixed(1)} s`}</span>
          <span className="stat-label">longest time with no tracked move{glance.longest_gap_at_ms !== null && <> at <button className="link" onClick={() => onSeek(glance.longest_gap_at_ms!)}>{clock(glance.longest_gap_at_ms)}</button></>}</span></div>
      </div>
      <p className="muted small-text">Time each limb could be tracked, left / right: hands {share(glance.hand_tracked)}, feet {share(glance.foot_tracked)}. {glance.notes.join(" ")} These are counts, not a score.</p>
    </section>
  );
}

export function ObservedRoutePanel({ route, onSeek }: { route: ObservedRoute; onSeek: (ms: number) => void }) {
  return (
    <section className="card" data-testid="observed-route" aria-label="Your route as tracked">
      <h2>Your route as tracked</h2>
      {route.visits.length === 0 ? <p className="muted">No tracked hand or foot rested near a marked hold.</p> : (
        <ol className="phase-list">{route.visits.map((v) => <li key={`${v.limb}${v.start_ms}`}><button className="link" onClick={() => onSeek(v.start_ms)}>{clock(v.start_ms)}</button> {LIMB_WORD[v.limb]} rested near {holdName(v.hold_index)}</li>)}</ol>
      )}
      {route.unvisited.length > 0 && <p className="small-text" data-testid="unvisited">No tracked limb rested near {route.unvisited.map(holdName).join(", ")}. If you skipped {route.unvisited.length > 1 ? "them" : "it"}, would using {route.unvisited.length > 1 ? "one" : "it"} as an extra hand or foot make a hard move easier?</p>}
      <p className="muted small-text">{route.note}</p>
    </section>
  );
}
