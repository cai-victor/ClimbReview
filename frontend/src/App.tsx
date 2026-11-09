import { useEffect, useState } from "react";
import { AttemptPage } from "./AttemptPage";
import { Library } from "./Library";

function currentRoute() {
  const match = window.location.hash.match(/^#\/attempt\/([0-9a-f]{32})/);
  return match ? match[1] : null;
}

export function App() {
  const [attemptId, setAttemptId] = useState(currentRoute);
  useEffect(() => {
    const update = () => setAttemptId(currentRoute());
    window.addEventListener("hashchange", update);
    return () => window.removeEventListener("hashchange", update);
  }, []);
  return (
    <div className="app">
      <header className="topbar">
        <a href="#/" className="brand">ClimbReview</a>
        <span className="muted">Runs only on this computer</span>
      </header>
      <main>{attemptId ? <AttemptPage key={attemptId} id={attemptId} /> : <Library />}</main>
    </div>
  );
}
