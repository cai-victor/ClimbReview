import { MouseEvent, PointerEvent as ReactPointerEvent, useCallback, useEffect, useRef, useState } from "react";
import { api, Attempt, clock, Hold, HoldBody, holdApi, HoldMap, HoldSuggestion, StartLimb, WallGeometry, WallInfo } from "./api";
import { PerspectiveNote } from "./Performance";

type Mode = "add" | "suggest" | "scale";
type Drag = { id: string; kind: "move" | "resize"; x: number; y: number; radius: number; moved: boolean };
/** One undoable change. Ids are looked up again when undoing, because a hold that was deleted and restored gets a new id. */
type UndoStep = { kind: "add"; ids: string[] } | { kind: "remove"; hold: Hold } | { kind: "edit"; id: string; before: HoldBody; fields: string; at: number };

const DEFAULT_RADIUS = 0.035;
const NUDGE = 0.005;
const MIN_RADIUS = 0.006, MAX_RADIUS = 0.2;
const ZOOMS = [1, 1.5, 2, 3, 4, 6];
export const TOP_OUT = "top-out";
export const VOLUME = "volume";
const START_LIMBS: { value: StartLimb; label: string; short: string }[] = [
  { value: "", label: "Not set", short: "" }, { value: "left_hand", label: "Left hand", short: "LH" }, { value: "right_hand", label: "Right hand", short: "RH" },
  { value: "both_hands", label: "Both hands", short: "LH+RH" }, { value: "left_foot", label: "Left foot", short: "LF" }, { value: "right_foot", label: "Right foot", short: "RF" },
];
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
  return { x: hold.x, y: hold.y, radius: hold.radius, route: hold.route, hold_type: hold.hold_type, role: hold.role, use: hold.use, pull: hold.pull ?? "", start_limb: hold.role === "start" ? hold.start_limb ?? "" : "" };
}
const isTopOut = (hold: Hold) => hold.role === "finish" && hold.hold_type.trim().toLowerCase() === TOP_OUT;
const isVolume = (hold: Hold) => !isTopOut(hold) && hold.hold_type.trim().toLowerCase() === VOLUME;
const typing = (target: EventTarget | null) => target instanceof HTMLElement && (target.tagName === "TEXTAREA" || target.tagName === "SELECT" || (target instanceof HTMLInputElement && target.type !== "range" && target.type !== "checkbox"));
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
  const history = useRef<UndoStep[]>([]);               // changes made in this visit, newest last
  const renamed = useRef<Record<string, string>>({});   // old id to new id, for holds restored by an undo
  const [undoable, setUndoable] = useState(0);
  const undoRef = useRef<() => void>(() => {});
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
    history.current = []; renamed.current = {}; setUndoable(0); setSuggestions([]); setSuggestNote(""); setMode("add");
    // The combined picture is built only when asked for. A map where it was chosen before loads it again, which is quick once built.
    if (activeId && wallChoice(activeId)) void buildWall(activeId);
  }, [activeId]);

  const load = useCallback(async () => {
    try { setAttempt(await api.getAttempt(attemptId)); setMaps(await holdApi.list(attemptId)); }
    catch (e) { setError((e as Error).message); }
  }, [attemptId]);
  useEffect(() => { void load(); }, [load]);

  // Saves go to the server one at a time, in the order they were made, and each is built from the newest saved map.
  // Two quick changes to one hold can then never overwrite each other with stale values.
  const latest = useRef<HoldMap | null>(null);
  latest.current = active;
  const queue = useRef<Promise<unknown>>(Promise.resolve());
  const waiting = useRef(0);
  const exec = async (action: () => Promise<HoldMap>) => {
    setError(""); setSaveState("saving");
    try {
      const next = await action();
      latest.current = next;
      if (waiting.current <= 1) { setActive(next); setSaveState("saved"); }     // while more saves wait, the screen keeps showing what the user did
      return next;
    } catch (e) { setError(`Not saved: ${(e as Error).message}`); setSaveState("error"); if (latest.current) setActive(latest.current); return null; }
  };
  const enqueue = <T,>(job: () => Promise<T>): Promise<T> => {
    waiting.current += 1;
    const result = queue.current.then(job).finally(() => { waiting.current -= 1; });
    queue.current = result.catch(() => undefined);
    return result;
  };
  const run = (action: () => Promise<HoldMap>) => enqueue(() => exec(action));
  const saved = (id: string) => latest.current?.holds.find((h) => h.id === id) ?? null;
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
        .then((result) => {
          // Outlines from an earlier color stay, and the next click adds by hand again: looking for a color is one click, not a mode to get stuck in.
          const apart = (a: HoldSuggestion, b: HoldSuggestion) => Math.hypot((a.x - b.x) * active.width, (a.y - b.y) * active.height) > Math.max(a.radius, b.radius) * active.width;
          setSuggestions((kept) => [...kept, ...result.suggestions.filter((item) => kept.every((other) => apart(item, other)))]);
          setSuggestNote(result.suggestions.length ? `${result.suggestions.length} new outline${result.suggestions.length === 1 ? "" : "s"} in the color you clicked. ${result.note}` : "Nothing else in that color looked like a hold. Try the loose setting, or add the holds by hand.");
          setMode("add");
        })
        .catch((e) => { setSuggestNote(""); setError((e as Error).message); })
        .finally(() => setBusy(false));
      return;
    }
    if (mode === "scale") { setScalePoints((points) => (points.length >= 2 ? [{ x, y }] : [...points, { x, y }])); return; }
    void run(() => holdApi.addHold(active.id, { x, y, radius: DEFAULT_RADIUS / Math.sqrt(zoom), route, hold_type: "", role: "", use: "", pull: "" })).then((next) => {
      if (next) { const id = next.holds[next.holds.length - 1].id; setSelected(id); record({ kind: "add", ids: [id] }); }
    });
  };
  const accept = async (items: HoldSuggestion[]) => {
    if (!active) return;
    setBusy(true);
    let latest: HoldMap | null = null;
    const ids: string[] = [];
    for (const item of items) {
      latest = await run(() => holdApi.addHold(active.id, { x: item.x, y: item.y, radius: item.radius, route, hold_type: "", role: "", use: "", pull: "" }));
      if (latest) ids.push(latest.holds[latest.holds.length - 1].id);
    }
    if (ids.length) record({ kind: "add", ids });          // one undo takes back the whole batch
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
  const record = (step: UndoStep) => { history.current.push(step); setUndoable(history.current.length); };
  const current = (id: string) => { let now = id; while (renamed.current[now]) now = renamed.current[now]; return now; };
  const undoNow = async () => {
    const map = latest.current, step = history.current.pop();
    setUndoable(history.current.length);
    if (!map || !step) return;
    if (step.kind === "add") {
      const ids = step.ids.map(current);
      setSelected((now) => (now && ids.includes(now) ? null : now));
      for (const id of ids) if (saved(id)) await exec(() => holdApi.removeHold(map.id, id));
    } else if (step.kind === "remove") {
      const next = await exec(() => holdApi.addHold(map.id, toBody(step.hold)));
      if (next) { const id = next.holds[next.holds.length - 1].id; renamed.current[step.hold.id] = id; setSelected(id); }
    } else {
      const id = current(step.id), now = saved(id);
      const before = Object.fromEntries(step.fields.split(",").map((field) => [field, step.before[field as keyof HoldBody]]));
      if (now) await exec(() => holdApi.editHold(map.id, id, { ...toBody(now), ...before }));
    }
    if (latest.current) setActive(latest.current);
  };
  const undo = () => enqueue(undoNow);
  undoRef.current = () => void undo();
  const lastStep = history.current[history.current.length - 1];
  const undoLabel = !lastStep ? "Undo" : lastStep.kind === "add" ? (lastStep.ids.length > 1 ? `Undo adding ${lastStep.ids.length} holds` : "Undo adding a hold") : lastStep.kind === "remove" ? "Undo deleting a hold" : "Undo last change";
  const change = (target: Hold, changes: Partial<Hold>) => {
    if (!active) return;
    const fields = Object.keys(changes).sort().join(","), previous = history.current[history.current.length - 1], now = Date.now();
    // Dragging a slider or typing sends many small edits; they undo as one.
    if (previous?.kind === "edit" && previous.id === target.id && previous.fields === fields && now - previous.at < 1200) previous.at = now;
    else record({ kind: "edit", id: target.id, before: toBody(target), fields, at: now });
    const apply = (map: HoldMap | null) => map && { ...map, holds: map.holds.map((h) => (h.id === target.id ? { ...h, ...changes } : h)) };
    setActive(apply);                                   // shown at once; the save follows
    void run(() => holdApi.editHold(active.id, target.id, { ...toBody(saved(target.id) ?? target), ...changes }));
  };
  const remove = (target: Hold) => {
    if (!active) return;
    record({ kind: "remove", hold: target });
    if (selected === target.id) setSelected(null);
    setActive((map) => map && { ...map, holds: map.holds.filter((h) => h.id !== target.id) });
    void run(() => holdApi.removeHold(active.id, target.id));
  };
  const update = (changes: Partial<Hold>) => { if (hold) change(hold, changes); };
  const setStartLimb = (target: Hold, limb: StartLimb) => change(target, {
    start_limb: limb,
    use: limb.endsWith("foot") ? (target.use === "both" ? "both" : "foot") : limb && target.use === "foot" ? "hand" : target.use,
  });
  const setRole = (target: Hold, role: "start" | "middle" | "finish" | "top") => change(target, {
    start_limb: role === "start" ? target.start_limb ?? "" : "",
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
      remove(target);
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
        change(target, kind === "move" ? { x: final.x, y: final.y } : { radius: final.radius });
      }
    };
    window.addEventListener("pointermove", move); window.addEventListener("pointerup", end); window.addEventListener("pointercancel", end);
  };

  useEffect(() => {
    const onUndo = (event: KeyboardEvent) => {
      if (!(event.metaKey || event.ctrlKey) || event.shiftKey || event.altKey || event.key.toLowerCase() !== "z" || typing(event.target)) return;
      event.preventDefault();
      undoRef.current();
    };
    window.addEventListener("keydown", onUndo);
    return () => window.removeEventListener("keydown", onUndo);
  }, []);

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
  // Large marks are drawn first, so a small mark inside a large one stays on top and can be clicked.
  const drawn = active ? active.holds.map((item, index) => ({ item, index })).sort((a, b) => b.item.radius - a.item.radius) : [];
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
                    {drawn.map(({ item: raw, index }) => {
                      const item = shown(raw), chosen = item.id === selected, arrow = PULL_ARROW[item.pull ?? ""];
                      const limb = item.role === "start" ? START_LIMBS.find((option) => option.value === (item.start_limb ?? ""))?.short : "";
                      const cx = item.x * width, cy = item.y * height, r = item.radius * width;
                      return (
                        <g key={item.id}>
                          <circle cx={cx} cy={cy} r={r} className="hold-mark"
                            fill={chosen ? "rgba(124,92,230,.3)" : "rgba(255,200,0,.2)"} stroke={chosen ? "#7c5ce6" : ROLE_COLOR[item.role]} strokeWidth={stroke} strokeDasharray={isTopOut(item) ? `${stroke * 3} ${stroke * 2}` : isVolume(item) ? `${stroke * 8} ${stroke * 3}` : undefined}
                            tabIndex={0} role="button" aria-label={`Hold ${index + 1}${item.role ? `, ${isTopOut(item) ? "top out" : item.role}` : ""}, position ${Math.round(item.x * 100)}%, ${Math.round(item.y * 100)}%`} data-testid="hold-circle" data-role={item.role}
                            onPointerDown={(e) => startDrag(e, raw, "move")} onClick={(e) => { e.stopPropagation(); setSelected(item.id); }} onFocus={() => setSelected(item.id)} onKeyDown={(e) => onKey(e, raw)} />
                          {arrow && <line x1={cx - arrow[0] * r * 0.55} y1={cy - arrow[1] * r * 0.55 - r * 0.0} x2={cx + arrow[0] * r * 0.9} y2={cy + arrow[1] * r * 0.9} stroke="#fff" strokeWidth={stroke * 1.4} markerEnd="url(#pull-head)" pointerEvents="none" data-testid="pull-arrow" />}
                          <text x={cx} y={cy - r - stroke * 3} textAnchor="middle" fontSize={(width / 40) / Math.sqrt(zoom)} fontWeight="700" fill="#fff" stroke="#000" strokeWidth={stroke * 0.8} paintOrder="stroke" pointerEvents="none">{index + 1}{item.role === "start" ? ` S${limb ? ` ${limb}` : ""}` : isTopOut(item) ? " top" : item.role === "finish" ? " F" : ""}{isVolume(item) ? " vol" : ""}</text>
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
            ? <p className="muted small-text" data-testid="mode-hint"><strong>{mode === "suggest" ? "Finding holds by color." : mode === "scale" ? "Setting the scale." : "Adding holds by hand."}</strong> {mode === "suggest" ? "Click one hold of your route. Others of that color are outlined in pink, and after that one click the picture goes back to adding holds by hand." : mode === "scale" ? "Click two points on the wall whose real distance apart you know." : `Click the picture to add a hold${suggestions.length ? ", or click a pink outline to accept it" : ""}. Drag a hold to move it, and drag the white handle on its edge to resize it.`} The order you mark holds in does not matter. Cmd+Z or Ctrl+Z undoes the last change. With a hold selected: arrow keys move it, + and − resize it, S, M, F, and T set start, middle, finish, and top out, and Delete removes it. Picture from {clock(active.reference_frame_ms)}.</p>
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
                <button className={`button small ${mode === "add" ? "active" : ""}`} aria-pressed={mode === "add"} data-testid="mode-add" onClick={() => setMode("add")}>Add holds by hand</button>
                <button className={`button small ${mode === "suggest" ? "active" : ""}`} aria-pressed={mode === "suggest"} data-testid="mode-suggest" title="The next click on the picture outlines holds of that color. After it, clicks add holds by hand again." onClick={() => setMode("suggest")}>Find holds by color</button>
                <button className={`button small ${mode === "scale" ? "active" : ""}`} aria-pressed={mode === "scale"} data-testid="mode-scale" onClick={() => { setMode("scale"); setScalePoints([]); }}>Set scale</button>
              </div>
              {(mode === "suggest" || suggestions.length > 0 || suggestNote) && (
                <div data-testid="suggest-panel" className="suggest-panel">
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
                  <p className="muted small-text">{mode === "suggest" ? "Waiting for one click on a hold of your route. " : ""}Dashed pink outlines are only suggestions and are not saved until you accept them. Click one to add it, or keep adding holds by hand: the outlines stay until you discard them.{mode !== "suggest" ? <> <button className="link" data-testid="suggest-again" onClick={() => setMode("suggest")}>Find another color</button></> : null}</p>
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
                  {hold.role === "start" && (
                    <div className="field"><span className="field-label">Starts with (optional)</span>
                      <div className="seg" role="group" aria-label="Limb that starts on this hold" data-testid="hold-start-limb">
                        {START_LIMBS.map((option) => <button key={option.value || "unset"} className="button small" aria-pressed={(hold.start_limb ?? "") === option.value} data-testid={`hold-start-${option.value || "unset"}`} onClick={() => setStartLimb(hold, option.value)}>{option.label}</button>)}
                      </div>
                      <p className="muted small-text">Left unset, the planner picks which hand or foot starts here.</p>
                    </div>
                  )}
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
                  {!isTopOut(hold) && (
                    <div className="field"><span className="field-label">Kind of mark</span>
                      <div className="seg" role="group" aria-label="Kind of mark" data-testid="hold-kind">
                        <button className="button small" aria-pressed={!isVolume(hold)} data-testid="hold-kind-hold" onClick={() => { if (isVolume(hold)) update({ hold_type: "" }); }}>One hold</button>
                        <button className="button small" aria-pressed={isVolume(hold)} data-testid="hold-kind-volume" title="Size the circle to cover the volume. The planner then tries its top, left, and right for hands and feet." onClick={() => update({ hold_type: VOLUME })}>Volume</button>
                      </div>
                      {isVolume(hold) && <p className="muted small-text">Size the circle to cover the whole volume. The planner tries its top, left side, and right side, for hands or feet. Holds bolted onto the volume get their own marks.</p>}
                    </div>
                  )}
                  <label>Size<input type="range" min={MIN_RADIUS} max="0.15" step="0.002" value={Math.min(hold.radius, 0.15)} data-testid="hold-radius" onChange={(e) => update({ radius: parseFloat(e.target.value) })} /></label>
                  <div className="row tight">
                    <button className="button small" data-testid="fit-hold" disabled={busy} title="Sizes the circle to the patch of one color under it" onClick={() => void fit()}>{busy ? "Fitting…" : "Fit to the hold's color"}</button>
                    <button className="button small danger" data-testid="delete-hold" onClick={() => remove(hold)}>Delete hold</button>
                  </div>
                  <details><summary className="small-text">Route name and your own label</summary>
                    <label>Route<input value={hold.route} onChange={(e) => update({ route: e.target.value })} /></label>
                    <label>Type (your own label)<input value={hold.hold_type} disabled={isTopOut(hold) || isVolume(hold)} onChange={(e) => update({ hold_type: e.target.value })} /></label>
                  </details>
                </div>
              ) : <p className="muted">Click a hold to set its role and who uses it. New holds start as middle holds for hands or feet.</p>}
              <h3 data-testid="hold-count">{active.holds.length} holds{active.holds.length ? ` · ${starts} start, ${finishes} finish` : ""}</h3>
              <div className="row tight"><button className="button small" data-testid="undo-hold" title="Cmd+Z or Ctrl+Z" disabled={!undoable} onClick={() => void undo()}>{undoLabel}</button></div>
              <details><summary className="small-text">Marking more than one route on this picture</summary>
                <label>Route name given to new holds<input value={route} data-testid="route-input" onChange={(e) => setRoute(e.target.value)} /></label>
              </details>
              <details className="tips" data-testid="marking-tips"><summary>Marking tips</summary>
                <ul className="plain-list small-text">
                  <li><strong>Any order.</strong> The numbers are only labels. Mark holds in whatever order is easiest; the planner works out the sequence from the start and finish roles.</li>
                  <li><strong>Which hand or foot starts where.</strong> Select a start hold and choose Left hand, Right hand, Both hands, Left foot, or Right foot under "Starts with".</li>
                  <li><strong>The finish is matched.</strong> Planned sequences end with both hands on the finish hold. Mark two finish holds only if the problem really ends with one hand on each.</li>
                  <li><strong>Start holds are used again later.</strong> A start hold stays available for hands and feet for the rest of the climb, so it needs only the Start role.</li>
                  <li><strong>No finish hold?</strong> Mark the spot on the lip you grab last and choose Top out.</li>
                  <li><strong>Not sure if it is for hands or feet?</strong> Leave it as Not sure. The planner then allows either.</li>
                  <li><strong>Volumes.</strong> Add one mark, drag its handle until the circle covers the volume, and choose Volume. The planner then tries the top and both sides for hands and feet. Color matching usually misses volumes, so mark them by hand.</li>
                  <li><strong>Long holds and rails.</strong> The planner measures from the center of each circle. Put one mark at each place you would grab, not one big circle around the whole hold.</li>
                  <li><strong>Sidepulls and underclings.</strong> Set a pull direction and the planner keeps the body on the side that makes the hold usable.</li>
                </ul>
              </details>
              <div className="row tight">
                <a className="button small primary" data-testid="open-planner" href={`#/plan/${attemptId}`}>Plan a route</a>
                <a className="button small" href={`/api/hold-maps/${active.id}/export`} download>Export JSON</a>
                <button className="button small" onClick={() => { setActive(null); setSelected(null); setSaveState("idle"); setZoom(1); void load(); }}>All maps</button>
                <button className="button small danger" onClick={async () => { if (window.confirm("Delete this hold map?")) { await holdApi.remove(active.id); setActive(null); void load(); } }}>Delete map</button>
              </div>
            </>
          )}
        </section>
      </div>
    </div>
  );
}
