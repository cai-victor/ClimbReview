import { useEffect, useRef, useState } from "react";
import { api, Attempt } from "./api";

/** The outcomes the review understands. Free text is still allowed; these are the quick choices. */
export const OUTCOMES = ["Finished", "Fell", "Not finished"] as const;

/** Outcome as one tap, with room for the climber's own words ("Fell at move 4"). */
export function OutcomeField({ value, onChange, testid = "outcome" }: { value: string; onChange: (value: string) => void; testid?: string }) {
  const chosen = OUTCOMES.find((o) => o.toLowerCase() === value.trim().toLowerCase());
  return (
    <div className="field outcome-field">
      <span className="field-label" id={`${testid}-label`}>Outcome</span>
      <div className="seg" role="group" aria-labelledby={`${testid}-label`}>
        {OUTCOMES.map((option) => (
          <button key={option} type="button" className="button small" aria-pressed={chosen === option} data-testid={`${testid}-${option.toLowerCase().replace(" ", "-")}`}
            onClick={() => onChange(chosen === option ? "" : option)}>{option}</button>
        ))}
      </div>
      <input aria-label="Outcome in your own words" value={value} placeholder="Or in your own words: fell at move 4…" data-testid={`${testid}-text`} onChange={(e) => onChange(e.target.value)} />
      <span className="muted small-text">Used to read the end of the video: a finished climb is not treated as a fall.</span>
    </div>
  );
}

/** One line under the title: what is known about this attempt, and a way to change it. */
export function DetailsLine({ attempt, onEdit }: { attempt: Attempt; onEdit: () => void }) {
  const problem = attempt.problem_label || attempt.route_name;
  const parts = [problem, attempt.grade, attempt.outcome, attempt.climber_label && `Climber: ${attempt.climber_label}`].filter(Boolean);
  return (
    <div className="details-line">
      {parts.length > 0 && <span data-testid="details-summary">{parts.join(" · ")}</span>}
      <button className="link" data-testid="edit-details" onClick={onEdit}>{parts.length ? "Edit details" : "Add the problem, grade and outcome"}</button>
    </div>
  );
}

/** Name, problem, grade, outcome and climber in one place. The problem name is also what Compare matches on. */
export function DetailsDialog({ attempt, open, onClose, onSaved }: { attempt: Attempt; open: boolean; onClose: () => void; onSaved: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const blank = () => ({ title: attempt.title, problem: attempt.problem_label || attempt.route_name || "", grade: attempt.grade ?? "", outcome: attempt.outcome ?? "", climber: attempt.climber_label ?? "" });
  const [form, setForm] = useState(blank);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    const node = dialog.current;
    if (!node) return;
    if (open && !node.open) { setForm(blank()); setError(""); node.showModal(); }
    if (!open && node.open) node.close();
  }, [open]);   // eslint-disable-line react-hooks/exhaustive-deps

  const save = async () => {
    if (!form.title.trim()) { setError("The attempt needs a name."); return; }
    setBusy(true); setError("");
    try {
      await api.patchAttempt(attempt.id, { title: form.title.trim(), route_name: form.problem.trim(), problem_label: form.problem.trim(), grade: form.grade.trim(),
        outcome: form.outcome.trim(), climber_label: form.climber.trim() });
      onSaved(); onClose();
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };

  return (
    <dialog ref={dialog} className="sheet" aria-labelledby="details-title" onClose={onClose} onCancel={onClose} data-testid="details-dialog">
      <form method="dialog" onSubmit={(e) => { e.preventDefault(); void save(); }}>
        <h2 id="details-title">Attempt details</h2>
        <label>Name<input value={form.title} data-testid="details-title" onChange={(e) => setForm({ ...form, title: e.target.value })} /></label>
        <div className="grid2">
          <label>Problem<input value={form.problem} placeholder="Yellow V4 on the cave" data-testid="details-problem" onChange={(e) => setForm({ ...form, problem: e.target.value })} /></label>
          <label>Grade<input value={form.grade} placeholder="V4" data-testid="details-grade" onChange={(e) => setForm({ ...form, grade: e.target.value })} /></label>
        </div>
        <OutcomeField value={form.outcome} onChange={(outcome) => setForm({ ...form, outcome })} testid="details-outcome" />
        <label>Climber<input value={form.climber} placeholder="A name or initials" data-testid="details-climber" onChange={(e) => setForm({ ...form, climber: e.target.value })} /></label>
        <p className="muted small-text">Attempts with the same problem and climber can be compared side by side in the Compare tab.</p>
        {error && <p className="error" role="alert">{error}</p>}
        <div className="sheet-actions">
          <button type="button" className="button" onClick={onClose}>Cancel</button>
          <button type="submit" className="button primary" disabled={busy} data-testid="details-save">{busy ? "Saving…" : "Save"}</button>
        </div>
      </form>
    </dialog>
  );
}
