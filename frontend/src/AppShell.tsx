import { NavLink, Route, Routes } from "react-router-dom";
import { Suspense, lazy, useEffect, useState } from "react";
import PreprocessingWorkspace from "./PreprocessingWorkspace";
import { AnalyzeErrorBoundary } from "./AnalyzeErrorBoundary";
import { fetchJson } from "./lib/http";
import UserScopeSelect from "./UserScopeSelect";

const AnalyzeWorkspace = lazy(() => import("./AnalyzeWorkspace"));

/** True when mounted inside the legacy `index.html` shell (`#tab-spa`); that page provides top Prepare | Analyze tabs. */
function embeddedInLegacyShell(): boolean {
  if (typeof document === "undefined") return false;
  return document.getElementById("preprocess-root")?.closest("#tab-spa") != null;
}

function AnalyzeFallback() {
  return (
    <div className="hint" style={{ padding: "16px" }}>
      Loading Analyze…
    </div>
  );
}

export default function AppShell() {
  const embedded = embeddedInLegacyShell();
  const [username, setUsername] = useState<string | null>(null);

  useEffect(() => {
    if (embedded) return;
    fetchJson<{ user: { username: string } }>("/auth/me")
      .then((data) => setUsername(data.user?.username ?? null))
      .catch(() => setUsername(null));
  }, [embedded]);

  async function logout() {
    try {
      await fetchJson("/auth/logout", { method: "POST" });
    } catch {
      /* ignore */
    }
    window.location.href = "/";
  }

  return (
    <div className="preprocess-scope">
      {!embedded ? (
        <div className="card" style={{ marginBottom: "10px" }}>
          <div className="row" style={{ alignItems: "center", gap: "12px", flexWrap: "wrap" }}>
            <div className="section-title" style={{ margin: 0 }}>
              SERSFlow
            </div>
            <nav className="row" style={{ gap: "8px" }}>
              <NavLink
                to="/"
                end
                className={({ isActive }) => (isActive ? "mini primary" : "mini")}
                style={({ isActive }) => ({ fontWeight: isActive ? 600 : 400 })}
              >
                Pipeline &amp; preview
              </NavLink>
              <NavLink
                to="/analyze"
                className={({ isActive }) => (isActive ? "mini primary" : "mini")}
                style={({ isActive }) => ({ fontWeight: isActive ? 600 : 400 })}
              >
                Features &amp; statistics
              </NavLink>
              {username ? (
                <>
                  <UserScopeSelect />
                  <span className="hint" style={{ margin: 0 }}>
                    {username}
                  </span>
                  <button type="button" className="mini" onClick={() => void logout()}>
                    Log out
                  </button>
                </>
              ) : null}
            </nav>
            <p className="hint" style={{ margin: "8px 0 0", fontSize: "12px" }}>
              Workflow: (1) Save pipeline → (2) Run feature extraction on the <b>full dataset</b> in Features &amp; statistics →
              (3) Export observation table or run PCA / correlation.
            </p>
          </div>
        </div>
      ) : null}

      <Routes>
        <Route path="/" element={<PreprocessingWorkspace />} />
        <Route
          path="/analyze"
          element={
            <AnalyzeErrorBoundary>
              <Suspense fallback={<AnalyzeFallback />}>
                <AnalyzeWorkspace />
              </Suspense>
            </AnalyzeErrorBoundary>
          }
        />
      </Routes>
    </div>
  );
}
