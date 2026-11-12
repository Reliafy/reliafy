import { useEffect, useState } from "react";
import Select from "./Select.jsx";
import ScrollCue from "./ui/ScrollCue.jsx";
import { analyzeRbd, getRbd, listRbds } from "../api.js";
import { formatReliability, timeInWords } from "../rbdCalcText.js";
import { bestOf, designRow, unitClash } from "../rbdCompareDesigns.js";
import { unitInText } from "./unitText.js";

// "Compare with other designs" on a non-repairable diagram's Calculator
// results: this diagram (as it is in the builder) beside up to four saved
// non-repairable diagrams — the reliability at the time asked about, MTTF and
// B-lives, each worked out exactly as the Calculator works it out. Free, like
// the Calculator: nothing is simulated.

const MAX_OTHERS = 4;
const fmtLife = (v) => (v == null ? "—" : Number(v.toPrecision(4)).toLocaleString("en-US"));

export default function RbdCompareDesigns({ graph, rbdId = null, t = null }) {
  const [rbds, setRbds] = useState(null);
  const [pick, setPick] = useState("");
  const [chosen, setChosen] = useState([]); // [{id, name}]
  const [rows, setRows] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    let live = true;
    listRbds()
      .then((r) => live && setRbds((r.rbds || []).filter((d) => !d.repairable && d.id !== rbdId)))
      .catch(() => live && setRbds([]));
    return () => { live = false; };
  }, [rbdId]);

  // A new time or diagram makes the shown comparison out of date.
  const graphKey = JSON.stringify(graph);
  useEffect(() => { setRows(null); }, [t, graphKey]);

  const time = Number(t);
  const hasT = Number.isFinite(time) && time > 0;
  const options = (rbds || [])
    .filter((d) => !chosen.some((c) => c.id === d.id))
    .map((d) => ({ value: d.id, label: d.name, hint: d.is_sample ? "sample" : undefined }));

  const add = () => {
    const d = (rbds || []).find((x) => x.id === pick);
    if (!d || chosen.length >= MAX_OTHERS) return;
    setChosen((c) => [...c, { id: d.id, name: d.name }]);
    setPick("");
    setRows(null);
  };
  const remove = (id) => {
    setChosen((c) => c.filter((x) => x.id !== id));
    setRows(null);
  };

  const run = async () => {
    if (!hasT || !chosen.length) return;
    setBusy(true);
    setError(null);
    try {
      const analyse = (g) => analyzeRbd(g, null, {}, null, { evaluateAt: time });
      const others = await Promise.all(chosen.map(async (c) => {
        const doc = await getRbd(c.id);
        return designRow(doc.name || c.name, await analyse(doc.graph || {}), { id: c.id });
      }));
      const mine = designRow("This diagram", await analyse(graph), { id: "this", current: true });
      setRows([mine, ...others]);
    } catch (err) {
      setRows(null);
      setError(err.message);
    }
    setBusy(false);
  };

  const unit = graph.unit || "";
  const u = unit ? ` (${unitInText(unit)})` : "";
  const best = rows ? bestOf(rows, "reliability") : null;
  const bestName = best ? rows.find((r) => r.id === best)?.name : null;

  return (
    <div className="rbd-compare">
      <div className="ds-section-h">Compare with other designs</div>
      <p className="hint" style={{ margin: 0 }}>
        Put this diagram beside other saved non-repairable designs: each one&rsquo;s reliability
        {hasT ? ` over ${timeInWords(time, unit)}` : " at Evaluate at t"}, MTTF and B-lives, worked out exactly.
      </p>
      <div className="rbd-compare-bar">
        <Select
          value={pick}
          onChange={setPick}
          options={options}
          placeholder={rbds == null ? "Loading diagrams…" : options.length ? "Choose a saved design…" : "No other saved non-repairable diagrams"}
          disabled={!options.length || chosen.length >= MAX_OTHERS}
          title="Another saved non-repairable diagram to compare with this one"
        />
        <button type="button" className="secondary" onClick={add} disabled={!pick || chosen.length >= MAX_OTHERS}>
          Add
        </button>
        <button type="button" onClick={run} disabled={!chosen.length || !hasT || busy}
                title={hasT ? undefined : "Type a time in Evaluate at t first"}>
          {busy ? "Comparing…" : "Compare"}
        </button>
      </div>
      {chosen.length > 0 && (
        <ul className="rbd-compare-chosen">
          {chosen.map((c) => (
            <li key={c.id}>
              <span>{c.name}</span>
              <button type="button" className="link" onClick={() => remove(c.id)} aria-label={`Remove ${c.name}`}>Remove</button>
            </li>
          ))}
        </ul>
      )}
      {!hasT && <p className="hint" style={{ margin: 0 }}>Type a time in Evaluate at t to compare at it.</p>}
      {error && <div className="card error">{error}</div>}
      {rows && (
        <div className="rbd-compare-result">
          {bestName && (
            <p className="rbd-compare-verdict b_higher">
              <b>{bestName}</b> is the most reliable over {timeInWords(time, unit)}
              {" "}(R = {formatReliability(rows.find((r) => r.id === best).reliability)}).
            </p>
          )}
          {unitClash(rows) && (
            <p className="hint warn" style={{ margin: 0 }}>
              These diagrams use different time units, so their figures aren&rsquo;t on the same scale.
            </p>
          )}
          <ScrollCue className="rbd-avail-imp-scroll">
            <table className="calc-table rbd-compare-table">
              <thead>
                <tr>
                  <th>Design</th>
                  <th title="System reliability over the time asked about">R({timeInWords(time, unit)})</th>
                  <th>MTTF{u}</th>
                  <th>B10{u}</th>
                  <th>B50{u}</th>
                  <th title="Blocks that alone take the system down (cut sets of one)">Single points of failure</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id}>
                    <td className="calc-row-label">{r.name}</td>
                    <td>{r.id === best ? <b>{formatReliability(r.reliability)}</b> : formatReliability(r.reliability)}</td>
                    <td>{fmtLife(r.mttf)}</td>
                    <td>{fmtLife(r.b10)}</td>
                    <td>{fmtLife(r.b50)}</td>
                    <td>{r.singlePoints}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </ScrollCue>
          <p className="muted-line" style={{ margin: 0 }}>
            Point values from each diagram&rsquo;s exact analysis (no confidence band). This diagram is as it is
            in the builder, saved or not.
          </p>
        </div>
      )}
    </div>
  );
}
