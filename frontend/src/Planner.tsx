import { useCallback, useEffect, useState } from "react";
import { api, Attempt, holdApi, HoldMap, PlanResult } from "./api";
import { BetaFigure, holdName, LIMB_WORD, PerspectiveNote } from "./Performance";

const STORE = "climbreview.body";
const saved = (): { height: string; wingspan: string } => {
  try { return { height: "", wingspan: "", ...JSON.parse(window.localStorage.getItem(STORE) ?? "{}") }; } catch { return { height: "", wingspan: "" }; }
};

/** Candidate sequences from marked holds, the picture's scale, and the climber's own height and wingspan. Needs no video analysis. */
export function Planner({ attemptId }: { attemptId: string }) {
  const [attempt, setAttempt] = useState<Attempt | null>(null);
  const [maps, setMaps] = useState<HoldMap[]>([]);
  const [mapId, setMapId] = useState("");
  const [body, setBody] = useState(saved);
  const [result, setResult] = useState<PlanResult | null>(null);
  const [active, setActive] = useState(0);
  const [step, setStep] = useState(0);
  const [error, setError] = useState("");
  const [rectify, setRectify] = useState(true);

  useEffect(() => {
    Promise.all([api.getAttempt(attemptId), holdApi.list(attemptId)])
      .then(([a, list]) => { setAttempt(a); setMaps(list); setMapId(list[list.length - 1]?.id ?? ""); })
      .catch((e) => setError(e.message));
  }, [attemptId]);

  const height = parseFloat(body.height), wingspan = parseFloat(body.wingspan);
  const valid = height >= 100 && height <= 230 && wingspan >= 100 && wingspan <= 250;
  const plan = useCallback(async () => {
    setError("");
    try {
      window.localStorage.setItem(STORE, JSON.stringify(body));     // stays in this browser only
      setResult(await holdApi.plan(mapId, height, wingspan, rectify)); setActive(0); setStep(0);
    } catch (e) { setError((e as Error).message); }
  }, [mapId, height, wingspan, body, rectify]);

  if (!attempt) return <div className="page">{error ? <p className="error" role="alert">{error}</p> : <p className="muted">Loading…</p>}</div>;
  const candidate = result?.candidates[Math.min(active, result.candidates.length - 1)] ?? null;

  return (
    <div className="page">
      <div className="page-head"><a href={`#/attempt/${attemptId}`}>← Back</a><h1>Plan a route: {attempt.title}</h1><a className="button" href={`#/holds/${attemptId}`}>Mark holds</a></div>
      <p className="blind-note" role="note">These are ideas from 2D geometry on holds you confirmed. The picture cannot show hold quality, wall angle, or balance, so try them on the wall. None is the best or easiest beta.</p>
      {error && <p className="error" role="alert">{error}</p>}
      {maps.length === 0 ? (
        <section className="card" data-testid="planner-no-map"><p>This climb has no marked holds yet.</p><a className="button primary" href={`#/holds/${attemptId}`}>Mark holds</a></section>
      ) : (
        <div className="hold-layout">
          <section className="card">
            {result?.hold_map
              ? <BetaFigure map={result.hold_map} candidate={candidate} stepIndex={step} width={result.hold_map.width} height={result.hold_map.height} />
              : <p className="muted">Enter your measurements and choose Plan.</p>}
          </section>
          <section className="card">
            <h2>Your measurements</h2>
            {maps.length > 1 && <label>Hold map<select value={mapId} onChange={(e) => { setMapId(e.target.value); setResult(null); }}>{maps.map((m) => <option key={m.id} value={m.id}>{m.name} ({m.holds.length} holds)</option>)}</select></label>}
            <div className="grid2">
              <label>Height (cm)<input type="number" min="100" max="230" value={body.height} data-testid="body-height" onChange={(e) => setBody({ ...body, height: e.target.value })} /></label>
              <label>Wingspan (cm)<input type="number" min="100" max="250" value={body.wingspan} data-testid="body-wingspan" onChange={(e) => setBody({ ...body, wingspan: e.target.value })} /></label>
            </div>
            <p className="muted small-text">Wingspan is fingertip to fingertip with arms out. These stay in this browser and are not stored with the climb.</p>
            <label className="check"><input type="checkbox" checked={rectify} data-testid="rectify" onChange={(e) => setRectify(e.target.checked)} /> Correct distances for the wall's angle, using its bolt holes</label>
            <button className="button primary" data-testid="run-plan" disabled={!valid || !mapId} onClick={() => void plan()}>Plan</button>
            {!valid && (body.height || body.wingspan) && <p className="muted small-text">Enter a height of 100 to 230 cm and a wingspan of 100 to 250 cm.</p>}

            {result && result.status !== "ready" && (
              <div data-testid="plan-needs">
                <h3>{result.status === "no_candidate" ? "No sequence found" : "Still needed"}</h3>
                {result.status === "no_candidate" ? <p>{result.note}</p> : <ul className="plain-list">{result.needs.map((need) => <li key={need}>{need}</li>)}</ul>}
                <a className="button" href={`#/holds/${attemptId}`}>Open the hold editor</a>
              </div>
            )}
            {result?.body && <p className="small-text" data-testid="plan-body">Estimated reach lengths: arm {result.body.arm_cm} cm, leg {result.body.leg_cm} cm, torso {result.body.torso_cm} cm.</p>}
            {candidate && result && (
              <>
                <h3>Candidates to try</h3>
                <div className="row tight" role="tablist">
                  {result.candidates.map((item, index) => <button key={item.id} role="tab" aria-selected={index === active} className={`button small ${index === active ? "active" : ""}`} data-testid="plan-candidate" onClick={() => { setActive(index); setStep(0); }}>{item.label}</button>)}
                </div>
                <p className="small-text">{candidate.move_count} moves. Largest single move {candidate.largest_move_L.toFixed(2)} torso lengths. Tightest reach margin {candidate.tightest_margin_L.toFixed(2)} torso lengths{candidate.tight_moves ? `, with ${candidate.tight_moves} tight move${candidate.tight_moves > 1 ? "s" : ""}` : ""}.</p>
                <p className="small-text"><strong>Start:</strong> {Object.entries(candidate.start).map(([limb, hold]) => `${LIMB_WORD[limb]} ${hold < 0 ? "from the ground" : holdName(hold)}`).join(", ")}</p>
                <ol className="phase-list" data-testid="plan-steps">
                  {candidate.steps.map((item, index) => (
                    <li key={index}><button className={`link ${index === step ? "strong" : ""}`} onClick={() => setStep(index)}>{LIMB_WORD[item.limb]} to {holdName(item.to_hold)}</button> <span className="muted small-text">{item.from_hold < 0 ? "first placement" : `${item.distance_L.toFixed(2)} L move`}, {item.margin_L.toFixed(2)} L margin{item.tight ? ", tight" : ""}</span></li>
                  ))}
                </ol>
                <PerspectiveNote perspective={result.perspective} />
                <details open><summary>Assumptions</summary><ul className="plain-list small-text">{(result.assumptions ?? []).map((text) => <li key={text}>{text}</li>)}</ul></details>
              </>
            )}
          </section>
        </div>
      )}
    </div>
  );
}
