import { useEffect, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { getPositionRcm } from "../api.js";
import usePageTitle from "../components/usePageTitle.js";
import { EXPORT_HEADER, FMEA_HEADER, positionRcmRows } from "../rcmImport.js";
import { fmt3 } from "../fmea.js";
import { explorerPath } from "../assetTree.js";
import "./Maintenance.css";
import "../components/FmeaPanels.css";

// The print view of a position's FME(C)A (/asset-register/positions/:id/fmea):
// one plain, full-width worksheet table, it and everything inside it, one row
// per failure mode (the rows the CSV export writes, rcmImport.js), with print
// CSS for a landscape page. Opened from the FME(C)A tab's overflow menu
// (Print view); Print prints it.

// The worksheet's columns: where the mode sits, then the FME(C)A's own.
const SHOWN = ["Position", "Function", "Functional failure", "Failure mode", ...FMEA_HEADER];
const NUMERIC = new Set(["Severity", "Occurrence", "Detection", "RPN", "Failure rate", "Mode ratio", "Loss probability", "Operating time", "Mode criticality"]);
const ROUNDED = new Set(["Failure rate", "Mode ratio", "Loss probability", "Operating time", "Mode criticality"]);

export default function FmeaPrint() {
  const { id } = useParams();
  const navigate = useNavigate();
  // Back to where it was opened (a product's structure tab, or the Explorer);
  // opened from a link, the Explorer on this position.
  const back = useLocation().state?.back || explorerPath("positions", { tab: "fmea", sel: id });
  const [sheet, setSheet] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    let live = true;
    setSheet(null);
    setError(null);
    getPositionRcm(id, "below").then((d) => live && setSheet(d), (e) => live && setError(e.message));
    return () => { live = false; };
  }, [id]);
  const top = sheet?.positions?.[0];
  usePageTitle(top ? `${top.name} FME(C)A` : "FME(C)A");
  const rows = sheet ? positionRcmRows(sheet).slice(1) : [];
  const at = (row, h) => row[EXPORT_HEADER.indexOf(h)];
  // Only rows with a failure mode are the worksheet's; a function with none
  // is still listed, so the gap shows.
  const shown = rows.filter((r) => at(r, "Failure mode") || at(r, "Function"));
  return (
    <div className="app fm-print">
      <div className="fm-print-head">
        <div>
          <h1>{top ? top.name : "FME(C)A"}</h1>
          <p className="muted">FME(C)A worksheet{top ? `: ${top.name} and everything inside it` : ""} · {sheet?.today || ""}</p>
        </div>
        <div className="fm-print-acts">
          <button type="button" className="secondary" onClick={() => navigate(back)}>Back</button>
          <button type="button" onClick={() => window.print()}>Print</button>
        </div>
      </div>
      {error ? (
        <div className="card error"><p>The worksheet didn't load: {error}</p></div>
      ) : !sheet ? (
        <div className="card empty">Loading…</div>
      ) : !shown.length ? (
        <div className="card empty"><p>No functions or failure modes here yet. Add them on the Explorer's FME(C)A tab.</p></div>
      ) : (
        <div className="maint-scroll">
          <table className="fm-sheet">
            <thead>
              <tr>{SHOWN.map((h) => <th key={h} scope="col">{h}</th>)}</tr>
            </thead>
            <tbody>
              {shown.map((r, i) => (
                <tr key={i} className={at(r, "Failure mode") ? undefined : "fm-fn"}>
                  {SHOWN.map((h) => {
                    const v = at(r, h);
                    const text = v == null || v === "" ? "" : ROUNDED.has(h) ? fmt3(v) : String(v);
                    return <td key={h} className={NUMERIC.has(h) ? "num" : undefined}>{text}</td>;
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
