import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { getLibraryRecord, getLibrarySources, searchLibrary } from "../api.js";
import PageHeader from "../components/ui/PageHeader.jsx";
import Plot from "../components/Plot.jsx";
import { Select, TextInput } from "../components/ui/Controls.jsx";
import Chip from "../components/ui/Chip.jsx";
import { LibraryPicker, UseAsModelDialog, UseAsPriorDialog } from "../components/LibraryParts.jsx";
import { ACCENT } from "../plotTheme.js";
import {
  LIBRARY_PATH, curve, distributionWords, rangeText, recordIdOf, recordPath, sig, sourcePath, unitsMeaning, whyNot,
} from "../libraryModels.js";
import "./LibraryPages.css";

// The reliability data library under Models, three levels (Derryn, 9 Nov 2026): the libraries
// (each source: what it covers, how many records, its basis and licence, the reference), one
// library's records (filters, sort, and each record's Use as a model… / Use as a prior…), and one
// record (its distribution written out and plotted, its units, basis, full reference and notes).

const crumbsFor = (source, record) => [
  { label: "Models", to: "/models" },
  ...(source || record ? [{ label: "Library", to: LIBRARY_PATH }] : []),
  ...(record && source ? [{ label: source.short_name || source.name, to: sourcePath(source.id) }] : []),
];
const BASIS = { field_data: "Field data", prediction_model: "Handbook prediction model" };
const KIND = { rate: "Failure rate", per_demand: "Per demand" };

function useSources() {
  const [sources, setSources] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => { getLibrarySources().then((d) => setSources(d.sources || []), (e) => setError(e.message)); }, []);
  return { sources, error };
}

function Actions({ rec }) {
  const [open, setOpen] = useState(null);
  const whyModel = whyNot(rec, "model");
  const whyPrior = whyNot(rec, "prior");
  return (
    <span className="lib-actions">
      <button type="button" className="secondary sm" disabled={!!whyModel} title={whyModel || undefined} onClick={() => setOpen("model")}>Use as a model…</button>
      <button type="button" className="secondary sm" disabled={!!whyPrior} title={whyPrior || undefined} onClick={() => setOpen("prior")}>Use as a prior…</button>
      {open === "model" && <UseAsModelDialog record={rec} onClose={() => setOpen(null)} />}
      {open === "prior" && <UseAsPriorDialog record={rec} onClose={() => setOpen(null)} />}
    </span>
  );
}

// /models/library: the libraries, and a search across them all.
export function LibraryHome() {
  const { sources, error } = useSources();
  const [picked, setPicked] = useState(null);
  return (
    <div className="app">
      <PageHeader crumbs={crumbsFor()} title="Library"
                  meta="Published failure rates and probabilities, each with its uncertainty and its source, to use as a model or a prior." />
      {error && <div className="card error">{error}</div>}
      <section className="card" aria-label="Search every library">
        <h2 className="lib-h">Know the record you want?</h2>
        <LibraryPicker value={picked?.id} onPick={setPicked} label="Records" use="look" />
        {picked && <p><Link to={recordPath(picked.id)}>Open {picked.label}</Link></p>}
      </section>
      {sources === null && !error && <div className="card empty">Loading…</div>}
      <div className="lib-sources">
        {(sources || []).map((s) => (
          <Link key={s.id} to={sourcePath(s.id)} className="card lib-source">
            <h2 className="lib-h">{s.name}</h2>
            <p>{s.description}</p>
            <p className="lib-facts">
              <Chip>{s.records} records</Chip> <Chip>{BASIS[s.basis] || s.basis}</Chip> <Chip>{s.licence?.name}</Chip>
            </p>
            <p className="rim-tquiet">{s.title}{s.report ? ` (${s.report})` : ""}{s.year ? `, ${s.year}` : ""}</p>
          </Link>
        ))}
      </div>
    </div>
  );
}

// /models/library/:source: every record of one library, with its filters and sort.
export function LibrarySource() {
  const { source: sourceId } = useParams();
  const { sources, error } = useSources();
  const source = (sources || []).find((s) => s.id === sourceId);
  const [rows, setRows] = useState(null);
  const [q, setQ] = useState("");
  const [equipment, setEquipment] = useState("");
  const [mode, setMode] = useState("");
  const [kind, setKind] = useState("");
  const [sort, setSort] = useState("name");
  useEffect(() => {
    let live = true;
    (async () => {
      const all = [];
      for (let page = 1; page < 10; page += 1) {
        const d = await searchLibrary({ source: sourceId, page, pageSize: 100 });
        all.push(...(d.results || []));
        if (page >= (d.pages || 1)) break;
      }
      if (live) setRows(all);
    })().catch(() => live && setRows([]));
    return () => { live = false; };
  }, [sourceId]);
  const equipments = useMemo(() => [...new Set((rows || []).map((r) => r.equipment_type).filter(Boolean))].sort(), [rows]);
  const modes = useMemo(() => [...new Set((rows || []).map((r) => r.failure_mode).filter(Boolean))].sort(), [rows]);
  const shown = useMemo(() => {
    const t = q.trim().toLowerCase();
    const out = (rows || []).filter((r) => (!equipment || r.equipment_type === equipment) && (!mode || r.failure_mode === mode)
      && (!kind || r.kind === kind) && (!t || `${r.label} ${r.equipment_type} ${r.failure_mode}`.toLowerCase().includes(t)));
    return out.sort((a, b) => (sort === "mean" ? (a.mean ?? 0) - (b.mean ?? 0) : String(a.label).localeCompare(String(b.label))));
  }, [rows, q, equipment, mode, kind, sort]);
  return (
    <div className="app">
      <PageHeader crumbs={crumbsFor(source || { id: sourceId })} title={source?.name || sourceId}
                  meta={source ? `${source.records} records · ${BASIS[source.basis] || source.basis} · ${source.licence?.name || ""}` : null} />
      {error && <div className="card error">{error}</div>}
      <section className="card">
        <div className="lib-filters">
          <TextInput type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Name, equipment, failure mode" aria-label="Search this library" />
          <Select aria-label="Equipment type" value={equipment} onChange={(e) => setEquipment(e.target.value)}>
            <option value="">Every equipment type</option>{equipments.map((x) => <option key={x} value={x}>{x}</option>)}
          </Select>
          <Select aria-label="Failure mode" value={mode} onChange={(e) => setMode(e.target.value)}>
            <option value="">Every failure mode</option>{modes.map((x) => <option key={x} value={x}>{x}</option>)}
          </Select>
          <Select aria-label="Kind" value={kind} onChange={(e) => setKind(e.target.value)}>
            <option value="">Every kind</option><option value="rate">Failure rates</option><option value="per_demand">Per demand</option>
          </Select>
          <Select aria-label="Sort" value={sort} onChange={(e) => setSort(e.target.value)}>
            <option value="name">By name</option><option value="mean">By mean, lowest first</option>
          </Select>
        </div>
        {rows === null ? <p className="rim-tquiet">Loading the records…</p> : (
          <div className="maint-scroll">
            <table className="lib-table">
              <thead><tr><th>Record</th><th>Equipment</th><th>Failure mode</th><th>Kind</th><th className="num">Mean</th><th className="num">5–95%</th><th>Units</th><th /></tr></thead>
              <tbody>
                {shown.map((r) => (
                  <tr key={r.id}>
                    <td><Link to={recordPath(r.id)}>{r.label}</Link></td>
                    <td>{r.equipment_type}</td><td>{r.failure_mode}</td><td>{KIND[r.kind] || r.kind}</td>
                    <td className="num">{sig(r.mean)}</td><td className="num">{rangeText(r)}</td><td>{r.units}</td>
                    <td><Actions rec={r} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="rim-tquiet">{shown.length} of {rows.length} records.</p>
          </div>
        )}
      </section>
    </div>
  );
}

// /models/library/:source/:record: one record.
export function LibraryRecord() {
  const { source: sourceId, record } = useParams();
  const id = recordIdOf(sourceId, record);
  const { sources } = useSources();
  const source = (sources || []).find((s) => s.id === sourceId);
  const [d, setD] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => { setD(null); getLibraryRecord(id).then(setD, (e) => setError(e.message)); }, [id]);
  const rec = d?.record;
  const summary = rec?.summary || {};
  const brief = rec && { id: rec.id, label: rec.label, kind: rec.kind, basis: rec.basis, mean: summary.mean, p05: summary.p05,
    p95: summary.p95, units: rec.units?.as_given, source: source?.short_name || sourceId };
  const pts = rec ? curve(rec.distribution, summary.p05, summary.p95) : null;
  // The log axis's ticks: a decade apart, as powers of ten; a narrow range (under 2.5 decades) adds the 2s and 5s.
  const decades = pts ? Math.log10(pts.x[pts.x.length - 1] / pts.x[0]) : 0;
  const cite = rec?.citation || {};
  return (
    <div className="app">
      <PageHeader crumbs={crumbsFor(source || { id: sourceId }, true)} title={rec?.label || "Record"}
                  meta={rec ? `${KIND[rec.kind] || rec.kind} · ${BASIS[rec.basis] || rec.basis}` : null}
                  primary={brief ? <Actions rec={brief} /> : null} />
      {error && <div className="card error">{error}</div>}
      {!rec && !error && <div className="card empty">Loading…</div>}
      {rec && (
        <div className="lib-record">
          <section className="card">
            <h2 className="lib-h">What it is</h2>
            <p>{rec.name}{rec.failure_mode?.name ? `: ${rec.failure_mode.name}` : ""}{rec.failure_mode?.meaning ? `. ${rec.failure_mode.meaning}` : "."}</p>
            <dl className="ml-dl">
              <dt>Distribution</dt><dd>{distributionWords(rec.distribution)}</dd>
              <dt>Mean</dt><dd>{sig(summary.mean)} {rec.units?.as_given}</dd>
              {summary.median != null && <><dt>Median</dt><dd>{sig(summary.median)}</dd></>}
              <dt>5–95%</dt><dd>{rangeText(summary)}{summary.error_factor ? ` (error factor ${sig(summary.error_factor)})` : ""}</dd>
              <dt>Units</dt><dd>{rec.units?.as_given}: {unitsMeaning(rec.kind, rec.units?.as_given)}</dd>
              {rec.evidence?.failures != null && <><dt>Evidence</dt><dd>{[rec.evidence.failures != null && `${rec.evidence.failures} failures`,
                rec.evidence.demands && `${Number(rec.evidence.demands).toLocaleString("en-AU")} demands`,
                rec.evidence.components && `${rec.evidence.components} components`, rec.evidence.period, rec.evidence.method].filter(Boolean).join(" · ")}</dd></>}
            </dl>
          </section>
          {pts && (
            <section className="card">
              <h2 className="lib-h">The distribution</h2>
              <Plot data={[{ x: pts.x, y: pts.y, mode: "lines", line: { color: ACCENT, width: 2 }, name: "Density" }]}
                    layout={{ height: 260,
                      // Powers of ten on the log axis (not "1.0000005e-12"); the density in SI prefixes.
                      xaxis: { type: "log", dtick: decades < 2.5 ? "D2" : 1, exponentformat: "power", showexponent: "all",
                        title: { text: rec.kind === "per_demand" ? "Probability per demand" : "Failure rate (per hour)" } },
                      yaxis: { title: { text: "Density" }, rangemode: "tozero", exponentformat: "SI", showexponent: "all" } }}
                    download={`${rec.label} — distribution`} />
            </section>
          )}
          <section className="card">
            <h2 className="lib-h">Source and licence</h2>
            <p>{cite.title || source?.title}{cite.report ? ` (${cite.report})` : ""}{cite.table ? `, ${cite.table}` : ""}{cite.page ? `, p. ${cite.page}` : ""}{cite.year ? `, ${cite.year}` : ""}.</p>
            {source?.licence && <p className="rim-tquiet">{source.licence.name}. {source.licence.attribution}</p>}
            {(d.caveats || []).length > 0 && <ul>{d.caveats.map((c) => <li key={c}>{c}</li>)}</ul>}
          </section>
        </div>
      )}
    </div>
  );
}
