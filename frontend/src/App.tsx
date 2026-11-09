import { useEffect, useState } from "react";
import { Annotate } from "./Annotate";
import { AttemptPage } from "./AttemptPage";
import { Library } from "./Library";

function currentRoute(): { page: "attempt" | "annotate"; id: string } | null {
  const match = window.location.hash.match(/^#\/(attempt|annotate)\/([0-9a-f]{32})/);
  return match ? { page: match[1] as "attempt" | "annotate", id: match[2] } : null;
}

export function App() {
  const [route, setRoute] = useState(currentRoute);
  useEffect(() => {
    const update = () => setRoute(currentRoute());
    window.addEventListener("hashchange", update);
    return () => window.removeEventListener("hashchange", update);
  }, []);
  return (
    <div className="app">
      <header className="topbar">
        <a href="#/" className="brand">ClimbReview</a>
        <span className="muted">Runs only on this computer</span>
      </header>
      <main>{route?.page === "annotate" ? <Annotate key={route.id} attemptId={route.id} />
        : route ? <AttemptPage key={route.id} id={route.id} /> : <Library />}</main>
    </div>
  );
}
