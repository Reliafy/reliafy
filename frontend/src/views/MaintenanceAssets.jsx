import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { addSampleTruck as postSampleTruck, listMaintenancePlaces } from "../api.js";
import RegisterList, { CountCell } from "../components/RegisterList.jsx";
import { PlusIcon } from "../components/LibRows.jsx";
import { fmtDate } from "../components/MaintenanceParts.jsx";
import { useConfirm } from "../components/ConfirmProvider.jsx";
import { NewLocationModal } from "./MaintenanceLists.jsx";
import {
  NOT_PLACED_PATH, assetPath, assetsSummary, dueText, insideText, openWorkPath, placePath,
} from "../maintenanceAssets.js";
import { EXPLORER_PATH } from "../navigation.js";
import { SAMPLES, addSample } from "../sampleTruck.js";
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
  const confirm = useConfirm();
  const [view, setView] = useState(null);
  const [modal, setModal] = useState(false);
  const [error, setError] = useState(null);
  const [adding, setAdding] = useState(false);
  useEffect(() => {
    listMaintenancePlaces().then(setView).catch((e) => setError(e.message));
  }, []);

  const rest = view?.not_placed;
  const horizon = view?.horizon_days ?? 30;
  const newAsset = <button onClick={() => setModal(true)}><PlusIcon /> New asset</button>;
  // The sample truck (with its RCM), opened in the Explorer.
  const addTruck = () => {
    if (adding) return;
    setAdding(true);
    setError(null);
    addSample(postSampleTruck, confirm, "truck")
      .then((r) => navigate(`${EXPLORER_PATH}?tab=rcm&sel=${encodeURIComponent(r.position.id)}`))
      .catch((e) => { setError(`The sample truck wasn't added: ${e.message}`); setAdding(false); });
  };
  const sampleButton = (
    <button type="button" className="secondary" onClick={addTruck} disabled={adding}>{adding ? "Adding…" : SAMPLES.truck.label}</button>
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
    </tr>
  );

  return (
    <>
      <RegisterList
        title="Assets" purpose="The places you look after, and everything at each one."
        help={HELP} primary={newAsset}
        menu={<button type="button" className="ovm-item" onClick={addTruck} disabled={adding}>{SAMPLES.truck.label}</button>}
        error={error} rows={view ? view.places || [] : null} noun={["asset", "assets"]}
        count={assetsSummary(view)} search={(p) => [p.name, p.description]}
        name={(p) => ({ to: assetPath(p.id), label: p.name, sub: [p.description, insideText(p)].filter(Boolean).join(" · ") })}
        columns={columns} after={notPlaced || null}
        empty={{
          title: "No assets yet",
          text: "An asset is a place you look after: a house, a site, a plant. Add one, then add the rooms or areas inside it and say where each position is. Or add the sample truck to see an RCM built on its tree.",
          sample: sampleButton,
          guide: "How the asset tree works",
        }}
      />
      {modal && <NewLocationModal asset locations={[]} onClose={() => setModal(false)}
                                  onDone={(l) => navigate(placePath(l.id))} />}
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
