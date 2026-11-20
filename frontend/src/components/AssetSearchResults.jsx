import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { searchAssets } from "../api.js";
import LoadFailed from "./LoadFailed.jsx";
import { itemPagePath } from "../products.js";
import { itemHitText, matchesText, positionHitText } from "../maintenanceAssets.js";

const positionPath = (id) => `/asset-register/positions/${encodeURIComponent(id)}`;

// Under the Assets list while there's a query: the positions (by name or tag, P-101)
// and items (by name, serial or part number, built ones too) inside the assets, each
// with the asset it's at. `shown`: how many assets the list itself kept, so "nothing
// matches" is said only when nothing at all does.
export default function AssetSearchResults({ query, shown }) {
  const [state, setState] = useState({ q: null, found: null, error: null });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const ctl = new AbortController();
    // A short wait so each keystroke doesn't ask the server.
    const t = setTimeout(() => {
      searchAssets(query, { signal: ctl.signal })
        .then((found) => setState({ q: query, found, error: null }))
        .catch((e) => { if (e?.name !== "AbortError") setState({ q: query, found: null, error: e }); });
    }, 250);
    return () => { clearTimeout(t); ctl.abort(); };
  }, [query, attempt]);

  const found = state.q === query ? state.found : null;
  if (state.error && state.q === query) {
    return <LoadFailed what="Couldn't search the positions and items inside your assets." error={state.error}
                       onRetry={() => { setState({ q: null, found: null, error: null }); setAttempt((n) => n + 1); }} />;
  }
  if (!found) return <p className="section-nomatch" aria-live="polite">Searching positions and items…</p>;
  const count = matchesText(found);
  if (!count) {
    return (
      <p className="section-nomatch" aria-live="polite">
        {shown ? "No position or item matches either."
          : `Nothing matches “${query}”. Search by an asset's name, a position's name or tag (P-101), or an item's serial.`}
      </p>
    );
  }
  return (
    <section className="reg-found" aria-live="polite">
      <div className="tablebar section-tablebar"><span className="count">{count}</span></div>
      <div className="lib maint-scroll">
        <table className="lib-table reg-table reg-found-table">
          {found.positions.length > 0 && (
            <Rows heading="Position" rows={found.positions.map((p) => ({ id: p.id, to: positionPath(p.id), ...positionHitText(p) }))} />
          )}
          {found.items.length > 0 && (
            <Rows heading="Item" rows={found.items.map((i) => ({ id: i.id, to: itemPagePath(i.id), ...itemHitText(i) }))} />
          )}
        </table>
      </div>
    </section>
  );
}

function Rows({ heading, rows }) {
  const navigate = useNavigate();
  return (
    <>
      <thead><tr><th>{heading}</th></tr></thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.id} className="lib-row" onClick={() => navigate(r.to)}>
            <td>
              <Link to={r.to} className="lib-name maint-node-name" onClick={(e) => e.stopPropagation()}>{r.title}</Link>
              {r.sub && <div className="lib-date reg-sub" title={r.sub}>{r.sub}</div>}
            </td>
          </tr>
        ))}
      </tbody>
    </>
  );
}
