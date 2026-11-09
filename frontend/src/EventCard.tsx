import { useState } from "react";
import { api, ClimbEvent, clock, Review } from "./api";

export const eventTitle = (event: ClimbEvent) =>
  event.type === "low_movement" ? "Low visible movement" : `${event.hand === "left" ? "Left" : "Right"} wrist movement`;

const TAGS: [string, string][] = [
  ["planned_rest", "Planned rest"], ["planning_next_move", "Planning next move"],
  ["intentional_dynamic_movement", "Intentional dynamic movement"], ["other", "Other"],
];

export function EventCard({ event, runId, selected, onSelect, onSaved }: {
  event: ClimbEvent; runId: string; selected: boolean; onSelect: () => void; onSaved: (review: Review) => void;
}) {
  const [review, setReview] = useState(event.review);
  const [status, setStatus] = useState("");

  const save = async (next: Review) => {
    setReview(next);
    try { onSaved(await api.putReview(runId, event.id, next)); setStatus("Saved"); }
    catch (e) { setStatus((e as Error).message); }
  };
  const option = (name: keyof Review, value: string, label: string) => (
    <label className="choice">
      <input type="radio" name={`${event.id}-${name}`} checked={review[name] === value} onChange={() => save({ ...review, [name]: value })} />
      {label}
    </label>
  );

  return (
    <article id={`card-${event.id}`} className={`card event-card ${selected ? "selected" : ""}`} data-testid="event-card">
      <button className="event-head" onClick={onSelect}>
        <strong>{eventTitle(event)}</strong>
        <span>{clock(event.start_ms)} to {clock(event.end_ms)}</span>
      </button>
      <p><span className="label">Observed</span> {event.feedback.observation}</p>
      <p><span className="label">Could be</span> {event.feedback.interpretation}</p>
      <p><span className="label">Reflect</span> {event.feedback.reflection_question}</p>
      <details>
        <summary>Evidence · tracking {event.tracking_quality.label}</summary>
        <p className="muted small-text">The tracking label describes how well the joints were seen. It is not the chance that this event is correct.</p>
        <dl className="evidence">
          {Object.entries(event.evidence).filter(([, v]) => v !== null && typeof v !== "object").map(([key, value]) => (
            <div key={key}><dt>{key.replaceAll("_", " ")}</dt><dd>{String(value)}</dd></div>
          ))}
          <div><dt>median required-joint visibility</dt><dd>{event.tracking_quality.median_min_required_visibility}</dd></div>
        </dl>
      </details>
      <fieldset><legend>Was this event really visible?</legend>
        {option("detection_judgment", "confirmed", "Yes")}{option("detection_judgment", "incorrect", "Incorrect detection")}{option("detection_judgment", "cannot_tell", "Cannot tell")}
      </fieldset>
      <fieldset><legend>Was it useful to review?</legend>
        {option("usefulness", "useful", "Useful")}{option("usefulness", "not_useful", "Not useful")}
      </fieldset>
      <fieldset><legend>Context (optional)</legend>
        {TAGS.map(([value, label]) => (
          <label className="choice" key={value}>
            <input type="checkbox" checked={review.context_tags.includes(value)}
              onChange={(e) => save({ ...review, context_tags: e.target.checked ? [...review.context_tags, value] : review.context_tags.filter((t) => t !== value) })} />
            {label}
          </label>
        ))}
      </fieldset>
      <label>Note<textarea data-testid="event-note" value={review.note} onChange={(e) => setReview({ ...review, note: e.target.value })} onBlur={() => save(review)} /></label>
      {status && <span className="muted small-text" role="status">{status}</span>}
    </article>
  );
}
