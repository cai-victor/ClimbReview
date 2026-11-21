import { useCallback, useEffect, useRef, useState } from "react";
import { api, Attempt, holdApi, HoldMap, PlanResult } from "./api";
import { BetaFigure, CandidateDetail } from "./BetaView";
import { PerspectiveNote } from "./Performance";

const STORE = "climbreview.body";
const CM_PER_INCH = 2.54;
type Unit = "cm" | "in";
type Body = { height: string; wingspan: string; unit: Unit };          // lengths are kept in centimeters, whatever unit is shown
const saved = (): Body => {
  const blank: Body = { height: "", wingspan: "", unit: "cm" };
  try { return { ...blank, ...JSON.parse(window.localStorage.getItem(STORE) ?? "{}") }; } catch { return blank; }
};
const feetInches = (cm: number) => { const total = Math.round(cm / CM_PER_INCH); return { feet: Math.floor(total / 12), inches: total % 12 }; };
const showLength = (cm: number, unit: Unit) => (unit === "cm" ? `${Math.round(cm)} cm` : `${(cm / CM_PER_INCH).toFixed(1)} in`);

/** A length typed as centimeters, or as feet and inches. The value passed up is always centimeters. */
function LengthField({ label, value, unit, onChange, testid }: { label: string; value: string; unit: Unit; onChange: (cm: string) => void; testid: string }) {
  const cm = parseFloat(value);
  if (unit === "cm") {
    return <label>{label} (cm)<input type="number" min="100" max="250" value={value} data-testid={testid} onChange={(e) => onChange(e.target.value)} /></label>;
  }
  const parts = Number.isFinite(cm) ? feetInches(cm) : { feet: "", inches: "" };
  const set = (feet: string, inches: string) => {
    const total = (parseFloat(feet) || 0) * 12 + (parseFloat(inches) || 0);
    onChange(total > 0 ? String(Math.round(total * CM_PER_INCH * 10) / 10) : "");
  };
  return (
    <fieldset className="length-field"><legend>{label}</legend>
      <label>ft<input type="number" min="3" max="8" value={parts.feet} data-testid={`${testid}-ft`} onChange={(e) => set(e.target.value, String(parts.inches))} /></label>
      <label>in<input type="number" min="0" max="11" value={parts.inches} data-testid={`${testid}-in`} onChange={(e) => set(String(parts.feet), e.target.value)} /></label>
    </fieldset>
  );
}

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
  const request = useRef(0);

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
      const asked = ++request.current;
      const answer = await holdApi.plan(mapId, height, wingspan, rectify);
      if (asked !== request.current) return;            // a newer request was made while this one was running
      setResult(answer); setActive(0); setStep(0);
    } catch (e) { setError((e as Error).message); }
  }, [mapId, height, wingspan, body, rectify]);

  if (!attempt) return <div className="page">{error ? <p className="error" role="alert">{error}</p> : <p className="muted">Loading…</p>}</div>;
  const current = maps.find((m) => m.id === mapId) ?? null;
  const candidate = result?.candidates[Math.min(active, result.candidates.length - 1)] ?? null;
  const torso = result?.body?.torso_cm ?? 0;

  return (
    <div className="page">
      <a className="back" href={`#/attempt/${attemptId}`}>← Back to {attempt.kind === "photo" ? "the photo" : "the review"}</a>
      <div className="page-head"><h1>Plan a route <span className="muted small-text">{attempt.title}</span></h1><a className="button" href={`#/holds/${attemptId}`}>Mark route holds</a></div>
      <p className="blind-note" role="note">These are ideas from 2D geometry on holds you confirmed, limited to positions a person can get into. The picture cannot show hold quality or balance, so try them on the wall. None is the best or easiest beta.</p>
      {error && <p className="error" role="alert">{error}</p>}
      {maps.length === 0 ? (
        <section className="card" data-testid="planner-no-map"><p>This climb has no marked holds yet. Mark the route first, then come back to plan.</p><a className="button primary" href={`#/holds/${attemptId}`}>Mark route holds</a></section>
      ) : (
        <div className="hold-layout">
          <section className="card">
            {result?.hold_map
              ? <BetaFigure map={result.hold_map} candidate={candidate} position={candidate ? Math.min(step, candidate.steps.length) : 0} width={result.hold_map.width} height={result.hold_map.height} />
              : current
                ? <><BetaFigure map={{ ...current, hold_count: current.holds.length, usable: true, message: "", alignment: null }} candidate={null} position={0} width={current.width} height={current.height} />
                    <p className="muted small-text">{current.name}: {current.holds.length} marked hold{current.holds.length === 1 ? "" : "s"}. Enter your measurements and choose Plan.</p></>
                : <p className="muted">Enter your measurements and choose Plan.</p>}
          </section>
          <section className="card">
            <div className="panel-head"><h2>Your measurements</h2>
              <div className="seg" role="group" aria-label="Units">
                <button className="button small" aria-pressed={body.unit === "cm"} data-testid="unit-cm" onClick={() => setBody({ ...body, unit: "cm" })}>cm</button>
                <button className="button small" aria-pressed={body.unit === "in"} data-testid="unit-in" onClick={() => setBody({ ...body, unit: "in" })}>ft, in</button>
              </div>
            </div>
            {maps.length > 1 && <label>Hold map<select value={mapId} onChange={(e) => { setMapId(e.target.value); setResult(null); }}>{maps.map((m) => <option key={m.id} value={m.id}>{m.name} ({m.holds.length} holds)</option>)}</select></label>}
            <div className="grid2">
              <LengthField label="Height" value={body.height} unit={body.unit} testid="body-height" onChange={(cm) => setBody({ ...body, height: cm })} />
              <LengthField label="Wingspan" value={body.wingspan} unit={body.unit} testid="body-wingspan" onChange={(cm) => setBody({ ...body, wingspan: cm })} />
            </div>
            <p className="muted small-text">Wingspan is fingertip to fingertip with arms out. These stay in this browser and are not stored with the climb.</p>
            <label className="check"><input type="checkbox" checked={rectify} data-testid="rectify" onChange={(e) => setRectify(e.target.checked)} /> Correct distances for the wall's angle, using its bolt holes</label>
            <button className="button primary" data-testid="run-plan" disabled={!valid || !mapId} onClick={() => void plan()}>Plan</button>
            {!valid && (body.height || body.wingspan) && <p className="muted small-text">{body.unit === "cm" ? "Enter a height of 100 to 230 cm and a wingspan of 100 to 250 cm." : "Enter a height of 3 ft 4 in to 7 ft 6 in and a wingspan of 3 ft 4 in to 8 ft 2 in."}</p>}

            {result && result.status !== "ready" && (
              <div data-testid="plan-needs">
                <h3>{result.status === "no_candidate" ? "No sequence found" : "Still needed"}</h3>
                {result.status === "no_candidate" ? <p>{result.note}</p> : <ul className="plain-list">{result.needs.map((need) => <li key={need}>{need}</li>)}</ul>}
                <a className="button" href={`#/holds/${attemptId}`}>Open the hold editor</a>
              </div>
            )}
            {result?.scale_check && !result.scale_check.plausible && <p className="notice-text small-text" role="alert" data-testid="plan-scale-warning">{result.scale_check.message} <a href={`#/holds/${attemptId}`}>Open the hold editor</a></p>}
            {!result && current?.scale_check && !current.scale_check.plausible && <p className="notice-text small-text" role="alert">{current.scale_check.message}</p>}
            {result?.body && <p className="small-text" data-testid="plan-body">Estimated reach lengths: arm {showLength(result.body.arm_cm, body.unit)}, leg {showLength(result.body.leg_cm, body.unit)}, torso {showLength(result.body.torso_cm, body.unit)}.</p>}
            {candidate && result && (
              <>
                <h3>Candidates to try</h3>
                <div className="row tight" role="group" aria-label="Sequence shown">
                  {result.candidates.map((item, index) => <button key={item.id} aria-pressed={index === active} className="button small" data-testid="plan-candidate" onClick={() => { setActive(index); setStep(0); }}>{item.label}</button>)}
                </div>
                <CandidateDetail candidate={candidate} position={Math.min(step, candidate.steps.length)} onPosition={setStep} length={(value) => showLength(value * torso, body.unit)} testid="plan" />
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
