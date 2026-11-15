import { MouseEvent, PointerEvent as ReactPointerEvent, useCallback, useEffect, useRef, useState } from "react";
import { api, Attempt, clock, Hold, holdApi, HoldMap, HoldSuggestion, WallGeometry, WallInfo } from "./api";
import { PerspectiveNote } from "./Performance";

type Mode = "add" | "suggest" | "scale";
type Drag = { id: string; kind: "move" | "resize"; x: number; y: number; radius: number; moved: boolean };

const DEFAULT_RADIUS = 0.035;
const NUDGE = 0.005;
const MIN_RADIUS = 0.006, MAX_RADIUS = 0.2;
const ZOOMS = [1, 1.5, 2, 3, 4, 6];
export const TOP_OUT = "top-out";
const CM_PER_INCH = 2.54;
const ROLE_COLOR = { start: "#2fbf71", finish: "#e0245e", "": "#ffc800" } as const;
const PULL_ARROW: Record<string, [number, number]> = { down: [0, 1], left: [-1, 0], right: [1, 0], up: [0, -1] };
const PULLS: { value: Hold["pull"]; label: string; title: string }[] = [
  { value: "", label: "Not set", title: "The planner lets the body be anywhere within reach" },
  { value: "down", label: "↓ Down", title: "Jugs, crimps, and most holds: you hang below it" },
  { value: "left", label: "← Left", title: "Sidepull: you pull it to the left, with your body to the left" },
  { value: "right", label: "→ Right", title: "Sidepull: you pull it to the right, with your body to the right" },
  { value: "up", label: "↑ Up", title: "Undercling: you pull upward, with your body high beside it" },
];

function toBody(hold: Hold) {
  return { x: hold.x, y: hold.y, radius: hold.radius, route: hold.route, hold_type: hold.hold_type, role: hold.role, use: hold.use, pull: hold.pull ?? "" };
}
const isTopOut = (hold: Hold) => hold.role === "finish" && hold.hold_type.trim().toLowerCase() === TOP_OUT;
const clamp = (value: number, low: number, high: number) => Math.min(high, Math.max(low, value));

const wallKey = (mapId: string) => `climbreview.clearWall.${mapId}`;
const wallChoice = (mapId: string) => { try { return window.localStorage.getItem(wallKey(mapId)) === "1"; } catch { return false; } };
const rememberWall = (mapId: string, on: boolean) => { try { if (on) window.localStorage.setItem(wallKey(mapId), "1"); else window.localStorage.removeItem(wallKey(mapId)); } catch { /* the choice is a convenience only */ } };

export function HoldEditor({ attemptId }: { attemptId: string }) {
  const [attempt, setAttempt] = useState<Attempt | null>(null);
  const [maps, setMaps] = useState<HoldMap[]>([]);
  const [active, setActive] = useState<HoldMap | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [frameSeconds, setFrameSeconds] = useState("0");
  const [name, setName] = useState("Route 1");
  const [route, setRoute] = useState("");
  const [newUse, setNewUse] = useState<Hold["use"]>("");
  const [error, setError] = useState("");
  const svg = useRef<SVGSVGElement>(null);
  const stage = useRef<HTMLDivElement>(null);
  const picker = useRef<HTMLVideoElement>(null);
  const [mode, setMode] = useState<Mode>("add");
  const [tolerance, setTolerance] = useState("normal");
  const [suggestions, setSuggestions] = useState<HoldSuggestion[]>([]);
  const [suggestNote, setSuggestNote] = useState("");
  const [scalePoints, setScalePoints] = useState<{ x: number; y: number }[]>([]);
  const [scaleValue, setScaleValue] = useState("");
  const [scaleUnit, setScaleUnit] = useState<"cm" | "in">("cm");
  const [busy, setBusy] = useState(false);
  const [wall, setWall] = useState<WallInfo | null>(null);
  const [showWall, setShowWall] = useState(false);
  const [wallState, setWallState] = useState<"idle" | "loading" | "ready" | "failed">("idle");
  const [geometry, setGeometry] = useState<WallGeometry | null>(null);
  const [showGrid, setShowGrid] = useState(false);
  const [saveState, setSaveState] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [added, setAdded] = useState<string[]>([]);     // holds added in this visit, newest last, for undo
  const [zoom, setZoom] = useState(1);
  const [drag, setDrag] = useState<Drag | null>(null);
  const dragRef = useRef<Drag | null>(null);
  const justDragged = useRef(false);
  const activeId = active?.id;
  const wanted = useRef<string | null>(null);
  const buildWall = async (mapId: string) => {
    wanted.current = mapId; setWallState("loading");
    try {
      const info = await holdApi.wallInfo(mapId);
      if (wanted.current !== mapId) return;                 // another map was opened while this one was building
      setWall(info); setWallState("ready"); setShowWall(info.combined); rememberWall(mapId, info.combined);
    } catch { if (wanted.current === mapId) setWallState("failed"); }   // the single frame stays usable
  };
  useEffect(() => {
    setWall(null); setGeometry(null); setShowWall(false); setWallState("idle");
    // The combined picture is built only when asked for. A map where it was chosen before loads it again, which is quick once built.
    if (activeId && wallChoice(activeId)) void buildWall(activeId);
  }, [activeId]);

  const load = useCallback(async () => {
    try { setAttempt(await api.getAttempt(attemptId)); setMaps(await holdApi.list(attemptId)); }
    catch (e) { setError((e as Error).message); }
  }, [attemptId]);
  useEffect(() => { void load(); }, [load]);

  const run = async (action: () => Promise<HoldMap>) => {
    setError(""); setSaveState("saving");
    try { const next = await action(); setActive(next); setSaveState("saved"); return next; }
    catch (e) { setError(`Not saved: ${(e as Error).message}`); setSaveState("error"); return null; }
  };
  const previewMs = Math.round(parseFloat(frameSeconds || "0") * 1000);
  const hold = active?.holds.find((h) => h.id === selected) ?? null;

  /** Keeps the middle of the view in place when the zoom changes. */
  const zoomTo = (next: number) => {
    const box = stage.current;
    const cx = box ? (box.scrollLeft + box.clientWidth / 2) / (box.clientWidth * zoom) : 0.5;
    const cy = box ? (box.scrollTop + box.clientHeight / 2) / (box.clientHeight * zoom) : 0.5;
    setZoom(next);
    requestAnimationFrame(() => {
      if (!box) return;
      box.scrollLeft = cx * box.clientWidth * next - box.clientWidth / 2;
      box.scrollTop = cy * box.clientHeight * next - box.clientHeight / 2;
    });
  };
  const zoomStep = (direction: 1 | -1) => zoomTo(ZOOMS[clamp(ZOOMS.indexOf(zoom) + direction, 0, ZOOMS.length - 1)]);

  // Screen-to-viewBox mapping accounts for letterboxing and zoom; the viewBox is canonical pixels.
  const pointAt = (clientX: number, clientY: number) => {
    const surface = svg.current;
    if (!surface || !active) return null;
    const point = new DOMPoint(clientX, clientY).matrixTransform(surface.getScreenCTM()!.inverse());
    return { x: point.x / active.width, y: point.y / active.height };
  };

  const addAt = (event: MouseEvent<SVGSVGElement>) => {
    const surface = svg.current;
    if (!surface || !active || event.target !== surface) return;
    const at = pointAt(event.clientX, event.clientY);
    if (!at || at.x < 0 || at.x > 1 || at.y < 0 || at.y > 1) return; // click on the letterbox band
    const { x, y } = at;
    if (mode === "suggest") {
      setError(""); setBusy(true);
      holdApi.suggest(active.id, { x, y, tolerance })
        .then((result) => { setSuggestions(result.suggestions); setSuggestNote(`${result.suggestions.length} suggestions in the tapped color. ${result.image.detail} ${result.note}`); })
        .catch((e) => { setSuggestions([]); setSuggestNote(""); setError((e as Error).message); })
        .finally(() => setBusy(false));
      return;
    }
    if (mode === "scale") { setScalePoints((points) => (points.length >= 2 ? [{ x, y }] : [...points, { x, y }])); return; }
    void run(() => holdApi.addHold(active.id, { x, y, radius: DEFAULT_RADIUS / Math.sqrt(zoom), route, hold_type: "", role: "", use: newUse, pull: "" })).then((next) => {
      if (next) { const id = next.holds[next.holds.length - 1].id; setSelected(id); setAdded((list) => [...list, id]); }
    });
  };
  const accept = async (items: HoldSuggestion[]) => {
    if (!active) return;
    setBusy(true);
    let latest: HoldMap | null = null;
    for (const item of items) {
      latest = await run(() => holdApi.addHold(active.id, { x: item.x, y: item.y, radius: item.radius, route, hold_type: "", role: "", use: newUse, pull: "" }));
      if (latest) { const id = latest.holds[latest.holds.length - 1].id; setAdded((list) => [...list, id]); }
    }
    if (latest) setSuggestions((list) => list.filter((s) => !items.includes(s)));
    setBusy(false);
  };
  const scaleCm = parseFloat(scaleValue) * (scaleUnit === "in" ? CM_PER_INCH : 1);
  const saveScale = async () => {
    if (!active || scalePoints.length !== 2) return;
    setError("");
    try {
      await holdApi.putScale(active.id, { x1: scalePoints[0].x, y1: scalePoints[0].y, x2: scalePoints[1].x, y2: scalePoints[1].y, cm: Math.round(scaleCm * 10) / 10 });
      setActive(await holdApi.get(active.id)); setScalePoints([]); setMode("add");
    } catch (e) { setError((e as Error).message); }
  };
  const undo = () => {
    const id = [...added].reverse().find((item) => active?.holds.some((h) => h.id === item));
    if (!active || !id) return;
    setAdded((list) => list.filter((item) => item !== id));
    if (selected === id) setSelected(null);
    void run(() => holdApi.removeHold(active.id, id));
  };
  const canUndo = added.some((item) => active?.holds.some((h) => h.id === item));
  const change = (target: Hold, changes: Partial<Hold>) => {
    if (active) void run(() => holdApi.editHold(active.id, target.id, { ...toBody(target), ...changes }));
  };
  const update = (changes: Partial<Hold>) => { if (hold) change(hold, changes); };
  const setRole = (target: Hold, role: "start" | "middle" | "finish" | "top") => change(target, {
    role: role === "middle" ? "" : role === "top" ? "finish" : role,
    hold_type: role === "top" ? TOP_OUT : isTopOut(target) ? "" : target.hold_type,
    use: role === "top" || role === "finish" ? (target.use === "foot" ? "hand" : target.use || "hand") : target.use,
  });
  const fit = async () => {
    if (!active || !hold) return;
    setError(""); setBusy(true);
    try {
      const found = await holdApi.fit(active.id, { x: hold.x, y: hold.y, tolerance: "normal" });
      change(hold, { x: found.x, y: found.y, radius: found.radius });
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };
  const onKey = (event: React.KeyboardEvent, target: Hold) => {
    if (!active || event.metaKey || event.ctrlKey || event.altKey) return;
    const moves: Record<string, [number, number]> = { ArrowLeft: [-NUDGE, 0], ArrowRight: [NUDGE, 0], ArrowUp: [0, -NUDGE], ArrowDown: [0, NUDGE] };
    const roles: Record<string, "start" | "middle" | "finish" | "top"> = { s: "start", m: "middle", f: "finish", t: "top" };
    const key = event.key.length === 1 ? event.key.toLowerCase() : event.key;
    if (moves[key]) {
      event.preventDefault();
      const [dx, dy] = moves[key];
      change(target, { x: clamp(target.x + dx / zoom, 0, 1), y: clamp(target.y + dy / zoom, 0, 1) });
    } else if (key === "Delete" || key === "Backspace") {
      event.preventDefault();
      setSelected(null);
      void run(() => holdApi.removeHold(active.id, target.id));
    } else if (roles[key]) {
      event.preventDefault();
      setRole(target, roles[key]);
    } else if (key === "+" || key === "=" || key === "-") {
      event.preventDefault();
      change(target, { radius: clamp(target.radius * (key === "-" ? 0.87 : 1.15), MIN_RADIUS, MAX_RADIUS) });
    }
  };

  // Dragging a hold moves it, and dragging the handle on its edge resizes it. Nothing is saved until the pointer is released.
  const startDrag = (event: ReactPointerEvent<SVGCircleElement>, target: Hold, kind: Drag["kind"]) => {
    if (event.button !== 0 || !active) return;
    event.stopPropagation();
    (event.currentTarget as Element).setPointerCapture(event.pointerId);
    setSelected(target.id);
    dragRef.current = { id: target.id, kind, x: target.x, y: target.y, radius: target.radius, moved: false };
    const origin = pointAt(event.clientX, event.clientY);
    const offset = origin ? { x: origin.x - target.x, y: origin.y - target.y } : { x: 0, y: 0 };
    const startX = event.clientX, startY = event.clientY;
    const move = (e: PointerEvent) => {
      const at = pointAt(e.clientX, e.clientY), current = dragRef.current;
      if (!at || !current) return;
      if (!current.moved && Math.hypot(e.clientX - startX, e.clientY - startY) < 4) return;       // a click, not a drag
      const next: Drag = kind === "move"
        ? { ...current, moved: true, x: clamp(at.x - offset.x, 0, 1), y: clamp(at.y - offset.y, 0, 1) }
        : { ...current, moved: true, radius: clamp(Math.hypot((at.x - target.x) * active.width, (at.y - target.y) * active.height) / active.width, MIN_RADIUS, MAX_RADIUS) };
      dragRef.current = next; setDrag(next);
    };
    const end = () => {
      window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", end); window.removeEventListener("pointercancel", end);
      const final = dragRef.current;
      dragRef.current = null; setDrag(null);
      if (final?.moved) {
        justDragged.current = true; window.setTimeout(() => { justDragged.current = false; }, 0);
        change(target, { x: final.x, y: final.y, radius: final.radius });
      }
    };
    window.addEventListener("pointermove", move); window.addEventListener("pointerup", end); window.addEventListener("pointercancel", end);
  };

  if (!attempt) return <div className="page">{error ? <p className="error" role="alert">{error}</p> : <p className="muted">Loading…</p>}</div>;
  const width = active?.width ?? attempt.width ?? 1, height = active?.height ?? attempt.height ?? 1;
  const useWall = Boolean(active && wall?.combined && showWall);
  const lastMs = Math.max(0, (attempt.duration_ms ?? 1) - 1);
  const image = active ? active.frame_url : `/api/attempts/${attemptId}/frame?ms=${Math.min(previewMs, lastMs)}`;
  const pickFromVideo = !active && attempt.kind !== "photo" && Boolean(attempt.video_url);
  const shown = (item: Hold) => (drag?.id === item.id ? { ...item, x: drag.x, y: drag.y, radius: drag.radius } : item);
  const stroke = Math.max(1.5, width / 400) / Math.sqrt(zoom);
  const starts = active?.holds.filter((h) => h.role === "start").length ?? 0;
  const finishes = active?.holds.filter((h) => h.role === "finish").length ?? 0;
  const highest = active && active.holds.length >= 3 && finishes === 0 ? active.holds.reduce((top, h) => (h.y < top.y ? h : top)) : null;
  const numberOf = (target: Hold) => (active?.holds.findIndex((h) => h.id === target.id) ?? 0) + 1;
  const setFrame = (seconds: number) => {
    const value = clamp(seconds, 0, lastMs / 1000);
    setFrameSeconds(value.toFixed(1));
    if (picker.current && Math.abs(picker.current.currentTime - value) > 0.05) picker.current.currentTime = value;
  };

  return (
    <div className="page">
      <a className="back" href={`#/attempt/${attemptId}`}>← Back to {attempt.kind === "photo" ? "the photo" : "the review"}</a>
      <div className="page-head"><h1>Mark route holds <span className="muted small-text">{attempt.title}</span></h1></div>
      <p className="blind-note" role="note">
        Marking your route lets the review compare your hands and feet with its holds and suggest other sequences to test. You place or confirm every hold on one still picture. Color suggestions are not hold recognition, nothing here shows contact, and the marks only line up with the video if the camera stayed still.
      </p>
      {error && <p className="error" role="alert">{error}</p>}
      <div className="hold-layout">
        <section className="card">
          {active && (
            <div className="row tight zoom-bar" role="group" aria-label="Zoom">
              <button className="button small" data-testid="zoom-out" aria-label="Zoom out" disabled={zoom === ZOOMS[0]} onClick={() => zoomStep(-1)}>−</button>
              <span className="num small-text" data-testid="zoom-level" aria-live="polite">{Math.round(zoom * 100)}%</span>
              <button className="button small" data-testid="zoom-in" aria-label="Zoom in" disabled={zoom === ZOOMS[ZOOMS.length - 1]} onClick={() => zoomStep(1)}>+</button>
              {zoom > 1 && <button className="button small" data-testid="zoom-reset" onClick={() => zoomTo(1)}>Fit</button>}
              <span className="muted small-text">{zoom > 1 ? "Scroll to move around the picture." : "Zoom in to mark small footholds."}</span>
            </div>
          )}
          <div className={`hold-stage ${zoom > 1 ? "zoomed" : ""}`} data-testid="hold-stage" ref={stage}>
            {pickFromVideo ? (
              <video ref={picker} src={attempt.video_url ?? undefined} controls playsInline muted preload="auto" className="frame-picker" data-testid="frame-picker"
                onTimeUpdate={(e) => setFrameSeconds(e.currentTarget.currentTime.toFixed(1))} onSeeked={(e) => setFrameSeconds(e.currentTarget.currentTime.toFixed(1))} />
            ) : (
              <div className="hold-canvas" style={{ width: `${zoom * 100}%`, height: `${zoom * 100}%` }}>
                <img src={image} alt={`Reference frame at ${clock(active?.reference_frame_ms ?? previewMs)}`} data-testid={useWall ? undefined : "hold-image"} />
                {active && wall?.combined && <img src={wall.image_url} className={`wall-layer ${useWall ? "on" : ""}`} alt="Wall picture combined from the video, with the climber removed" aria-hidden={!useWall} data-testid={useWall ? "hold-image" : undefined} />}
                {active && (
                  <svg ref={svg} viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="xMidYMid meet" data-testid="hold-svg" onClick={addAt}>
                    {active.holds.map((raw, index) => {
                      const item = shown(raw), chosen = item.id === selected, arrow = PULL_ARROW[item.pull ?? ""];
                      const cx = item.x * width, cy = item.y * height, r = item.radius * width;
                      return (
                        <g key={item.id}>
                          <circle cx={cx} cy={cy} r={r} className="hold-mark"
                            fill={chosen ? "rgba(124,92,230,.3)" : "rgba(255,200,0,.2)"} stroke={chosen ? "#7c5ce6" : ROLE_COLOR[item.role]} strokeWidth={stroke} strokeDasharray={isTopOut(item) ? `${stroke * 3} ${stroke * 2}` : undefined}
                            tabIndex={0} role="button" aria-label={`Hold ${index + 1}${item.role ? `, ${isTopOut(item) ? "top out" : item.role}` : ""}, position ${Math.round(item.x * 100)}%, ${Math.round(item.y * 100)}%`} data-testid="hold-circle" data-role={item.role}
                            onPointerDown={(e) => startDrag(e, raw, "move")} onClick={(e) => { e.stopPropagation(); setSelected(item.id); }} onFocus={() => setSelected(item.id)} onKeyDown={(e) => onKey(e, raw)} />
                          {arrow && <line x1={cx - arrow[0] * r * 0.55} y1={cy - arrow[1] * r * 0.55 - r * 0.0} x2={cx + arrow[0] * r * 0.9} y2={cy + arrow[1] * r * 0.9} stroke="#fff" strokeWidth={stroke * 1.4} markerEnd="url(#pull-head)" pointerEvents="none" data-testid="pull-arrow" />}
                          <text x={cx} y={cy - r - stroke * 3} textAnchor="middle" fontSize={(width / 40) / Math.sqrt(zoom)} fontWeight="700" fill="#fff" stroke="#000" strokeWidth={stroke * 0.8} paintOrder="stroke" pointerEvents="none">{index + 1}{item.role === "start" ? " S" : isTopOut(item) ? " top" : item.role === "finish" ? " F" : ""}</text>
                          {chosen && <circle cx={cx + r} cy={cy} r={Math.max(stroke * 3.2, r * 0.16)} className="hold-handle" fill="#fff" stroke="#7c5ce6" strokeWidth={stroke} data-testid="hold-handle" aria-hidden="true" onPointerDown={(e) => startDrag(e, raw, "resize")} onClick={(e) => e.stopPropagation()} />}
                        </g>
                      );
                    })}
                    <defs><marker id="pull-head" viewBox="0 0 10 10" refX="7" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse"><path d="M0 0 L10 5 L0 10 z" fill="#fff" /></marker></defs>
                    {showGrid && geometry?.grid_points.map(([x, y], index) => <circle key={`g${index}`} cx={x} cy={y} r={Math.max(2.5, width / 240) / Math.sqrt(zoom)} fill="#22d35e" stroke="#063" strokeWidth="0.6" pointerEvents="none" data-testid="grid-point" />)}
                    {suggestions.map((item, index) => (
                      <circle key={`s${index}`} cx={item.x * width} cy={item.y * height} r={item.radius * width} fill="rgba(214,51,132,.12)" stroke="#d63384" strokeWidth={stroke} strokeDasharray={`${width / 120} ${width / 180}`}
                        role="button" tabIndex={0} aria-label={`Suggested hold ${index + 1}. Activate to add it.`} data-testid="hold-suggestion"
                        onClick={(e) => { e.stopPropagation(); void accept([item]); }} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); void accept([item]); } }} />
                    ))}
                    {(() => {
                      const line = scalePoints.length ? scalePoints : active.scale ? [{ x: active.scale.x1, y: active.scale.y1 }, { x: active.scale.x2, y: active.scale.y2 }] : [];
                      return (<g pointerEvents="none" data-testid="scale-line">
                        {line.length === 2 && <line x1={line[0].x * width} y1={line[0].y * height} x2={line[1].x * width} y2={line[1].y * height} stroke="#fff" strokeWidth={stroke * 1.4} strokeDasharray={scalePoints.length ? `${width / 100}` : undefined} />}
                        {line.map((point, index) => <circle key={index} cx={point.x * width} cy={point.y * height} r={(width / 120) / Math.sqrt(zoom)} fill="#fff" stroke="#000" />)}
                      </g>);
                    })()}
                  </svg>
                )}
              </div>
            )}
          </div>
          {active && attempt.kind !== "photo" && (
            <div className="wall-choice" data-testid="wall-status">
              {wallState === "idle" && (
                <p className="small-text">This is the frame you picked, from {clock(active.reference_frame_ms)}. If the climber is covering holds, the app can combine frames from the whole video into one picture with the climber removed.{" "}
                  <button className="button small" data-testid="build-wall" onClick={() => void buildWall(active.id)}>Load combined frames</button></p>
              )}
              {wallState === "loading" && <p className="small-text" role="status" data-testid="wall-loading"><span className="spinner" aria-hidden="true" /> Combining frames from the video into a clear picture. This can take up to a minute the first time. You can keep marking on the frame meanwhile; the marks stay in place when the picture changes.</p>}
              {wallState === "failed" && <p className="small-text">The combined picture could not be built, so the single frame stays. <button className="button small" onClick={() => void buildWall(active.id)}>Try again</button></p>}
              {wallState === "ready" && wall && (
                <p className="small-text">
                  {wall.combined
                    ? <span className="seg" role="group" aria-label="Picture shown">
                        <button className="button small" aria-pressed={!showWall} data-testid="wall-off" onClick={() => { setShowWall(false); rememberWall(active.id, false); }}>Your frame</button>
                        <button className="button small" aria-pressed={showWall} data-testid="wall-toggle" onClick={() => { setShowWall(true); rememberWall(active.id, true); }}>Combined, climber removed</button>
                      </span>
                    : <strong>The frames could not be combined, so the single frame stays. </strong>}
                  {" "}{wall.detail}{wall.combined ? " Marks line up with the video because the camera did not move." : ""}
                </p>
              )}
            </div>
          )}
          {active && (
            <div data-testid="grid-status">
              <label className="choice small-text"><input type="checkbox" checked={showGrid} data-testid="grid-toggle" onChange={(e) => {
                setShowGrid(e.target.checked);
                if (e.target.checked && !geometry) holdApi.wallGeometry(active.id).then(setGeometry).catch((error) => setError(error.message));
              }} /> Show the fitted bolt grid</label>
              {showGrid && !geometry && <span className="muted small-text" role="status"> Fitting the grid…</span>}
              {showGrid && geometry && geometry.status !== "ok" && <p className="muted small-text">{geometry.reason}</p>}
              {showGrid && geometry?.status === "ok" && <><p className="muted small-text">Green dots are the bolt holes the fit used. If they sit on real holes across your route, the wall's angle is being read correctly.</p><PerspectiveNote perspective={geometry.summary} /></>}
            </div>
          )}
          {active
            ? <p className="muted small-text" data-testid="mode-hint"><strong>{mode === "suggest" ? "Suggesting by color." : mode === "scale" ? "Setting the scale." : "Adding holds."}</strong> {mode === "suggest" ? "Click one hold of your route to find others of the same color." : mode === "scale" ? "Click two points on the wall whose real distance apart you know." : "Click the picture to add a hold. Drag a hold to move it, and drag the white handle on its edge to resize it."} With a hold selected: arrow keys move it, + and − resize it, S, M, F, and T set start, middle, finish, and top out, and Delete removes it. Picture from {clock(active.reference_frame_ms)}.</p>
            : <p className="muted small-text">{pickFromVideo ? "Scrub the video to a moment when the climber covers as few holds as possible, then create the map from that frame." : "Choose the frame, then create a hold map."}</p>}
        </section>
        <section className="card">
          {!active ? (
            <>
              <h2>Your hold maps</h2>
              {maps.length === 0 && <p className="muted small-text">No map yet. A map is one route's holds marked on one picture of the wall.</p>}
              {maps.length > 0 && (
                <ul className="interval-list">
                  {maps.map((item) => (
                    <li key={item.id}><span>{item.name} ({item.holds.length} holds, {clock(item.reference_frame_ms)})</span>
                      <button className="button small" aria-label={`Open map ${item.name}`} onClick={() => { setActive(item); setZoom(1); }}>Open</button></li>
                  ))}
                </ul>
              )}
              <h3>New map</h3>
              <label>Name<input value={name} data-testid="map-name" onChange={(e) => setName(e.target.value)} /></label>
              {attempt.kind !== "photo" && (
                <>
                  <label>Picture to mark on: {clock(previewMs)} of {clock(attempt.duration_ms)}
                    <input type="range" min="0" max={(lastMs / 1000).toFixed(1)} step="0.1" value={Math.min(parseFloat(frameSeconds || "0"), lastMs / 1000)} data-testid="map-frame-slider" aria-label="Reference frame time" onChange={(e) => setFrame(parseFloat(e.target.value))} />
                  </label>
                  <div className="row tight">
                    <button className="button small" data-testid="frame-back" onClick={() => setFrame(parseFloat(frameSeconds || "0") - 0.5)}>− 0.5s</button>
                    <button className="button small" data-testid="frame-forward" onClick={() => setFrame(parseFloat(frameSeconds || "0") + 0.5)}>+ 0.5s</button>
                    <label className="inline-field">Time (s)<input type="number" min="0" step="0.1" value={frameSeconds} data-testid="map-frame" onChange={(e) => { setFrameSeconds(e.target.value); const value = parseFloat(e.target.value); if (picker.current && Number.isFinite(value)) picker.current.currentTime = clamp(value, 0, lastMs / 1000); }} /></label>
                  </div>
                  <p className="muted small-text">Drag the slider or the video's own bar to a moment when every hold of your route is visible: the picture on the left is the frame that will be used. If the climber covers holds in every frame, create the map anyway and choose "Load combined frames" afterwards to remove the climber.</p>
                </>
              )}
              <button className="button primary" data-testid="create-map" onClick={() => void run(() => holdApi.create(attemptId, { name, reference_frame_ms: Math.min(previewMs, lastMs) }))}>Create map from this frame</button>
            </>
          ) : (
            <>
              <div className="panel-head"><h2>Editing: {active.name}</h2>
                <span className={`save-state ${saveState === "error" ? "bad" : ""}`} role="status" data-testid="save-state">{saveState === "saving" ? "Saving…" : saveState === "error" ? "Last change not saved" : saveState === "saved" ? "All changes saved" : "Changes save as you make them"}</span></div>
              <div className="row tight" role="group" aria-label="What a click on the picture does">
                <button className={`button small ${mode === "add" ? "active" : ""}`} aria-pressed={mode === "add"} data-testid="mode-add" onClick={() => setMode("add")}>Add one hold</button>
                <button className={`button small ${mode === "suggest" ? "active" : ""}`} aria-pressed={mode === "suggest"} data-testid="mode-suggest" onClick={() => setMode("suggest")}>Suggest by color</button>
                <button className={`button small ${mode === "scale" ? "active" : ""}`} aria-pressed={mode === "scale"} data-testid="mode-scale" onClick={() => { setMode("scale"); setScalePoints([]); }}>Set scale</button>
              </div>
              {mode === "suggest" && (
                <div data-testid="suggest-panel">
                  <label>Color match
                    <select value={tolerance} data-testid="suggest-tolerance" onChange={(e) => setTolerance(e.target.value)}>
                      <option value="strict">Strict (fewer, closer colors)</option><option value="normal">Normal</option><option value="loose">Loose (more, may include other things)</option>
                    </select>
                  </label>
                  {busy && <p className="muted small-text">Working…</p>}
                  {suggestNote && <p className="muted small-text" role="status" data-testid="suggest-note">{suggestNote}</p>}
                  {suggestions.length > 0 && (
                    <div className="row tight">
                      <button className="button small primary" data-testid="accept-all" disabled={busy} onClick={() => void accept(suggestions)}>Add all {suggestions.length}</button>
                      <button className="button small" data-testid="clear-suggestions" onClick={() => { setSuggestions([]); setSuggestNote(""); }}>Discard</button>
                    </div>
                  )}
                  <p className="muted small-text">Dashed pink outlines are only suggestions. Click one to add it, then delete or adjust any that are wrong.</p>
                </div>
              )}
              {mode === "scale" && (
                <div data-testid="scale-panel">
                  <p className="muted small-text">{scalePoints.length} of 2 points chosen. Good references are a measured distance between two holds or bolt holes, or the height of a panel.</p>
                  <div className="row tight">
                    <label className="inline-field">Real distance between the points<input type="number" min="1" step="1" value={scaleValue} data-testid="scale-cm" onChange={(e) => setScaleValue(e.target.value)} /></label>
                    <select value={scaleUnit} aria-label="Unit" data-testid="scale-unit" onChange={(e) => setScaleUnit(e.target.value as "cm" | "in")}><option value="cm">cm</option><option value="in">inches</option></select>
                  </div>
                  <button className="button small primary" data-testid="save-scale" disabled={scalePoints.length !== 2 || !(scaleCm >= 5)} onClick={() => void saveScale()}>Save scale</button>
                </div>
              )}
              <p className="small-text" data-testid="scale-status">{active.scale ? `Scale set: the white line is ${active.scale.cm} cm (${(active.scale.cm / CM_PER_INCH).toFixed(1)} in).` : "No scale set. A scale is needed to plan with your height and wingspan."}</p>
              <div className="grid2">
                <label>Route for new holds<input value={route} data-testid="route-input" onChange={(e) => setRoute(e.target.value)} /></label>
                <label>New holds are for
                  <select value={newUse} data-testid="new-use" onChange={(e) => setNewUse(e.target.value as Hold["use"])}>
                    <option value="">Not sure yet</option><option value="hand">Hands</option><option value="foot">Feet</option><option value="both">Hands and feet</option>
                  </select>
                </label>
              </div>
              {highest && (
                <p className="notice-text small-text" data-testid="finish-proposal">No finish yet. Hold {numberOf(highest)} is the highest mark.{" "}
                  <button className="link" data-testid="propose-finish" onClick={() => setRole(highest, "finish")}>Set it as the finish</button> or <button className="link" data-testid="propose-top" onClick={() => setRole(highest, "top")}>the route tops out there</button>.</p>
              )}
              {active.holds.length >= 2 && starts === 0 && <p className="notice-text small-text" data-testid="start-reminder">No start yet. Select each start hold and choose Start, or press S.</p>}
              {hold ? (
                <div data-testid="hold-details" className="hold-details">
                  <h3>Hold {numberOf(hold)}</h3>
                  <div className="field"><span className="field-label">Role on this problem</span>
                    <div className="seg" role="group" aria-label="Role on this problem" data-testid="hold-role">
                      {([["start", "Start", hold.role === "start"], ["middle", "Middle", hold.role === ""], ["finish", "Finish", hold.role === "finish" && !isTopOut(hold)], ["top", "Top out", isTopOut(hold)]] as const).map(([value, label, on]) => (
                        <button key={value} className="button small" aria-pressed={on} data-testid={`hold-role-${value}`} onClick={() => setRole(hold, value)}>{label}</button>
                      ))}
                    </div>
                  </div>
                  <div className="field"><span className="field-label">Used by</span>
                    <div className="seg" role="group" aria-label="Used by" data-testid="hold-use">
                      {([["hand", "Hands"], ["foot", "Feet"], ["both", "Both"], ["", "Not sure"]] as const).map(([value, label]) => (
                        <button key={value || "unset"} className="button small" aria-pressed={hold.use === value} data-testid={`hold-use-${value || "unset"}`} onClick={() => update({ use: value })}>{label}</button>
                      ))}
                    </div>
                  </div>
                  {hold.use !== "foot" && (
                    <div className="field"><span className="field-label">Pull direction for a hand (optional)</span>
                      <div className="seg" role="group" aria-label="Pull direction" data-testid="hold-pull">
                        {PULLS.map((item) => <button key={item.value || "unset"} className="button small" title={item.title} aria-pressed={(hold.pull ?? "") === item.value} data-testid={`hold-pull-${item.value || "unset"}`} onClick={() => update({ pull: item.value })}>{item.label}</button>)}
                      </div>
                      <p className="muted small-text">{PULLS.find((item) => item.value === (hold.pull ?? ""))?.title}.</p>
                    </div>
                  )}
                  <label>Size<input type="range" min={MIN_RADIUS} max="0.15" step="0.002" value={Math.min(hold.radius, 0.15)} data-testid="hold-radius" onChange={(e) => update({ radius: parseFloat(e.target.value) })} /></label>
                  <div className="row tight">
                    <button className="button small" data-testid="fit-hold" disabled={busy} title="Sizes the circle to the patch of one color under it" onClick={() => void fit()}>{busy ? "Fitting…" : "Fit to the hold's color"}</button>
                    <button className="button small danger" onClick={() => { setSelected(null); void run(() => holdApi.removeHold(active.id, hold.id)); }}>Delete hold</button>
                  </div>
                  <details><summary className="small-text">Route name and your own label</summary>
                    <label>Route<input value={hold.route} onChange={(e) => update({ route: e.target.value })} /></label>
                    <label>Type (your own label)<input value={hold.hold_type} disabled={isTopOut(hold)} onChange={(e) => update({ hold_type: e.target.value })} /></label>
                  </details>
                </div>
              ) : <p className="muted">Click a hold to edit it. New holds start as middle holds.</p>}
              <h3 data-testid="hold-count">{active.holds.length} holds{active.holds.length ? ` · ${starts} start, ${finishes} finish` : ""}</h3>
              <div className="row tight"><button className="button small" data-testid="undo-hold" disabled={!canUndo || saveState === "saving"} onClick={undo}>Undo last added hold</button></div>
              <details className="tips" data-testid="marking-tips"><summary>Marking tips</summary>
                <ul className="plain-list small-text">
                  <li><strong>Start holds are used again later.</strong> A start hold stays available for hands and feet for the rest of the climb, so it needs only the Start role.</li>
                  <li><strong>No finish hold?</strong> Mark the spot on the lip you grab last and choose Top out.</li>
                  <li><strong>Not sure if it is for hands or feet?</strong> Leave it as Not sure. The planner then allows either.</li>
                  <li><strong>Volumes.</strong> Mark the part you would actually use, as a hold for hands and feet. Add a second mark for a second usable spot.</li>
                  <li><strong>Long holds and rails.</strong> The planner measures from the center of each circle. Put one mark at each place you would grab, not one big circle around the whole hold.</li>
                  <li><strong>Sidepulls and underclings.</strong> Set a pull direction and the planner keeps the body on the side that makes the hold usable.</li>
                </ul>
              </details>
              <div className="row tight">
                <a className="button small primary" data-testid="open-planner" href={`#/plan/${attemptId}`}>Plan a route</a>
                <a className="button small" href={`/api/hold-maps/${active.id}/export`} download>Export JSON</a>
                <button className="button small" onClick={() => { setActive(null); setSelected(null); setAdded([]); setSaveState("idle"); setZoom(1); void load(); }}>All maps</button>
                <button className="button small danger" onClick={async () => { if (window.confirm("Delete this hold map?")) { await holdApi.remove(active.id); setActive(null); void load(); } }}>Delete map</button>
              </div>
            </>
          )}
        </section>
      </div>
    </div>
  );
}
