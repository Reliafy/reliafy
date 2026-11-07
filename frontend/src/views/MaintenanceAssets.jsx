import { useCallback, useEffect, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { addSampleProduct, listMaintenancePlaces, listProductItems } from "../api.js";
import RegisterList, { CountCell } from "../components/RegisterList.jsx";
import { PlusIcon } from "../components/LibRows.jsx";
import { DeleteTreeModal, DeletedToast } from "../components/DeleteTree.jsx";
import { fmtDate } from "../components/MaintenanceParts.jsx";
import { NewLocationModal } from "./MaintenanceLists.jsx";
import {
  NOT_PLACED_PATH, assetPath, assetsSummary, dueText, insideText, openWorkPath, placePath,
} from "../maintenanceAssets.js";
import { OPEN_SAMPLE_UNITS_LABEL, sampleUnitsPath } from "../sampleProduct.js";
import "./Maintenance.css";

const HELP = { guide: "rcm-on-your-asset-tree" };

// Assets (the menu entry's landing page): the assets themselves, the top-level
// places (a house, a site, a plant), each with what it holds anywhere inside
// it. The positions at no place are one row at the end, opening the Explorer
// filtered to them. Opening an asset opens the Explorer on it; Parts and stock
// and Classes are tabs there. The same page as Products (RegisterList), with
// the maintenance columns: open work and what's due.
export default function MaintenanceAssets() {
  const navigate = useNavigate();
  const [view, setView] = useState(null);
  const [modal, setModal] = useState(false);
  const [error, setError] = useState(null);
  const [adding, setAdding] = useState(false);
  const reload = useCallback(() => {
    listMaintenancePlaces().then(setView).catch((e) => setError(e.message));
  }, []);
  useEffect(() => reload(), [reload]);
  // Delete… on a row: the asset with everything at it ({id, name}), then the toast with Undo.
  const [deleting, setDeleting] = useState(null);
  const location = useLocation();
  const [deleted, setDeleted] = useState(() => location.state?.deleted || null);
  useEffect(() => {
    // Shown once: a reload of the page doesn't bring the toast back.
    if (location.state?.deleted) navigate(`${location.pathname}${location.search}`, { replace: true, state: null });
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const rest = view?.not_placed;
  const horizon = view?.horizon_days ?? 30;
  const newAsset = <button onClick={() => setModal(true)}><PlusIcon /> New asset</button>;
  // The sample quadcopter: the first of the three items built from the sample
  // product, on its own tree (the sample is added first when there's none).
  const openSample = () => {
    if (adding) return;
    setAdding(true);
    setError(null);
    sampleUnitsPath(addSampleProduct, listProductItems)
      .then((path) => navigate(path))
      .catch((e) => { setError(`The sample quadcopter didn't open: ${e.message}`); setAdding(false); });
  };
  const sampleButton = (
    <button type="button" className="secondary" onClick={openSample} disabled={adding}>{adding ? "Opening…" : OPEN_SAMPLE_UNITS_LABEL}</button>
  );
  const columns = [
    { key: "positions", label: "Positions", num: true, cell: (p) => p.positions },
    { key: "items", label: "Items", num: true, cell: (p) => p.items },
    {
      key: "work", label: "Open work", num: true,
      cell: (p) => <CountCell n={p.open_work_orders} to={p.id ? openWorkPath(p.id) : null}
                              label={`${p.open_work_orders} open work order${p.open_work_orders === 1 ? "" : "s"} at ${p.name}`} />,
    },
    { key: "due", label: `Due in ${horizon} days`, cell: (p) => <Due row={p} /> },
  ];
  const notPlaced = rest?.positions > 0 && (
    <tr className="lib-row maint-not-placed" onClick={() => navigate(NOT_PLACED_PATH)}>
      <td>
        <Link to={NOT_PLACED_PATH} className="lib-name maint-node-name" onClick={(e) => e.stopPropagation()}>
          Not at a place yet</Link>
        <div className="lib-date">Positions with no place set. Set one on a position's page, or on the position above it.</div>
      </td>
      {columns.map((c) => (
        <td key={c.key} className={c.num ? "num" : undefined} data-label={c.label}>{c.cell({ ...rest, name: "no place" })}</td>
      ))}
      <td />
    </tr>
  );

  return (
    <>
      <RegisterList
        title="Assets" purpose="The places you look after, and everything at each one."
        help={HELP} primary={newAsset}
        menu={<button type="button" className="ovm-item" onClick={openSample} disabled={adding}>{OPEN_SAMPLE_UNITS_LABEL}</button>}
        error={error} rows={view ? view.places || [] : null} noun={["asset", "assets"]}
        count={assetsSummary(view)} search={(p) => [p.name, p.description]}
        name={(p) => ({ to: assetPath(p.id), label: p.name, sub: [p.description, insideText(p)].filter(Boolean).join(" · ") })}
        columns={columns} after={notPlaced || null} onDelete={setDeleting}
        empty={{
          title: "No assets yet",
          text: "An asset is a place you look after: a house, a site, a plant. Add one, then add the rooms or areas inside it and say where each position is. Or open the sample quadcopter: one of three built from the sample product, with its flight hours and failure reports.",
          sample: sampleButton,
          guide: "How the asset tree works",
        }}
      />
      {modal && <NewLocationModal asset locations={[]} onClose={() => setModal(false)}
                                  onDone={(l) => navigate(placePath(l.id))} />}
      {deleting && (
        <DeleteTreeModal kind="location" id={deleting.id} name={deleting.name} onClose={() => setDeleting(null)}
                         onDone={(answer, done) => { setDeleting(null); setDeleted(done); reload(); }} />
      )}
      {deleted && <DeletedToast key={deleted.id} deleted={deleted} onClose={() => setDeleted(null)} onRestored={reload} />}
    </>
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
