import { useEffect, useState } from "react";
import { Annotate } from "./Annotate";
import { AttemptPage } from "./AttemptPage";
import { HoldEditor } from "./HoldEditor";
import { Library } from "./Library";
import { Planner } from "./Planner";

function currentRoute(): { page: "attempt" | "annotate" | "holds" | "plan"; id: string } | null {
  const match = window.location.hash.match(/^#\/(attempt|annotate|holds|plan)\/([0-9a-f]{32})/);
  return match ? { page: match[1] as "attempt" | "annotate" | "holds" | "plan", id: match[2] } : null;
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
        : route?.page === "plan" ? <Planner key={route.id} attemptId={route.id} />
        : route?.page === "holds" ? <HoldEditor key={route.id} attemptId={route.id} />
        : route ? <AttemptPage key={route.id} id={route.id} /> : <Library />}</main>
    </div>
  );
}
