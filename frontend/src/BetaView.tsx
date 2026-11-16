import { useEffect, useRef, useState } from "react";
import { BetaCandidate, BetaPose, BetaStep, clock, HoldMapSummary } from "./api";
import { PART_COLOR } from "./Player";
import { reducedMotion } from "./ui";

export const LIMB_SHORT: Record<string, string> = { left_hand: "LH", right_hand: "RH", left_foot: "LF", right_foot: "RF" };
const LIMB_NAME: Record<string, string> = { left_hand: "Left hand", right_hand: "Right hand", left_foot: "Left foot", right_foot: "Right foot" };
const holdName = (index: number) => `H${index + 1}`;
const ROLE_COLOR = { start: "#2fbf71", finish: "#e0245e", "": "#ffc800" } as const;
const TWEEN_MS = 450, PLAY_MS = 1300;
const ARM: [string, string][] = [["left_shoulder", "left_elbow"], ["left_elbow", "left_hand"], ["right_shoulder", "right_elbow"], ["right_elbow", "right_hand"]];
const LEG: [string, string][] = [["left_hip", "left_knee"], ["left_knee", "left_foot"], ["right_hip", "right_knee"], ["right_knee", "right_foot"]];
const TORSO: [string, string][] = [["neck", "pelvis"], ["left_shoulder", "right_shoulder"], ["left_hip", "right_hip"]];

/** Eases the drawn figure from its last position to the new one, so a step reads as a movement. */
function useTween(target: BetaPose | null): BetaPose | null {
  const [shown, setShown] = useState<BetaPose | null>(target);
  const from = useRef<BetaPose | null>(target);
  const current = useRef<BetaPose | null>(target);
  useEffect(() => {
    if (!target || !current.current || reducedMotion()) { current.current = target; setShown(target); return; }
    from.current = current.current;
    const began = performance.now();
    let frame = 0;
    const tick = (now: number) => {
      const raw = Math.min(1, (now - began) / TWEEN_MS), k = raw * raw * (3 - 2 * raw);
      const next: BetaPose = {};
      for (const name of Object.keys(target)) {
        const a = from.current?.[name] ?? target[name], b = target[name];
        next[name] = [a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k];
      }
      current.current = next; setShown(next);
      if (raw < 1) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [target]);
  return shown;
}

/**
 * The marked holds with one candidate drawn on them. `position` 0 is the start; position n is after step n.
 * Hands are blue and feet orange, matching the skeleton on the video.
 */
export function BetaFigure({ map, candidate, position, width, height }: { map: HoldMapSummary; candidate: BetaCandidate | null; position: number; width: number; height: number }) {
  const point = (index: number) => [map.holds[index].x * width, map.holds[index].y * height] as const;
  const stroke = Math.max(2, width / 300);
  const figures = candidate?.figures;
  const pose = useTween(figures ? figures[Math.min(position, figures.length - 1)] : null);
  const at = (name: string) => (pose?.[name] ? [pose[name][0] * width, pose[name][1] * height] as const : null);
  const moving = candidate && position > 0 ? candidate.steps[position - 1] : null;
  const placed: Record<string, number> = candidate ? { ...candidate.start } : {};
  candidate?.steps.slice(0, position).forEach((step) => { placed[step.limb] = step.to_hold; });
  const bone = (pair: [string, string], color: string, key: string, dashed = false) => {
    const a = at(pair[0]), b = at(pair[1]);
    return a && b ? <g key={key}><line x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]} stroke="rgba(0,0,0,.75)" strokeWidth={stroke * 3.2} strokeLinecap="round" />
      <line x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]} stroke={color} strokeWidth={stroke * 1.8} strokeLinecap="round" strokeDasharray={dashed ? `${stroke * 2.5} ${stroke * 3}` : undefined} /></g> : null;
  };
  const head = at("head");
  return (
    <div className="beta-stage" style={{ aspectRatio: `${width} / ${height}` }} data-testid="beta-figure" data-position={position} data-figure={pose ? "1" : "0"}>
      <img src={map.frame_url} alt={`Reference frame at ${clock(map.reference_frame_ms)} with marked holds`} />
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={candidate ? `Sketch of the climber ${position === 0 ? "at the start" : `after move ${position}`}` : "Marked holds"}>
        <defs><marker id="move-head" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="4.5" markerHeight="4.5" orient="auto"><path d="M0 0 L10 5 L0 10 z" fill="#ffe14a" /></marker></defs>
        {candidate?.steps.map((step, index) => {
          if (step.from_hold < 0) return null;
          const [x1, y1] = point(step.from_hold), [x2, y2] = point(step.to_hold);
          return <line key={index} x1={x1} y1={y1} x2={x2} y2={y2} stroke={step.limb.endsWith("foot") ? PART_COLOR.foot : PART_COLOR.hand} strokeWidth={stroke * 0.8} strokeDasharray={`${stroke * 2} ${stroke * 2}`} opacity={0.5} />;
        })}
        {map.holds.map((hold, index) => (
          <g key={hold.id}>
            <circle cx={hold.x * width} cy={hold.y * height} r={hold.radius * width} fill="rgba(0,0,0,.18)" stroke={ROLE_COLOR[hold.role]} strokeWidth={stroke} />
            <text x={hold.x * width} y={hold.y * height - hold.radius * width - stroke * 2} textAnchor="middle" fontSize={width / 34} fontWeight="700" fill="#fff" stroke="#000" strokeWidth={stroke / 2} paintOrder="stroke">{index + 1}</text>
          </g>
        ))}
        {pose && (
          <g data-testid="beta-stick">
            {TORSO.map((pair) => bone(pair, PART_COLOR.center, pair.join()))}
            {ARM.map((pair) => bone(pair, PART_COLOR.hand, pair.join()))}
            {LEG.map((pair) => bone(pair, PART_COLOR.foot, pair.join(), placed[`${pair[0].split("_")[0]}_foot`] < 0))}
            {head && <circle cx={head[0]} cy={head[1]} r={width / 55} fill={PART_COLOR.center} stroke="rgba(0,0,0,.75)" strokeWidth={stroke * 0.7} />}
            {Object.keys(LIMB_SHORT).map((limb) => {
              const p = at(limb);
              if (!p) return null;
              const active = moving?.limb === limb, color = limb.endsWith("foot") ? PART_COLOR.foot : PART_COLOR.hand, off = placed[limb] < 0;
              return (
                <g key={limb} opacity={off ? 0.6 : 1}>
                  <circle cx={p[0]} cy={p[1]} r={active ? width / 50 : width / 68} fill={color} stroke={active ? "#ffe14a" : "rgba(0,0,0,.8)"} strokeWidth={active ? stroke * 1.3 : stroke * 0.7} />
                  <text x={p[0] + (limb.startsWith("left") ? -1 : 1) * width / 26} y={p[1] + width / 90} textAnchor="middle" fontSize={width / 40} fontWeight="700" fill="#fff" stroke="#000" strokeWidth={stroke / 2} paintOrder="stroke">{LIMB_SHORT[limb]}</text>
                </g>
              );
            })}
          </g>
        )}
        {moving && moving.from_hold >= 0 && (() => {
          const [x1, y1] = point(moving.from_hold), [x2, y2] = point(moving.to_hold);
          return <g data-testid="beta-move"><line x1={x1} y1={y1} x2={x2} y2={y2} stroke="rgba(0,0,0,.8)" strokeWidth={stroke * 2.6} /><line x1={x1} y1={y1} x2={x2} y2={y2} stroke="#ffe14a" strokeWidth={stroke * 1.3} markerEnd="url(#move-head)" /></g>;
        })()}
      </svg>
    </div>
  );
}

function stepTags(step: BetaStep): string[] {
  const tags: string[] = [];
  if (step.match) tags.push(step.limb.endsWith("hand") ? "match hands" : "feet share the hold");
  if (step.crossed) tags.push("hands cross");
  if (step.high_foot) tags.push("high foot");
  if (step.tight) tags.push("near full reach");
  if (step.strenuous) tags.push("strenuous position");
  if (step.big_shift) tags.push("big body shift");
  if (step.on_volume) tags.push("on the volume");
  return tags;
}

/** One candidate: its summary, the playable sketch controls, and the list of moves. `length` writes a distance given in torso lengths. */
export function CandidateDetail({ candidate, position, onPosition, length, testid }: {
  candidate: BetaCandidate; position: number; onPosition: (next: number) => void; length: (torsoLengths: number) => string; testid: string;
}) {
  const [playing, setPlaying] = useState(false);
  const last = candidate.steps.length;
  useEffect(() => {
    if (!playing) return;
    if (position >= last) { setPlaying(false); return; }
    const timer = window.setTimeout(() => onPosition(position + 1), PLAY_MS);
    return () => window.clearTimeout(timer);
  }, [playing, position, last, onPosition]);
  useEffect(() => { setPlaying(false); }, [candidate.id]);
  const starts = Object.entries(candidate.start);
  const never = starts.filter(([limb, hold]) => hold < 0 && !candidate.steps.some((step) => step.limb === limb)).map(([limb]) => limb);
  const highFeet = candidate.high_foot_moves ?? 0, hard = candidate.strenuous_moves ?? 0, shifts = candidate.big_shifts ?? 0;
  const plural = (count: number, word: string) => `${count} ${word}${count === 1 ? "" : "s"}`;
  return (
    <div data-testid={`${testid}-detail`}>
      <p className="small-text">{candidate.move_count} moves. Longest single move {length(candidate.largest_move_L)}. {highFeet === 0 ? "No high feet." : `${highFeet} high foot placement${highFeet > 1 ? "s" : ""}.`} {candidate.tight_moves ? `${candidate.tight_moves} move${candidate.tight_moves > 1 ? "s" : ""} near full reach.` : "No move near full reach."} {hard || shifts ? `${[hard ? plural(hard, "strenuous position") : "", shifts ? plural(shifts, "big body shift") : ""].filter(Boolean).join(" and ")}, judged from the sketch.` : "No position the sketch rates as strenuous."} Ends with both hands on the finish.{candidate.tops_out ? " Ends at the top-out point: climb over from there." : ""}</p>
      <p className="legend small-text" data-testid={`${testid}-legend`}><span className="swatch" style={{ background: PART_COLOR.hand, marginLeft: 0 }} /> Hands (LH, RH) <span className="swatch" style={{ background: PART_COLOR.foot }} /> Feet (LF, RF) <span className="swatch" style={{ background: "#ffe14a" }} /> The move being shown</p>
      <div className="row tight" role="group" aria-label="Step through the sequence">
        <button className="button small" data-testid={`${testid}-prev`} disabled={position === 0} onClick={() => { setPlaying(false); onPosition(position - 1); }}>← Back</button>
        <button className="button small primary" data-testid={`${testid}-play`} aria-pressed={playing} onClick={() => { if (!playing && position >= last) onPosition(0); setPlaying(!playing); }}>{playing ? "Pause" : position >= last ? "Play again" : "Play"}</button>
        <button className="button small" data-testid={`${testid}-next`} disabled={position >= last} onClick={() => { setPlaying(false); onPosition(position + 1); }}>Next →</button>
        <span className="muted small-text num" aria-live="polite">{position === 0 ? "Start" : `Move ${position} of ${last}`}</span>
      </div>
      <ol className="phase-list" start={0} data-testid={`${testid}-steps`}>
        <li><button className={`link ${position === 0 ? "strong" : ""}`} aria-current={position === 0 ? "step" : undefined} onClick={() => { setPlaying(false); onPosition(0); }}>Start</button>{" "}
          <span className="muted small-text">{starts.map(([limb, hold]) => `${LIMB_SHORT[limb]} ${hold < 0 ? (never.includes(limb) ? "off the marks" : "on the ground") : holdName(hold)}`).join(", ")}</span></li>
        {candidate.steps.map((item, index) => {
          const tags = stepTags(item);
          return (
            <li key={index}><button className={`link ${index + 1 === position ? "strong" : ""}`} aria-current={index + 1 === position ? "step" : undefined} onClick={() => { setPlaying(false); onPosition(index + 1); }}>
              <span className="limb-dot" style={{ background: item.limb.endsWith("foot") ? PART_COLOR.foot : PART_COLOR.hand }} />{LIMB_NAME[item.limb]} to {holdName(item.to_hold)}</button>{" "}
              <span className="muted small-text">{item.from_hold < 0 ? "first placement" : length(item.distance_L)}{tags.length ? `, ${tags.join(", ")}` : ""}</span></li>
          );
        })}
      </ol>
      {never.length > 0 && <p className="muted small-text">{never.map((limb) => LIMB_NAME[limb]).join(" and ")} never goes to a marked hold in this sequence. On the wall it would smear, flag, or use a hold you did not mark.</p>}
    </div>
  );
}
