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
        <a href="#/" className="brand" aria-label="ClimbReview home">
          <span className="brand-mark" aria-hidden="true">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round"><path d="M3 20 9.5 8l4 6 2.5-4L21 20Z" /><circle cx="17" cy="5" r="1.6" fill="#fff" stroke="none" /></svg>
          </span>
          ClimbReview
        </a>
        <nav className="topnav" aria-label="Main">
          <a href="#/" aria-current={route ? undefined : "page"}>Attempts</a>
          <span className="local" title="Videos, analysis and notes are stored only on this computer"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><rect x="5" y="11" width="14" height="9" rx="2" /><path d="M8 11V8a4 4 0 0 1 8 0v3" /></svg>Stays on this computer</span>
        </nav>
      </header>
      <main>{route?.page === "annotate" ? <Annotate key={route.id} attemptId={route.id} />
        : route?.page === "plan" ? <Planner key={route.id} attemptId={route.id} />
        : route?.page === "holds" ? <HoldEditor key={route.id} attemptId={route.id} />
        : route ? <AttemptPage key={route.id} id={route.id} /> : <Library />}</main>
      <footer className="footer">ClimbReview describes what the camera saw. Its suggestions are things to test on the wall, not verdicts.</footer>
    </div>
  );
}
