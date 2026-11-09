import { MouseEvent, useCallback, useEffect, useRef, useState } from "react";
import { api, Attempt, clock, Hold, holdApi, HoldMap } from "./api";

const DEFAULT_RADIUS = 0.035;
const NUDGE = 0.005;

function toBody(hold: Hold) {
  return { x: hold.x, y: hold.y, radius: hold.radius, route: hold.route, hold_type: hold.hold_type, role: hold.role, use: hold.use };
}

export function HoldEditor({ attemptId }: { attemptId: string }) {
  const [attempt, setAttempt] = useState<Attempt | null>(null);
  const [maps, setMaps] = useState<HoldMap[]>([]);
  const [active, setActive] = useState<HoldMap | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [frameSeconds, setFrameSeconds] = useState("0");
  const [name, setName] = useState("Route 1");
  const [route, setRoute] = useState("");
  const [error, setError] = useState("");
  const svg = useRef<SVGSVGElement>(null);

  const load = useCallback(async () => {
    try { setAttempt(await api.getAttempt(attemptId)); setMaps(await holdApi.list(attemptId)); }
    catch (e) { setError((e as Error).message); }
  }, [attemptId]);
  useEffect(() => { void load(); }, [load]);

  const run = async (action: () => Promise<HoldMap>) => {
    setError("");
    try { const next = await action(); setActive(next); return next; }
    catch (e) { setError((e as Error).message); return null; }
  };
  const previewMs = Math.round(parseFloat(frameSeconds || "0") * 1000);
  const hold = active?.holds.find((h) => h.id === selected) ?? null;

  const addAt = (event: MouseEvent<SVGSVGElement>) => {
    const surface = svg.current;
    if (!surface || !active || event.target !== surface) return;
    // Screen-to-viewBox mapping accounts for letterboxing; the viewBox is canonical pixels.
    const point = new DOMPoint(event.clientX, event.clientY).matrixTransform(surface.getScreenCTM()!.inverse());
    const x = point.x / active.width, y = point.y / active.height;
    if (x < 0 || x > 1 || y < 0 || y > 1) return; // click on the letterbox band
    void run(() => holdApi.addHold(active.id, { x, y, radius: DEFAULT_RADIUS, route, hold_type: "", role: "", use: "" })).then((next) => {
      if (next) setSelected(next.holds[next.holds.length - 1].id);
    });
  };
  const update = (changes: Partial<Hold>) => {
    if (active && hold) void run(() => holdApi.editHold(active.id, hold.id, { ...toBody(hold), ...changes }));
  };
  const onKey = (event: React.KeyboardEvent, target: Hold) => {
    if (!active) return;
    const moves: Record<string, [number, number]> = { ArrowLeft: [-NUDGE, 0], ArrowRight: [NUDGE, 0], ArrowUp: [0, -NUDGE], ArrowDown: [0, NUDGE] };
    if (moves[event.key]) {
      event.preventDefault();
      const [dx, dy] = moves[event.key];
      void run(() => holdApi.editHold(active.id, target.id, { ...toBody(target), x: Math.min(1, Math.max(0, target.x + dx)), y: Math.min(1, Math.max(0, target.y + dy)) }));
    } else if (event.key === "Delete" || event.key === "Backspace") {
      event.preventDefault();
      setSelected(null);
      void run(() => holdApi.removeHold(active.id, target.id));
    }
  };

  if (!attempt) return <div className="page">{error ? <p className="error" role="alert">{error}</p> : <p className="muted">Loading…</p>}</div>;
  const width = active?.width ?? attempt.width ?? 1, height = active?.height ?? attempt.height ?? 1;
  const image = active ? active.frame_url : `/api/attempts/${attemptId}/frame?ms=${Math.min(previewMs, (attempt.duration_ms ?? 1) - 1)}`;

  return (
    <div className="page">
      <div className="page-head"><a href={`#/attempt/${attemptId}`}>← Back</a><h1>Mark holds: {attempt.title}</h1></div>
      <p className="blind-note" role="note">
        Holds are marked by you on one still frame. This does not detect holds or show contact, and the marks are shown only on that frame. Using them across a video requires a fixed camera.
      </p>
      {error && <p className="error" role="alert">{error}</p>}
      <div className="hold-layout">
        <section className="card">
          <div className="hold-stage" data-testid="hold-stage">
            <img src={image} alt={`Reference frame at ${clock(active?.reference_frame_ms ?? previewMs)}`} data-testid="hold-image" />
            {active && (
              <svg ref={svg} viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="xMidYMid meet" data-testid="hold-svg" onClick={addAt}>
                {active.holds.map((item, index) => (
                  <g key={item.id}>
                  <circle cx={item.x * width} cy={item.y * height} r={item.radius * width}
                    fill={item.id === selected ? "rgba(31,111,235,.35)" : "rgba(255,200,0,.25)"} stroke={item.id === selected ? "#1f6feb" : item.role === "start" ? "#2fbf71" : item.role === "finish" ? "#e0245e" : "#ffc800"} strokeWidth={Math.max(1.5, width / 400)}
                    tabIndex={0} role="button" aria-label={`Hold ${item.route || "no route"}, position ${Math.round(item.x * 100)}%, ${Math.round(item.y * 100)}%`} data-testid="hold-circle"
                    onClick={(e) => { e.stopPropagation(); setSelected(item.id); }} onFocus={() => setSelected(item.id)} onKeyDown={(e) => onKey(e, item)} />
                  <text x={item.x * width} y={item.y * height} textAnchor="middle" dominantBaseline="middle" fontSize={width / 36} fontWeight="700" fill="#fff" stroke="#000" strokeWidth={Math.max(1, width / 700)} paintOrder="stroke" pointerEvents="none">{index + 1}</text>
                  </g>
                ))}
              </svg>
            )}
          </div>
          {active
            ? <p className="muted small-text">Click the picture to add a hold. With a hold focused (Tab), arrow keys move it and Delete removes it. Frame {clock(active.reference_frame_ms)}.</p>
            : <p className="muted small-text">Choose the frame, then create a hold map.</p>}
        </section>
        <section className="card">
          {!active ? (
            <>
              <h2>Hold maps</h2>
              {maps.length > 0 && (
                <ul className="interval-list">
                  {maps.map((item) => (
                    <li key={item.id}><span>{item.name} ({item.holds.length} holds, {clock(item.reference_frame_ms)})</span>
                      <button className="button small" aria-label={`Open map ${item.name}`} onClick={() => setActive(item)}>Open</button></li>
                  ))}
                </ul>
              )}
              <h3>New map</h3>
              <label>Name<input value={name} data-testid="map-name" onChange={(e) => setName(e.target.value)} /></label>
              <label>Reference frame (s)<input type="number" min="0" step="0.1" value={frameSeconds} data-testid="map-frame" onChange={(e) => setFrameSeconds(e.target.value)} /></label>
              <p className="muted small-text">Pick a frame where the holds are unobstructed.</p>
              <button className="button primary" data-testid="create-map" onClick={() => void run(() => holdApi.create(attemptId, { name, reference_frame_ms: previewMs }))}>Create map</button>
            </>
          ) : (
            <>
              <h2>{active.name}</h2>
              <label>Route for new holds<input value={route} data-testid="route-input" onChange={(e) => setRoute(e.target.value)} /></label>
              {hold ? (
                <div data-testid="hold-details">
                  <h3>Hold {active.holds.findIndex((h) => h.id === hold.id) + 1}</h3>
                  <label>Route<input value={hold.route} onChange={(e) => update({ route: e.target.value })} /></label>
                  <label>Role on this problem
                    <select value={hold.role} data-testid="hold-role" onChange={(e) => update({ role: e.target.value as Hold["role"] })}>
                      <option value="">Middle of the route</option><option value="start">Start</option><option value="finish">Finish</option>
                    </select>
                  </label>
                  <label>Used by
                    <select value={hold.use} data-testid="hold-use" onChange={(e) => update({ use: e.target.value as Hold["use"] })}>
                      <option value="">Not set</option><option value="hand">Hands</option><option value="foot">Feet</option><option value="both">Hands and feet</option>
                    </select>
                  </label>
                  <label>Type (optional, your own label)<input value={hold.hold_type} onChange={(e) => update({ hold_type: e.target.value })} /></label>
                  <label>Radius<input type="range" min="0.01" max="0.15" step="0.005" value={hold.radius} onChange={(e) => update({ radius: parseFloat(e.target.value) })} /></label>
                  <button className="button small danger" onClick={() => { setSelected(null); void run(() => holdApi.removeHold(active.id, hold.id)); }}>Delete hold</button>
                </div>
              ) : <p className="muted">Click a hold to edit it.</p>}
              <h3>{active.holds.length} holds</h3>
              <div className="row tight">
                <a className="button small" href={`/api/hold-maps/${active.id}/export`} download>Export JSON</a>
                <button className="button small" onClick={() => { setActive(null); setSelected(null); void load(); }}>All maps</button>
                <button className="button small danger" onClick={async () => { if (window.confirm("Delete this hold map?")) { await holdApi.remove(active.id); setActive(null); void load(); } }}>Delete map</button>
              </div>
            </>
          )}
        </section>
      </div>
    </div>
  );
}
