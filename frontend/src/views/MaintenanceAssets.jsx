import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { listMaintenancePlaces } from "../api.js";
import { SectionHeader } from "../components/SectionPage.jsx";
import ListSearch, { matches } from "../components/ListSearch.jsx";
import { PlusIcon } from "../components/LibRows.jsx";
import { fmtDate } from "../components/MaintenanceParts.jsx";
import { NewLocationModal } from "./MaintenanceLists.jsx";
import {
  NOT_PLACED_PATH, POSITIONS_PATH, assetPath, assetsSummary, dueText, insideText, openWorkPath, placePath,
} from "../maintenanceAssets.js";
import "./Maintenance.css";

// Operate › Assets: the assets themselves, the top-level places (a house, a
// site, a plant), each with what it holds anywhere inside it. The positions at
// no place are one row at the end, opening the Explorer filtered to them.
export default function MaintenanceAssets() {
  const navigate = useNavigate();
  const [view, setView] = useState(null);
  const [query, setQuery] = useState("");
  const [modal, setModal] = useState(false);
  const [error, setError] = useState(null);
  useEffect(() => {
    listMaintenancePlaces().then(setView).catch((e) => setError(e.message));
  }, []);

  const places = view?.places || [];
  const rest = view?.not_placed;
  const visible = places.filter((p) => matches(query, p.name, p.description));
  const newAsset = <button onClick={() => setModal(true)}><PlusIcon /> New asset</button>;

  return (
    <div className="app">
      <SectionHeader title="Assets" purpose="The places you look after, and everything at each one."
                     primary={newAsset} />
      {error && <div className="card error">{error}</div>}
      {view === null ? (
        !error && <div className="card empty">Loading…</div>
      ) : places.length === 0 ? (
        <div className="card empty section-empty">
          <h2>No assets yet</h2>
          <p>An asset is a place you look after: a house, a site, a plant. Add one, then add the rooms or areas
            inside it and say where each position is.</p>
          <div className="section-empty-action">{newAsset}</div>
          <p className="section-empty-more">
            {rest?.positions > 0
              ? <>Your {rest.positions === 1 ? "position isn't" : `${rest.positions} positions aren't`} at a place
                yet: <Link to={NOT_PLACED_PATH}>see {rest.positions === 1 ? "it" : "them"}</Link>.</>
              : <>Or start with the <Link to={POSITIONS_PATH}>positions</Link>: what each slot in your
                plant does.</>}
          </p>
        </div>
      ) : (
        <>
          <div className="tablebar section-tablebar">
            <span className="count">{query ? `${visible.length} of ${places.length} assets` : assetsSummary(view)}</span>
            <span className="grow" />
            <ListSearch value={query} onChange={setQuery} placeholder="Search assets…" />
          </div>
          <div className="lib maint-scroll">
            <table className="lib-table maint-assets">
              <thead>
                <tr><th>Asset</th><th className="num">Positions</th><th className="num">Items</th>
                  <th className="num">Open work</th><th>Due in {view.horizon_days} days</th></tr>
              </thead>
              <tbody>
                {visible.map((p) => (
                  <tr key={p.id} className="lib-row" onClick={() => navigate(assetPath(p.id))}>
                    <td>
                      <Link to={assetPath(p.id)} className="lib-name maint-node-name" onClick={(e) => e.stopPropagation()}>
                        {p.name}</Link>
                      {(p.description || p.locations > 0) && (
                        <div className="lib-date">{[p.description, insideText(p)].filter(Boolean).join(" · ")}</div>
                      )}
                    </td>
                    <td className="num" data-label="Positions">{p.positions}</td>
                    <td className="num" data-label="Items">{p.items}</td>
                    <td className="num" data-label="Open work">{p.open_work_orders > 0
                      ? <Link to={openWorkPath(p.id)} onClick={(e) => e.stopPropagation()}
                              aria-label={`${p.open_work_orders} open work order${p.open_work_orders === 1 ? "" : "s"} at ${p.name}`}>{p.open_work_orders}</Link>
                      : <span className="lib-date">0</span>}</td>
                    <td data-label={`Due in ${view.horizon_days} days`}><Due row={p} /></td>
                  </tr>
                ))}
                {rest?.positions > 0 && (
                  <tr className="lib-row maint-not-placed" onClick={() => navigate(NOT_PLACED_PATH)}>
                    <td>
                      <Link to={NOT_PLACED_PATH} className="lib-name maint-node-name" onClick={(e) => e.stopPropagation()}>
                        Not at a place yet</Link>
                      <div className="lib-date">Positions with no place set. Set one on a position's page, or on
                        the position above it.</div>
                    </td>
                    <td className="num" data-label="Positions">{rest.positions}</td>
                    <td className="num" data-label="Items">{rest.items}</td>
                    <td className="num" data-label="Open work">{rest.open_work_orders || <span className="lib-date">0</span>}</td>
                    <td data-label={`Due in ${view.horizon_days} days`}><Due row={rest} /></td>
                  </tr>
                )}
              </tbody>
            </table>
            {!visible.length && <p className="section-nomatch">No asset matches.</p>}
          </div>
        </>
      )}
      {modal && <NewLocationModal asset locations={[]} onClose={() => setModal(false)}
                                  onDone={(l) => navigate(placePath(l.id))} />}
    </div>
  );
}

function Due({ row }) {
  const { text, overdue } = dueText(row, fmtDate);
  return (
    <>
      <span className={row.due ? undefined : "lib-date"}>{text}</span>
      {overdue && <div className="maint-overdue">{overdue}</div>}
    </>
  );
}
