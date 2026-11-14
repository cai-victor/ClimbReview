import { useMemo, useState } from "react";
import { ClimbEvent, clock, Limb, LimbSeries, Movement } from "./api";

export const LIMB_LABEL: Record<Limb, string> = { left_wrist: "Left wrist", right_wrist: "Right wrist", left_foot: "Left foot", right_foot: "Right foot" };
const SERIES_COLOR: Record<Limb, string> = { left_wrist: "#c96a0a", right_wrist: "#0e7fb8", left_foot: "#c96a0a", right_foot: "#0e7fb8" };
const WIDTH = 1000, ROW = 58, PLOT_TOP = 6, PLOT_BOTTOM = 8;
type Ready = Extract<Movement, { available: true }>;

export const limbOf = (event: ClimbEvent): Limb | null =>
  event.type === "low_movement" ? null : (`${event.hand}_${event.type === "wrist_motion" ? "wrist" : "foot"}` as Limb);
export const isUncertain = (event: ClimbEvent) =>
  (event.evidence.foot_support as { anchor_state?: string } | undefined)?.anchor_state === "uncertain";

/** One SVG path per continuous tracked run. A line never crosses a tracking gap. */
export function runPaths(times: number[], values: (number | null)[], runs: (number | null)[], x: (t: number) => number, y: (v: number) => number): string[] {
  const paths: string[] = [];
  let current = "", lastRun: number | null = null;
  times.forEach((time, index) => {
    const value = values[index], run = runs[index];
    if (value === null || run === null) {
      if (current) paths.push(current);
      current = "";
      lastRun = null;
      return;
    }
    if (run !== lastRun) { if (current) paths.push(current); current = `M${x(time).toFixed(1)} ${y(value).toFixed(1)}`; lastRun = run; }
    else current += `L${x(time).toFixed(1)} ${y(value).toFixed(1)}`;
  });
  if (current) paths.push(current);
  return paths;
}

export function untracked(times: number[], series: LimbSeries, x: (t: number) => number): { x: number; w: number }[] {
  const bands: { x: number; w: number }[] = [];
  let begin: number | null = null;
  for (let i = 0; i + 1 < times.length; i += 1) {
    // Valid endpoint landmarks do not make a blocked interval observable.
    const missing = series.x[i] === null || series.x[i + 1] === null
      || series.speed_L_per_s[i] === null || series.speed_L_per_s[i + 1] === null
      || series.run[i] === null || series.run[i + 1] === null || series.run[i] !== series.run[i + 1];
    if (missing && begin === null) begin = times[i];
    if (!missing && begin !== null) { bands.push({ x: x(begin), w: x(times[i]) - x(begin) }); begin = null; }
  }
  if (begin !== null) bands.push({ x: x(begin), w: x(times[times.length - 1]) - x(begin) });
  return bands;
}

/** Small multiples on a shared time and speed scale, so limbs can be compared without a legend. */
export function MovementChart({ movement, events, limbs, bounds, time, selected, onSeek }: {
  movement: Ready; events: ClimbEvent[]; limbs: Limb[]; bounds: { start: number; end: number }; time: number; selected: string | null; onSeek: (ms: number) => void;
}) {
  const [hover, setHover] = useState<{ limb: Limb; index: number; px: number; py: number } | null>(null);
  const span = bounds.end - bounds.start;
  const x = (t: number) => ((t - bounds.start) / span) * WIDTH;
  const peak = useMemo(() => {
    const all = limbs.flatMap((limb) => movement.limbs[limb].speed_L_per_s.filter((v): v is number => v !== null)).sort((a, b) => a - b);
    return Math.max(1, all.length ? all[Math.floor(all.length * 0.995)] : 1);
  }, [movement, limbs]);
  const nearestIndex = (ms: number) => {
    let best = 0;
    movement.t.forEach((t, i) => { if (Math.abs(t - ms) < Math.abs(movement.t[best] - ms)) best = i; });
    return best;
  };
  const height = ROW * limbs.length + 4;
  const chartHeight = Math.max(150, limbs.length * 62);
  const pick = (event: React.MouseEvent<SVGSVGElement>) => {
    const box = event.currentTarget.getBoundingClientRect();
    return { ms: bounds.start + ((event.clientX - box.left) / box.width) * span, rowIndex: Math.floor(((event.clientY - box.top) / box.height) * height / ROW), px: event.clientX - box.left, py: event.clientY - box.top };
  };
  const value = hover ? movement.limbs[hover.limb].speed_L_per_s[hover.index] : null;

  return (
    <div className="movement-chart">
      <svg viewBox={`0 0 ${WIDTH} ${height}`} role="img" data-testid="movement-chart" preserveAspectRatio="none" style={{ height: `${chartHeight}px` }}
        aria-label={`Speed over time for ${limbs.map((l) => LIMB_LABEL[l]).join(", ")}. Hatched areas could not be analyzed.`}
        onMouseMove={(e) => { const p = pick(e); const limb = limbs[Math.min(limbs.length - 1, Math.max(0, p.rowIndex))]; setHover({ limb, index: nearestIndex(p.ms), px: p.px, py: p.py }); }}
        onMouseLeave={() => setHover(null)} onClick={(e) => onSeek(Math.round(pick(e).ms))}>
        <defs><pattern id="hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="3" height="6" fill="#ddd6ec" /></pattern></defs>
        {limbs.map((limb, row) => {
          const top = row * ROW + PLOT_TOP, plot = ROW - PLOT_TOP - PLOT_BOTTOM;
          const y = (v: number) => top + plot - (Math.min(v, peak) / peak) * plot;
          const series = movement.limbs[limb];
          return (
            <g key={limb}>
              <line x1="0" x2={WIDTH} y1={top + plot} y2={top + plot} className="chart-base" />
              {untracked(movement.t, series, x).map((band) => <rect key={band.x} x={band.x} y={top} width={Math.max(band.w, 1)} height={plot} fill="url(#hatch)" />)}
              {events.filter((e) => limbOf(e) === limb).map((e) => (
                <rect key={e.id} x={x(e.start_ms)} y={top} width={Math.max(x(e.end_ms) - x(e.start_ms), 2)} height={plot}
                  className={`chart-event ${isUncertain(e) ? "uncertain" : ""} ${selected === e.id ? "selected" : ""}`} />
              ))}
              {runPaths(movement.t, series.speed_L_per_s, series.run, x, y).map((d) => <path key={d} d={d} fill="none" stroke={SERIES_COLOR[limb]} strokeWidth="2" vectorEffect="non-scaling-stroke" strokeLinejoin="round" />)}
            </g>
          );
        })}
        <line x1={x(time)} x2={x(time)} y1="0" y2={height} className="chart-playhead" vectorEffect="non-scaling-stroke" />
      </svg>
      {limbs.map((limb, row) => <span key={limb} className="chart-row-label" style={{ top: `${(row * ROW / height) * chartHeight}px` }}>{LIMB_LABEL[limb]}</span>)}
      <div className="chart-time"><span>{clock(bounds.start)}</span><span>{clock(bounds.end)}</span></div>
      {hover && (
        <div className="chart-tip" style={{ left: hover.px, top: hover.py }}>
          {LIMB_LABEL[hover.limb]} at {clock(movement.t[hover.index])}: {value === null ? "not analyzable" : `${value.toFixed(2)} torso lengths/s`}
        </div>
      )}
      <p className="legend">Line height is image speed, on the same scale for every row (top is {peak.toFixed(1)} torso lengths per second). <span className="swatch event-swatch" /> Detected episode <span className="swatch hatch-swatch" /> Not analyzable. Click anywhere to jump to that moment.</p>
    </div>
  );
}

/** Distance of the tracked point from where the episode began, with one second of context. */
export function EventChart({ movement, event, time, onSeek }: { movement: Ready; event: ClimbEvent; time: number; onSeek: (ms: number) => void }) {
  const limb = limbOf(event);
  if (!limb || !movement.L_px) return null;
  const length = movement.L_px;
  const series = movement.limbs[limb];
  const from = event.start_ms - 1000, to = event.end_ms + 1000;
  const indices = movement.t.map((_, i) => i).filter((i) => movement.t[i] >= from && movement.t[i] <= to);
  const startIndex = indices.find((i) => movement.t[i] >= event.start_ms && series.x[i] !== null);
  if (startIndex === undefined) return null;
  const originRun = series.run[startIndex];
  if (originRun === null) return null;
  const x0 = series.x[startIndex]! * movement.width, y0 = series.y[startIndex]! * movement.height;
  const distance = indices.map((i) => series.x[i] === null || series.run[i] !== originRun ? null : Math.hypot(series.x[i]! * movement.width - x0, series.y[i]! * movement.height - y0) / length);
  const top = Math.max(0.3, ...distance.filter((v): v is number => v !== null));
  const W = 360, H = 104, left = 34, bottom = 88, plotTop = 8;
  const px = (t: number) => left + ((t - from) / (to - from)) * (W - left - 6);
  const py = (v: number) => bottom - (v / top) * (bottom - plotTop);
  const times = indices.map((i) => movement.t[i]);
  const runs = indices.map((i) => series.run[i]);
  const contextSeries = { ...series, x: distance, y: distance, speed_L_per_s: distance, run: runs };
  return (
    <svg className="event-chart" viewBox={`0 0 ${W} ${H}`} role="img" data-testid="event-chart"
      aria-label={`${LIMB_LABEL[limb]} distance from its starting point, reaching ${top.toFixed(2)} torso lengths.`}
      onClick={(e) => { const box = e.currentTarget.getBoundingClientRect(); const fraction = (((e.clientX - box.left) / box.width) * W - left) / (W - left - 6); onSeek(Math.round(from + Math.min(1, Math.max(0, fraction)) * (to - from))); }}>
      <defs><pattern id="event-chart-hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="3" height="6" fill="#ddd6ec" /></pattern></defs>
      {untracked(times, contextSeries, px).map((band) => <rect key={band.x} className="event-chart-gap" x={band.x} y={plotTop} width={Math.max(band.w, 1)} height={bottom - plotTop} fill="url(#event-chart-hatch)" />)}
      <rect x={px(event.start_ms)} y={plotTop} width={px(event.end_ms) - px(event.start_ms)} height={bottom - plotTop} className="chart-event" />
      <line x1={left} x2={W - 6} y1={bottom} y2={bottom} className="chart-base" />
      {runPaths(times, distance, runs, px, py).map((d) => <path key={d} d={d} fill="none" stroke={SERIES_COLOR[limb]} strokeWidth="2" strokeLinejoin="round" />)}
      {time >= from && time <= to && <line x1={px(time)} x2={px(time)} y1={plotTop} y2={bottom} className="chart-playhead" />}
      <text x={left - 4} y={plotTop + 9} textAnchor="end" className="chart-axis">{top.toFixed(1)}</text>
      <text x={left - 4} y={bottom} textAnchor="end" className="chart-axis">0</text>
      <text x={px(event.start_ms)} y={H - 3} textAnchor="middle" className="chart-axis">{clock(event.start_ms)}</text>
      <text x={px(event.end_ms)} y={H - 3} textAnchor="middle" className="chart-axis">{clock(event.end_ms)}</text>
    </svg>
  );
}
