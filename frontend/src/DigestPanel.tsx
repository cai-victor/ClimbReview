import { clock, Digest, Limb, percent } from "./api";

const ORDER: Limb[] = ["left_foot", "right_foot", "left_wrist", "right_wrist"];

export function DigestPanel({ digest, onEvent }: { digest: Digest; onEvent: (id: string) => void }) {
  return (
    <section className="card" data-testid="digest">
      <h2>What moved and when</h2>
      <table className="facts"><thead><tr><th>Limb</th><th>Episodes</th><th>Time analyzable</th><th>Largest movement</th></tr></thead><tbody>
        {ORDER.map((limb) => {
          const item = digest.limbs[limb];
          return (
            <tr key={limb}>
              <td>{item.label}</td>
              <td>{item.episodes === null ? "unavailable" : item.episodes}{item.uncertain_episodes > 0 ? ` (${item.uncertain_episodes} uncertain)` : ""}</td>
              <td>{percent(item.analyzable_fraction)}</td>
              <td>{item.largest ? <button className="link" onClick={() => onEvent(item.largest!.event_id)}>{clock(item.largest.start_ms)}: {item.largest.text}</button> : "none"}</td>
            </tr>
          );
        })}
      </tbody></table>
      <p className="muted small-text">{digest.meaning} L means torso lengths in the picture.</p>

      {digest.phases.length > 0 && (<>
        <h3>Sequence of movements</h3>
        <ol className="phase-list">
          {digest.phases.map((phase) => (
            <li key={phase.start_ms}><button className="link" onClick={() => onEvent(phase.event_ids[0])}>{clock(phase.start_ms)}</button> {phase.text}</li>
          ))}
        </ol>
      </>)}

      {digest.rewatch.length > 0 && (<>
        <h3>Worth rewatching</h3>
        <ul className="plain-list">{digest.rewatch.map((item) => <li key={item.event_id}><button className="link" onClick={() => onEvent(item.event_id)}>{clock(item.start_ms)}</button> {item.reason}</li>)}</ul>
      </>)}

      {digest.repeated.length > 0 && (<>
        <h3>Repeated movement</h3>
        <ul className="plain-list">{digest.repeated.map((item) => <li key={item.start_ms + item.limb}><button className="link" onClick={() => onEvent(item.event_ids[0])}>{clock(item.start_ms)}</button> {item.text}</li>)}</ul>
      </>)}

      {digest.limits.length > 0 && (<>
        <h3>Where tracking prevents a conclusion</h3>
        <ul className="plain-list">{digest.limits.map((item) => <li key={item.limb}>{item.text}</li>)}</ul>
      </>)}

      {digest.prompts.length > 0 && (<>
        <h3>Questions to reflect on</h3>
        <ul className="plain-list">{digest.prompts.map((prompt) => <li key={prompt}>{prompt}</li>)}</ul>
      </>)}
    </section>
  );
}
