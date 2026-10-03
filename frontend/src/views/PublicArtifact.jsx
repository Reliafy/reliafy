import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import Plot from "../components/Plot.jsx";
import Logo from "../components/Logo.jsx";
import { useAuth } from "../AuthProvider.jsx";
import ResultView from "../components/ResultView.jsx";
import DegradationResultView from "../components/DegradationResultView.jsx";
import ReplacementResult from "../components/ReplacementResult.jsx";
import CompareResult from "../components/CompareResult.jsx";
import FfiResult from "../components/FfiResult.jsx";
import DemoTestResult from "../components/DemoTestResult.jsx";
import PreviewTable from "../components/PreviewTable.jsx";
import RcmTree from "../components/RcmTree.jsx";
import { RollupBadges } from "../components/RcmStatusBadge.jsx";
import PublicRbd from "../components/PublicRbd.jsx";
import { getPublicArtifact, unlockPublicLink } from "../api.js";

// Public, read-only view of a shared artifact (/p/:token) — no account
// needed. Renders the same payloads as the in-app detail pages through the
// same presentational components. This route is its own lazy chunk so the
// marketing pages don't inherit its Plotly dependency. The page is
// deliberately bare — just the brand bar and the content, no marketing nav
// or footer — because it's what an owner (or their agent) hands to a client
// or colleague. The one prompt is "Create free account" at the bar's right,
// for visitors who aren't signed in.

const KIND_LABEL = {
  models: "Fitted life model",
  datasets: "Dataset",
  degradation_models: "Degradation model",
  strategy_analyses: "Strategy analysis",
  rcm_studies: "RCM study",
  fleets: "Fleet failure forecast",
  rbds: "Reliability block diagram",
};

const fmt = (v, dp = 1) =>
  v === null || v === undefined ? "—" : Number(v).toLocaleString(undefined, { maximumFractionDigits: dp });

function FleetView({ a }) {
  const f = a.forecast || {};
  const unit = f.unit || "";
  return (
    <>
      {f.status === "stale" && (
        <div className="card note">{f.reason || "The linked life model is unavailable."}</div>
      )}
      {f.status === "ok" && (
        <div className="stats">
          <div className="stat"><div className="k">Expected failures</div><div className="v">{fmt(f.expected)}</div></div>
          <div className="stat"><div className="k">Likely range (P10–P90)</div><div className="v sm">{fmt(f.interval?.[0])} – {fmt(f.interval?.[1])}</div></div>
          <div className="stat"><div className="k">Horizon</div><div className="v sm">{f.periods} {f.period_label}</div></div>
          <div className="stat"><div className="k">Counting</div><div className="v sm">{f.method === "renewals" ? "with replacement" : "first failures"}</div></div>
        </div>
      )}
      {(a.items || []).length > 0 && (
        <div className="card" style={{ marginTop: "1rem" }}>
          <h2>Items</h2>
          <table className="lib-table">
            <thead>
              <tr>
                <th>Item</th>
                <th>Current use{unit ? ` (${unit})` : ""}</th>
                <th>P(failure)</th>
                <th>Expected failures</th>
              </tr>
            </thead>
            <tbody>
              {a.items.map((it) => {
                const r = (f.per_item || []).find((p) => p.id === it.id) || {};
                return (
                  <tr key={it.id} className="lib-row">
                    <td>{it.name}</td>
                    <td className="lib-n">{fmt(it.current_use, 0)}</td>
                    <td className="lib-n">{r.prob_any === undefined ? "—" : `${(r.prob_any * 100).toFixed(0)}%`}</td>
                    <td className="lib-n">{r.expected === undefined ? "—" : fmt(r.expected, 2)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {f.status === "ok" && (f.per_period || []).some((v) => v > 0) && (
        <div className="card" style={{ marginTop: "1rem" }}>
          <h2>Expected failures per {String(f.period_label || "period").replace(/s$/, "")}</h2>
          <Plot
            data={[{
              type: "bar",
              x: Array.from({ length: f.periods || 0 }, (_, i) => i + 1),
              y: f.per_period,
              marker: { color: "#2f6df6" },
            }]}
            layout={{
              height: 300,
              margin: { l: 46, r: 16, t: 8, b: 42 },
              xaxis: { title: { text: f.period_label || "period" }, dtick: 1 },
              yaxis: { title: { text: "expected failures" } },
              paper_bgcolor: "transparent",
              plot_bgcolor: "transparent",
            }}
            config={{ displayModeBar: false, responsive: true }}
            style={{ width: "100%" }}
          />
        </div>
      )}
    </>
  );
}

function Body({ collection, a, token, unlock }) {
  switch (collection) {
    case "models":
      return <div className="card"><ResultView result={a.results} /></div>;
    case "degradation_models":
      return <div className="card"><DegradationResultView results={a.results} /></div>;
    case "strategy_analyses":
      return (
        <div className="card">
          {a.kind === "optimal_replacement" && <ReplacementResult result={a.results} />}
          {a.kind === "compare_two" && <CompareResult result={a.results} />}
          {a.kind === "failure_finding" && <FfiResult result={a.results} />}
          {a.kind === "demonstration_test" && <DemoTestResult result={a.results} />}
        </div>
      );
    case "datasets":
      return (
        <div className="card">
          {a.preview?.length ? (
            <>
              <div className="ds-section-h">Preview · first {a.preview.length} rows</div>
              <PreviewTable columns={a.preview_columns} rows={a.preview} />
            </>
          ) : (
            <p className="muted-line">No preview available.</p>
          )}
        </div>
      );
    case "rcm_studies":
      return (
        <>
          {a.rollup && <RollupBadges rollup={a.rollup} />}
          <div className="card" style={{ marginTop: "0.8rem" }}>
            <RcmTree functions={a.functions || []} readOnly onChange={() => {}} onEditDecision={() => {}} />
          </div>
        </>
      );
    case "fleets":
      return <FleetView a={a} />;
    case "rbds":
      return <PublicRbd a={a} token={token} unlock={unlock} />;
    default:
      return <div className="card empty">This artifact type doesn't have a public view.</div>;
  }
}

// A protected link's unlock token lives for the tab (sessionStorage), so a
// reload doesn't ask again; storage can be unavailable (private modes).
const unlockKey = (token) => `reliafy.unlock.${token}`;
function readUnlock(token) {
  try {
    return sessionStorage.getItem(unlockKey(token)) || null;
  } catch {
    return null;
  }
}
function storeUnlock(token, value) {
  try {
    if (value) sessionStorage.setItem(unlockKey(token), value);
    else sessionStorage.removeItem(unlockKey(token));
  } catch {
    /* the unlock still works for this page view */
  }
}

const LockIcon = () => (
  <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="1.8"
    strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <rect x="4.5" y="10.5" width="15" height="10" rx="2" />
    <path d="M8 10.5V7.5a4 4 0 0 1 8 0v3" />
  </svg>
);

// The password prompt for a protected link. It knows nothing about what's
// behind it (the server reveals nothing before unlock), so it names nothing.
function PasswordGate({ token, onUnlocked }) {
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const onSubmit = async (e) => {
    e.preventDefault();
    if (!password) return;
    setBusy(true);
    setError(null);
    try {
      const { unlock_token: unlock } = await unlockPublicLink(token, password.trim());
      onUnlocked(unlock);
    } catch (err) {
      setError(err.status === 401 ? "That password isn't right." : err.message);
      setBusy(false);
    }
  };

  return (
    <form className="card share-gate" onSubmit={onSubmit}>
      <div className="share-gate-icon"><LockIcon /></div>
      <h2>This share is password-protected</h2>
      <p className="muted-line">Enter the password you were sent with the link.</p>
      <label className="login-field">
        <span>Password</span>
        <input
          type="password"
          autoFocus
          autoComplete="off"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
      </label>
      {error && <div className="error" role="alert">{error}</div>}
      <button type="submit" disabled={busy || !password}>{busy ? "Checking…" : "Unlock"}</button>
    </form>
  );
}

export default function PublicArtifact() {
  const { token } = useParams();
  const { user, loading } = useAuth();
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [locked, setLocked] = useState(false);
  const [unlock, setUnlock] = useState(() => readUnlock(token));

  useEffect(() => {
    let live = true;
    setData(null);
    setError(null);
    setLocked(false);
    getPublicArtifact(token, unlock)
      .then((d) => live && setData(d))
      .catch((e) => {
        if (!live) return;
        if (e.passwordRequired) {
          // No unlock yet, or it expired / the password was changed.
          if (unlock) {
            storeUnlock(token, null);
            setUnlock(null);
          }
          setLocked(true);
        } else {
          setError(e.message);
        }
      });
    return () => {
      live = false;
    };
  }, [token, unlock]);

  const onUnlocked = (value) => {
    storeUnlock(token, value);
    setUnlock(value);
  };

  // Share links are private to whoever holds them: keep them out of search.
  useEffect(() => {
    const meta = document.createElement("meta");
    meta.name = "robots";
    meta.content = "noindex";
    document.head.appendChild(meta);
    return () => meta.remove();
  }, []);

  // Name the tab after the shared artifact (the SPA shell's title is generic).
  useEffect(() => {
    if (!data?.artifact?.name) return undefined;
    const previous = document.title;
    document.title = `${data.artifact.name} — ${KIND_LABEL[data.collection] || "Analysis"} · Reliafy`;
    return () => {
      document.title = previous;
    };
  }, [data]);

  return (
    <div className="landing">
      <header className="landing-nav share-bar">
        <Link className="brand" to="/">
          <Logo size={26} />
          <span className="brand-name">Reliafy</span>
        </Link>
        {/* Only once auth has settled, so a signed-in viewer never sees it flash. */}
        {!loading && !user && (
          <Link className="cta cta-solid" to="/login?signup">Create free account</Link>
        )}
      </header>
      <div className="public-artifact">
        {error && (
          <div className="card empty" style={{ margin: "3rem auto", maxWidth: 520 }}>
            <h2>Link unavailable</h2>
            <p>{error}</p>
          </div>
        )}
        {locked && !error && <PasswordGate token={token} onUnlocked={onUnlocked} />}
        {!error && !locked && !data && (
          <div className="card empty" style={{ margin: "3rem auto", maxWidth: 520 }}>Loading…</div>
        )}
        {data && (
          <div className="app" style={{ margin: "0 auto", maxWidth: 1080 }}>
            <header>
              <div>
                <div className="crumb">{KIND_LABEL[data.collection] || "Analysis"} · shared by {data.shared_by}</div>
                <h1>{data.artifact.name}</h1>
              </div>
            </header>
            <Body collection={data.collection} a={data.artifact} token={token} unlock={unlock} />
          </div>
        )}
      </div>
    </div>
  );
}

