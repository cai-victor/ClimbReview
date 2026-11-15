import { useState } from "react";
import { clock, Story } from "./api";

type Ready = Extract<Story, { available: true }>;
const W = 1000, H = 150, TOP = 10, BOTTOM = 128;

/** Hip height in the picture over time, with the places the climber stayed put. A description of where time went, not a score. */
export function ClimbProfile({ story, bounds, time, onSeek }: { story: Ready; bounds: { start: number; end: number }; time: number; onSeek: (ms: number) => void }) {
  const [hover, setHover] = useState<{ index: number; px: number } | null>(null);
  const span = Math.max(1, bounds.end - bounds.start);
  const peak = Math.max(1, ...story.profile.map((p) => p.h));
  const x = (ms: number) => ((ms - bounds.start) / span) * W;
  const y = (h: number) => BOTTOM - (Math.max(0, h) / peak) * (BOTTOM - TOP);
  // One path per continuous run of tracking: the line never crosses a gap.
  const paths: string[] = [];
  let current = "", run = -1;
  for (const point of story.profile) {
    if (point.run !== run) { if (current) paths.push(current); current = `M${x(point.t).toFixed(1)} ${y(point.h).toFixed(1)}`; run = point.run; }
    else current += `L${x(point.t).toFixed(1)} ${y(point.h).toFixed(1)}`;
  }
  if (current) paths.push(current);
  const pick = (event: React.MouseEvent<SVGSVGElement>) => {
    const box = event.currentTarget.getBoundingClientRect();
    return { ms: bounds.start + ((event.clientX - box.left) / box.width) * span, px: event.clientX - box.left };
  };
  const nearest = (ms: number) => story.profile.reduce((best, point, index) => (Math.abs(point.t - ms) < Math.abs(story.profile[best].t - ms) ? index : best), 0);
  const stats = story.stats;
  const off = story.phases.filter((phase) => phase.kind === "off_wall" || phase.kind === "before_start");
  const point = hover ? story.profile[hover.index] : null;
  return (
    <section className="card" data-testid="climb-profile" aria-label="Your climb">
      <h2>Your climb</h2>
      <p data-testid="story-headline">{story.headline}</p>
      <div className="stat-row">
        <div className="stat"><span className="stat-value">{(stats.on_wall_ms / 1000).toFixed(0)}s</span><span className="stat-label">on the wall</span></div>
        <div className="stat"><span className="stat-value">{(stats.moving_ms / 1000).toFixed(0)}s</span><span className="stat-label">moving</span></div>
        <div className="stat"><span className="stat-value">{(stats.stopped_ms / 1000).toFixed(0)}s</span><span className="stat-label">staying put, in {stats.stops} place{stats.stops === 1 ? "" : "s"}</span></div>
        <div className="stat"><span className="stat-value">{stats.height_gained_L.toFixed(1)}</span><span className="stat-label">torso lengths gained, high point at <button className="link num" onClick={() => onSeek(stats.high_point_ms)}>{clock(stats.high_point_ms)}</button></span></div>
      </div>
      <div className="movement-chart">
        <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" style={{ height: 150 }} role="img" data-testid="climb-profile-chart"
          aria-label={`Hip height over time. ${story.headline} ${story.stops.map((s) => `Stayed put ${clock(s.start_ms)} to ${clock(s.end_ms)}.`).join(" ")}`}
          onMouseMove={(e) => { const p = pick(e); setHover({ index: nearest(p.ms), px: p.px }); }} onMouseLeave={() => setHover(null)} onClick={(e) => onSeek(Math.round(pick(e).ms))}>
          <defs><pattern id="story-hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="3" height="6" fill="#ddd6ec" /></pattern></defs>
          {story.stops.map((stop) => <rect key={stop.start_ms} className="chart-event" data-testid="profile-stop" x={x(stop.start_ms)} y={TOP} width={Math.max(2, x(stop.end_ms) - x(stop.start_ms))} height={BOTTOM - TOP} />)}
          {off.map((phase) => <rect key={phase.kind} x={x(phase.start_ms)} y={TOP} width={Math.max(2, x(phase.end_ms) - x(phase.start_ms))} height={BOTTOM - TOP} fill="url(#story-hatch)" data-testid="profile-off-wall" />)}
          <line x1="0" x2={W} y1={BOTTOM} y2={BOTTOM} className="chart-base" />
          {paths.map((d) => <path key={d} d={d} fill="none" stroke="var(--ink-2)" strokeWidth="2" vectorEffect="non-scaling-stroke" strokeLinejoin="round" />)}
          {point && <line x1={x(point.t)} x2={x(point.t)} y1={TOP} y2={BOTTOM} stroke="var(--muted)" strokeWidth="1" vectorEffect="non-scaling-stroke" strokeDasharray="3 3" />}
          <line x1={x(time)} x2={x(time)} y1="0" y2={BOTTOM} className="chart-playhead" vectorEffect="non-scaling-stroke" />
        </svg>
        <span className="chart-row-label" style={{ top: 0 }}>Hip height, up to {peak.toFixed(1)} torso lengths</span>
        <div className="chart-time"><span>{clock(bounds.start)}</span><span>{clock(bounds.end)}</span></div>
        {point && hover && <div className="chart-tip" style={{ left: hover.px, top: 40 }}>{clock(point.t)}: {point.h.toFixed(1)} torso lengths up</div>}
      </div>
      <p className="legend"><span className="swatch event-swatch" style={{ marginLeft: 0 }} /> Stayed in one area for 3s or more{off.length > 0 && <><span className="swatch hatch-swatch" /> Not counted as climbing</>}. Click the chart to jump there.</p>
      {story.stops.length > 0 && (
        <details>
          <summary>Where you stayed put ({story.stops.length})</summary>
          <ul className="plain-list small-text">
            {story.stops.map((stop) => {
              const feet = stop.counts.left_foot + stop.counts.right_foot, hands = stop.counts.left_wrist + stop.counts.right_wrist;
              return <li key={stop.start_ms}><button className="link num" onClick={() => onSeek(stop.start_ms)}>{clock(stop.start_ms)}</button> for {(stop.duration_ms / 1000).toFixed(0)}s, {stop.height_L.toFixed(1)} torso lengths up. Tracked movements: {feet} foot, {hands} hand.</li>;
            })}
          </ul>
        </details>
      )}
      <p className="muted small-text">{story.note}</p>
    </section>
  );
}
