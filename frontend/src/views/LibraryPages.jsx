import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { deleteLibrary, getLibraryRecord, getLibrarySources, removeLibraryRecord, searchLibrary } from "../api.js";
import PageHeader from "../components/ui/PageHeader.jsx";
import Plot from "../components/Plot.jsx";
import { Select, TextInput } from "../components/ui/Controls.jsx";
import Chip from "../components/ui/Chip.jsx";
import { LibraryFormDialog, LibraryLookup, UseAsModelDialog, UseAsPriorDialog } from "../components/LibraryParts.jsx";
import { StorageCapNotice } from "../components/StorageCap.jsx";
import { ShowMe } from "../components/SectionPage.jsx";
import { useConfirm } from "../components/ConfirmProvider.jsx";
import { ACCENT } from "../plotTheme.js";
import {
  BASIS_LABEL as BASIS, KIND_LABEL as KIND, LIBRARY_PATH, curve, distributionWords, evidenceWords, isLife, lifeCurve, lifeWords,
  asGivenWords, rangeText, recordIdOf, recordPath, sig, sourcePath, unitsMeaning, whyNot,
} from "../libraryModels.js";
import "./LibraryPages.css";

// The reliability data library under Models, three levels (Derryn, 9 Nov 2026): the libraries
// (each source: what it covers, how many records, its basis and licence, the reference), one
// library's records (filters, sort, and each record's Use as a model… / Use as a prior…), and one
// record (its distribution written out and plotted, its units, basis, full reference and notes).
// The user's own libraries (Derryn, 9 Nov: "a way to build a library") show first, as "Yours":
// the same pages, plus New library…, Edit, Delete and, on a record, Remove from library.

const crumbsFor = (source, record) => [
  { label: "Models", to: "/models" },
  ...(source || record ? [{ label: "Library", to: LIBRARY_PATH }] : []),
  ...(record && source ? [{ label: source.short_name || source.name, to: sourcePath(source.id) }] : []),
];

function useSources() {
  const [sources, setSources] = useState(null);
  const [error, setError] = useState(null);
  const [tick, setTick] = useState(0);
  useEffect(() => { getLibrarySources().then((d) => setSources(d.sources || []), (e) => setError(e.message)); }, [tick]);
  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { sources, error, reload };
}

// Use as a model… and Use as a prior…. ``inline``: when one is off, why, in words under the
// buttons (not only on hover); the records table says it once above the table instead.
function Actions({ rec, inline = false }) {
  const [open, setOpen] = useState(null);
  const whyModel = whyNot(rec, "model");
  const whyPrior = whyNot(rec, "prior");
  const why = [...new Set([whyModel, whyPrior].filter(Boolean))];
  const buttons = (
    <span className="lib-actions">
      <button type="button" className="secondary sm" disabled={!!whyModel} title={whyModel || undefined} onClick={() => setOpen("model")}>Use as a model…</button>
      <button type="button" className="secondary sm" disabled={!!whyPrior} title={whyPrior || undefined} onClick={() => setOpen("prior")}>Use as a prior…</button>
      {open === "model" && <UseAsModelDialog record={rec} onClose={() => setOpen(null)} />}
      {open === "prior" && <UseAsPriorDialog record={rec} onClose={() => setOpen(null)} />}
    </span>
  );
  if (!inline || !why.length) return buttons;
  return (
    <span className="lib-actions-col">
      {buttons}
      {why.map((w) => <span key={w} className="lib-why">{w}</span>)}
    </span>
  );
}

// A library's card on the sources page: a published source, or one of the user's own.
function SourceCard({ s }) {
  return (
    <Link to={sourcePath(s.id)} className="card lib-source">
      <h2 className="lib-h">{s.name}</h2>
      <p>{s.description || (s.mine ? "No description yet." : "")}</p>
      <p className="lib-facts">
        <Chip>{s.records} {s.records === 1 ? "record" : "records"}</Chip>
        {s.mine ? <Chip>Yours</Chip> : <Chip>{BASIS[s.basis] || s.basis}</Chip>}
        {s.licence?.name && <Chip>{s.licence.name}</Chip>}
      </p>
      {!s.mine && <p className="rim-tquiet">{s.title}{s.report ? ` (${s.report})` : ""}{s.year ? `, ${s.year}` : ""}</p>}
    </Link>
  );
}

// /models/library: the libraries (yours, then the published ones), and a search across them all.
export function LibraryHome() {
  const { sources, error, reload } = useSources();
  const [making, setMaking] = useState(false);
  const navigate = useNavigate();
  const mine = (sources || []).filter((s) => s.mine);
  const published = (sources || []).filter((s) => !s.mine);
  return (
    <div className="app">
      <PageHeader crumbs={crumbsFor()} title="Library"
                  meta={(
                    <span className="sh-purpose">
                      <span className="sh-purpose-text" title="Published failure rates and probabilities, and libraries of your own models, each with its uncertainty and its source, to use as a model or a prior.">Published failure rates and probabilities, and libraries of your own models, each with its uncertainty and its source, to use as a model or a prior.</span>
                      <ShowMe help={{ guide: "fit-your-first-model" }} />
                    </span>
                  )}
                  primary={<button type="button" onClick={() => setMaking(true)}>New library…</button>} />
      {error && <div className="card error">{error}</div>}
      <StorageCapNotice kind="libraries" one="data library" many="data libraries" refreshKey={sources} />
      <section className="card" aria-label="Search every library">
        <h2 className="lib-h">Know the record you want?</h2>
        <LibraryLookup label="Records" />
      </section>
      {sources === null && !error && <div className="card empty">Loading…</div>}
      {sources !== null && (
        <section aria-labelledby="lib-yours">
          <h2 id="lib-yours" className="lib-section">Yours</h2>
          {mine.length === 0 ? (
            <div className="card empty">
              <p>No libraries of your own yet. A library holds snapshots of your saved life models, to use as models or priors.</p>
              <p><button type="button" onClick={() => setMaking(true)}>New library…</button></p>
            </div>
          ) : <div className="lib-sources">{mine.map((s) => <SourceCard key={s.id} s={s} />)}</div>}
        </section>
      )}
      {published.length > 0 && (
        <section aria-labelledby="lib-published">
          <h2 id="lib-published" className="lib-section">Published</h2>
          <div className="lib-sources">{published.map((s) => <SourceCard key={s.id} s={s} />)}</div>
        </section>
      )}
      {making && <LibraryFormDialog onClose={() => setMaking(false)} onDone={(lib) => { setMaking(false); reload(); navigate(sourcePath(lib.id)); }} />}
    </div>
  );
}

// /models/library/:source: every record of one library, with its filters and sort. One of the user's
// own libraries adds Edit… and Delete….
export function LibrarySource() {
  const { source: sourceId } = useParams();
  const { sources, error, reload } = useSources();
  const navigate = useNavigate();
  const confirm = useConfirm();
  const source = (sources || []).find((s) => s.id === sourceId);
  const [editing, setEditing] = useState(false);
  const [deleteError, setDeleteError] = useState(null);
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
  // Why Use as a model… / Use as a prior… are off, said once above the table (each button keeps it on hover).
  const offWhy = useMemo(() => {
    const counts = new Map();
    for (const r of shown) {
      for (const w of new Set([whyNot(r, "model"), whyNot(r, "prior")].filter(Boolean))) counts.set(w, (counts.get(w) || 0) + 1);
    }
    return [...counts].map(([text, n]) => ({ text, all: n === shown.length }));
  }, [shown]);
  const mine = !!source?.mine;
  const canEdit = mine && !source.read_only;
  const onDelete = async () => {
    const ok = await confirm({
      title: `Delete ${source.name}?`,
      body: `Its ${source.records} ${source.records === 1 ? "record goes" : "records go"} with it. The models the records came from stay.`,
      confirmLabel: "Delete the library",
    });
    if (!ok) return;
    try {
      await deleteLibrary(source.id);
      navigate(LIBRARY_PATH);
    } catch (e) {
      setDeleteError(e.message);
    }
  };
  const meta = source ? (mine
    ? [`${source.records} ${source.records === 1 ? "record" : "records"}`, source.description].filter(Boolean).join(" · ")
    : `${source.records} records · ${BASIS[source.basis] || source.basis} · ${source.licence?.name || ""}`) : null;
  return (
    <div className="app">
      <PageHeader crumbs={crumbsFor(source || { id: sourceId })} title={source?.name || sourceId} meta={meta}
                  primary={canEdit ? (
                    <span className="lib-actions">
                      <button type="button" className="secondary" onClick={() => setEditing(true)}>Edit…</button>
                      <button type="button" className="secondary danger" onClick={onDelete}>Delete…</button>
                    </span>
                  ) : null} />
      {error && <div className="card error">{error}</div>}
      {deleteError && <div className="card error" role="alert">{deleteError}</div>}
      {mine && source.notes && <section className="card"><h2 className="lib-h">Notes</h2><p className="lib-notes">{source.notes}</p></section>}
      {mine && rows !== null && rows.length === 0 && (
        <div className="card empty">
          <p>No records yet. Open one of your <Link to="/models/life">non-repairable models</Link> and choose <strong>Add to a library…</strong> from its ⋯ menu,
            or do the same on a position’s life model in the Explorer’s Modelling tab.</p>
        </div>
      )}
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
            <option value="">Every kind</option><option value="rate">Failure rates</option><option value="per_demand">Per demand</option><option value="life">Life models</option>
          </Select>
          <Select aria-label="Sort" value={sort} onChange={(e) => setSort(e.target.value)}>
            <option value="name">By name</option><option value="mean">By mean, lowest first</option>
          </Select>
        </div>
        {offWhy.length > 0 && <p className="lib-why">{offWhy.length === 1 && offWhy[0].all ? "Every record here: " : "Some records here: "}{offWhy.map((w) => w.text).join(" ")}</p>}
        {rows === null ? <p className="rim-tquiet">Loading the records…</p> : (
          <div className="maint-scroll lib-scroll">
            <table className="lib-table">
              <thead><tr><th>Record</th><th>Equipment</th><th>Failure mode</th><th>Kind</th><th className="num">Mean</th><th className="num">5–95%</th><th>Units</th><th /></tr></thead>
              <tbody>
                {shown.map((r) => (
                  <tr key={r.id}>
                    <td><Link to={recordPath(r.id)}>{r.label}</Link></td>
                    <td>{r.equipment_type}</td><td>{r.failure_mode}</td><td>{KIND[r.kind] || r.kind}</td>
                    <td className="num">{r.mean == null ? "—" : sig(r.mean)}</td><td className="num">{rangeText(r)}</td><td>{r.units}</td>
                    <td><Actions rec={r} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="rim-tquiet">{shown.length} of {rows.length} records.</p>
          </div>
        )}
      </section>
      {editing && <LibraryFormDialog library={source} onClose={() => setEditing(false)} onDone={() => { setEditing(false); reload(); }} />}
    </div>
  );
}

// /models/library/:source/:record: one record.
export function LibraryRecord() {
  const { source: sourceId, record } = useParams();
  const id = recordIdOf(sourceId, record);
  const { sources } = useSources();
  const navigate = useNavigate();
  const confirm = useConfirm();
  const source = (sources || []).find((s) => s.id === sourceId);
  const [d, setD] = useState(null);
  const [error, setError] = useState(null);
  // Not in any library (404): said plainly, with links back, as the model pages do.
  const [missing, setMissing] = useState(false);
  useEffect(() => {
    setD(null);
    setError(null);
    setMissing(false);
    getLibraryRecord(id).then(setD, (e) => (e.status === 404 ? setMissing(true) : setError(e.message)));
  }, [id]);
  const rec = d?.record;
  const life = isLife(rec);
  const summary = rec?.summary || {};
  // A rate or probability's own unit ("per hour (running)"), which the numbers are in; the source's
  // wording (as_given, e.g. "failures per million hours") only where it is the same thing.
  const valueUnits = life ? rec?.units?.as_given : (d?.units || rec?.units?.as_given || "");
  const given = asGivenWords(rec, summary.mean);
  const brief = rec && { id: rec.id, label: rec.label, kind: rec.kind, basis: rec.basis, mean: summary.mean, p05: summary.p05,
    p95: summary.p95, b10: summary.b10, units: valueUnits, source: source?.short_name || sourceId,
    family: rec.distribution?.family, params: rec.distribution?.params, level: rec.distribution?.level };
  const pts = rec ? (life ? lifeCurve(rec.distribution, summary) : curve(rec.distribution, summary.p05, summary.p95)) : null;
  // The log axis's ticks: a decade apart, as powers of ten; a narrow range (under 2.5 decades) adds the 2s and 5s.
  const decades = pts && !life ? Math.log10(pts.x[pts.x.length - 1] / pts.x[0]) : 0;
  const cite = rec?.citation || {};
  const lib = d?.library || null;
  const link = d?.model_link || null;
  const onRemove = async () => {
    const ok = await confirm({ title: `Remove ${rec.label} from ${lib.name}?`, body: "The model it came from stays.",
      confirmLabel: "Remove from library" });
    if (!ok) return;
    try {
      await removeLibraryRecord(lib.id, rec.id);
      navigate(sourcePath(lib.id));
    } catch (e) {
      setError(e.message);
    }
  };
  if (missing) {
    return (
      <div className="app">
        <PageHeader crumbs={crumbsFor(source || { id: sourceId })} title="Record not found" />
        <div className="card" role="alert">
          <p style={{ marginTop: 0 }}>We couldn't find this record. It may have been removed, or the link may be mistyped.</p>
          <p style={{ marginBottom: 0 }}>
            {source && <><Link to={sourcePath(source.id)}>See {source.short_name || source.name}</Link> · </>}
            <Link to={LIBRARY_PATH}>The library</Link> · <Link to="/models">All models</Link>
          </p>
        </div>
      </div>
    );
  }
  return (
    <div className="app">
      <PageHeader crumbs={crumbsFor(source || { id: sourceId }, true)} title={rec?.label || "Record"}
                  meta={rec ? `${KIND[rec.kind] || rec.kind} · ${lib ? "Your library" : BASIS[rec.basis] || rec.basis}` : null}
                  primary={brief ? (
                    <span className="lib-actions">
                      <Actions rec={brief} inline />
                      {lib && !lib.read_only && <button type="button" className="secondary sm danger" onClick={onRemove}>Remove from library</button>}
                    </span>
                  ) : null} />
      {error && <div className="card error" role="alert">{error}</div>}
      {!rec && !error && <div className="card empty">Loading…</div>}
      {rec && (
        <div className="lib-record">
          <section className="card">
            <h2 className="lib-h">What it is</h2>
            <p>{rec.name}{rec.failure_mode?.name ? `: ${rec.failure_mode.name}` : ""}{rec.failure_mode?.meaning ? `. ${rec.failure_mode.meaning}` : "."}</p>
            <dl className="ml-dl">
              <dt>Distribution</dt><dd>{life ? lifeWords(rec.distribution, rec.units?.as_given) : distributionWords(rec.distribution)}</dd>
              {life ? (
                <>
                  <dt>Mean life</dt><dd>{summary.mean == null ? "Not finite for these parameters" : `${sig(summary.mean)} ${rec.units?.as_given}`}</dd>
                  {summary.b10 != null && <><dt>B10 life</dt><dd>{sig(summary.b10)} {rec.units?.as_given}</dd></>}
                  {summary.median != null && <><dt>Median</dt><dd>{sig(summary.median)} {rec.units?.as_given}</dd></>}
                  <dt>5–95% lives</dt><dd>{rangeText(summary)} {rec.units?.as_given}</dd>
                </>
              ) : (
                <>
                  <dt>Mean</dt><dd>{sig(summary.mean)} {valueUnits}{given ? ` (${given}, as the source gives it)` : ""}</dd>
                  {summary.median != null && <><dt>Median</dt><dd>{sig(summary.median)}</dd></>}
                  <dt>5–95%</dt><dd>{rangeText(summary)}{summary.error_factor ? ` (error factor ${sig(summary.error_factor)})` : ""}</dd>
                </>
              )}
              <dt>Units</dt><dd>{valueUnits}: {unitsMeaning(rec.kind, valueUnits)}</dd>
              {life && evidenceWords(rec.evidence) && <><dt>Evidence</dt><dd>{evidenceWords(rec.evidence)}</dd></>}
              {!life && rec.evidence?.failures != null && <><dt>Evidence</dt><dd>{[rec.evidence.failures != null && `${rec.evidence.failures} failures`,
                rec.evidence.demands && `${Number(rec.evidence.demands).toLocaleString("en-AU")} demands`,
                rec.evidence.components && `${rec.evidence.components} components`, rec.evidence.period, rec.evidence.method].filter(Boolean).join(" · ")}</dd></>}
              {rec.notes && <><dt>Notes</dt><dd className="lib-notes">{rec.notes}</dd></>}
            </dl>
          </section>
          {pts && (
            <section className="card">
              <h2 className="lib-h">The distribution</h2>
              <Plot data={[{ x: pts.x, y: pts.y, mode: "lines", line: { color: ACCENT, width: 2 }, name: "Density" }]}
                    layout={{ height: 260,
                      // Powers of ten on the log axis (not "1.0000005e-12"); the density in SI prefixes.
                      xaxis: life ? { title: { text: `Time to failure (${rec.units?.as_given || "units"})` }, rangemode: "tozero" }
                        : { type: "log", dtick: decades < 2.5 ? "D2" : 1, exponentformat: "power", showexponent: "all",
                          title: { text: rec.kind === "per_demand" ? "Probability per demand" : "Failure rate (per hour)" } },
                      yaxis: { title: { text: "Density" }, rangemode: "tozero", exponentformat: "SI", showexponent: "all" } }}
                    download={`${rec.label} — distribution`} />
            </section>
          )}
          <section className="card">
            <h2 className="lib-h">Source and licence</h2>
            {lib ? (
              <>
                <p>
                  From your library <Link to={sourcePath(lib.id)}>{lib.name}</Link>
                  {link ? (link.exists
                    ? <>, a snapshot of the model <Link to={`/models/m/${link.id}`}>{link.name}</Link> when it was added</>
                    : <>, a snapshot of the model {link.name || rec.model?.name} (since deleted) when it was added</>) : ""}
                  {rec.created_at ? ` on ${new Date(rec.created_at).toLocaleDateString("en-AU")}` : ""}.
                  {" "}A later refit of the model doesn’t change this record.
                </p>
                {lib.notes ? <p className="lib-notes rim-tquiet">{lib.notes}</p> : <p className="rim-tquiet">No notes or licence text on this library yet.</p>}
              </>
            ) : (
              <>
                <p>{cite.title || source?.title}{cite.report ? ` (${cite.report})` : ""}{cite.table ? `, ${cite.table}` : ""}{cite.page ? `, p. ${cite.page}` : ""}{cite.year ? `, ${cite.year}` : ""}.</p>
                {source?.licence && <p className="rim-tquiet">{source.licence.name}. {source.licence.attribution}</p>}
              </>
            )}
            {(d.caveats || []).length > 0 && <ul>{d.caveats.map((c) => <li key={c}>{c}</li>)}</ul>}
          </section>
        </div>
      )}
    </div>
  );
}
