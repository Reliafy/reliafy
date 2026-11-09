import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { deleteLibrary, getLibraryComponent, getLibraryComponents, getLibraryRecord, getLibrarySources, removeLibraryRecord, searchLibrary } from "../api.js";
import PageHeader from "../components/ui/PageHeader.jsx";
import Plot from "../components/Plot.jsx";
import { Select, TextInput } from "../components/ui/Controls.jsx";
import Chip from "../components/ui/Chip.jsx";
import { LibraryFormDialog, LibraryLookup, UseAsModelDialog, UseAsPriorDialog } from "../components/LibraryParts.jsx";
import { StorageCapNotice } from "../components/StorageCap.jsx";
import { ShowMe } from "../components/SectionPage.jsx";
import { useConfirm } from "../components/ConfirmProvider.jsx";
import { ACCENT } from "../plotTheme.js";
import CovariateCalculator from "../components/CovariateCalculator.jsx";
import { TRIGGER_WORDS, isCovariate, modeRows, modelShape, modelWords, unitShort } from "../covariate.js";
import {
  BASIS_LABEL as BASIS, KIND_LABEL as KIND, LIBRARY_PATH, curve, distributionWords, evidenceWords, isLife, lifeCurve, lifeWords,
  asGivenWords, componentIdOf, componentPath, rangeText, recordIdOf, recordPath, sig, sourcePath, unitsMeaning, whyNot,
} from "../libraryModels.js";
import "./LibraryPages.css";

// The reliability data library under Models, three levels (and an NRC/INL source's components:
// an equipment type in one pooling group, its failure modes together, each with its own page) (Derryn, 9 Nov 2026): the libraries
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
  // "By component" (NRC/INL): the source's components, when it has any.
  const [comps, setComps] = useState(null);
  const [view, setView] = useState("records");
  useEffect(() => {
    let live = true;
    setComps(null);
    getLibraryComponents(sourceId).then((d) => live && setComps(d.components || []), () => live && setComps([]));
    return () => { live = false; };
  }, [sourceId]);
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
  // A library of covariate models (NSWC-11) lists each component's parts or failure modes instead.
  const covariateRows = useMemo(() => (shown.some(isCovariate) ? modeRows(shown.filter(isCovariate)) : null), [shown]);
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
      {!mine && source?.disclaimer && <CovariateSourceIntro source={source} />}
      {mine && rows !== null && rows.length === 0 && (
        <div className="card empty">
          <p>No records yet. Open one of your <Link to="/models/life">non-repairable models</Link> and choose <strong>Add to a library…</strong> from its ⋯ menu,
            or do the same on a position’s life model in the Explorer’s Modelling tab.</p>
        </div>
      )}
      {comps?.length > 0 && (
        <div className="lib-view" role="group" aria-label="Show">
          <button type="button" className={view === "records" ? "" : "secondary"} aria-pressed={view === "records"} onClick={() => setView("records")}>Records</button>
          <button type="button" className={view === "components" ? "" : "secondary"} aria-pressed={view === "components"} onClick={() => setView("components")}>By component</button>
        </div>
      )}
      {view === "components" && comps?.length > 0 ? <ComponentTable comps={comps} q={q} setQ={setQ} /> : (
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
            <option value="">Every kind</option><option value="rate">Failure rates</option><option value="per_demand">Per demand</option><option value="life">Life models</option><option value="covariate_model">Covariate models</option>
          </Select>
          <Select aria-label="Sort" value={sort} onChange={(e) => setSort(e.target.value)}>
            <option value="name">By name</option><option value="mean">By mean, lowest first</option>
          </Select>
        </div>
        {offWhy.length > 0 && !covariateRows && <p className="lib-why">{offWhy.length === 1 && offWhy[0].all ? "Every record here: " : "Some records here: "}{offWhy.map((w) => w.text).join(" ")}</p>}
        {rows !== null && covariateRows ? (
          <CovariateTable rows={covariateRows} total={rows.length} shown={shown.length} />
        ) : rows === null ? <p className="rim-tquiet">Loading the records…</p> : (
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
      )}
      {editing && <LibraryFormDialog library={source} onClose={() => setEditing(false)} onDone={() => { setEditing(false); reload(); }} />}
    </div>
  );
}

// "By component": an NRC/INL source's components, one row each: the component (an equipment type in
// one of the report's pooling groups), its failure modes and what sets them off.
function ComponentTable({ comps, q, setQ }) {
  const t = q.trim().toLowerCase();
  const shown = comps.filter((c) => !t || `${c.label} ${c.mode_names.join(" ")} ${c.equipment_type}`.toLowerCase().includes(t));
  return (
    <section className="card" aria-label="Components">
      <p className="rw-fhelp">Each component brings its failure modes together: those per demand (fails to start, open or close),
        per hour of running (fails to run) and per calendar hour (leaks, spurious operation). Open one for its chance of failing
        over a period, with the demands and hours you give.</p>
      <div className="lib-filters">
        <TextInput type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Component or failure mode" aria-label="Search the components" />
      </div>
      <div className="maint-scroll lib-scroll">
        <table className="lib-table">
          <thead><tr><th>Component</th><th>Failure modes</th><th>Set off by</th></tr></thead>
          <tbody>
            {shown.map((c) => (
              <tr key={c.id}>
                <td><Link to={componentPath(c.id)}>{c.label}</Link></td>
                <td>{c.mode_names.join(", ")}{c.alternatives ? <span className="rim-tquiet"> (+{c.alternatives} not added)</span> : null}</td>
                <td>{c.triggers.map((x) => TRIGGER_WORDS[x] || x).join("; ")}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="rim-tquiet">{shown.length} of {comps.length} components.</p>
      </div>
    </section>
  );
}

// /models/library/:source/components/:component: a component's failure modes (each a record, with
// what sets it off and whether it's added), how they combine in words, and Try it: its chance of
// failing over a period of demands, running hours and calendar hours, in the shared calculator.
export function LibraryComponent() {
  const { source: sourceId, component } = useParams();
  const { sources } = useSources();
  const source = (sources || []).find((s) => s.id === sourceId);
  const id = componentIdOf(sourceId, component);
  const [d, setD] = useState(null);
  const [error, setError] = useState(null);
  const [missing, setMissing] = useState(false);
  const [values, setValues] = useState({ demands: "12", running_hours: "24" });
  const [using, setUsing] = useState(false);
  useEffect(() => {
    setD(null);
    setMissing(false);
    getLibraryComponent(id).then(setD, (e) => (e.status === 404 ? setMissing(true) : setError(e.message)));
  }, [id]);
  if (missing) {
    return (
      <div className="app">
        <PageHeader crumbs={crumbsFor(source || { id: sourceId })} title="Component not found" />
        <div className="card" role="alert"><p>We couldn't find this component. <Link to={sourcePath(sourceId)}>See the library</Link>.</p></div>
      </div>
    );
  }
  const counted = (d?.modes || []).filter((m) => m.counted);
  const alts = (d?.modes || []).filter((m) => !m.counted);
  return (
    <div className="app">
      <PageHeader crumbs={crumbsFor(source || { id: sourceId }, true)} title={d?.label || "Component"}
                  meta={d ? `${counted.length} failure modes · ${source?.short_name || sourceId}` : null}
                  primary={d ? <button type="button" onClick={() => setUsing(true)}>Use as a model…</button> : null} />
      {error && <div className="card error" role="alert">{error}</div>}
      {!d && !error && <div className="card empty">Loading…</div>}
      {d && (
        <div className="lib-record">
          <section className="card">
            <h2 className="lib-h">How its modes combine</h2>
            <p>{d.how}</p>
            <p className="rim-tquiet">From {d.citation}. Industry averages, not this equipment’s own data.</p>
          </section>
          <section className="card">
            <h2 className="lib-h">Try it</h2>
            <p className="rw-fhelp">The demands, running hours and calendar hours over the period you have in mind (a year is 8,760 hours; a 24-hour mission with one start is 1 demand and 24 running hours).</p>
            <CovariateCalculator recordId={id} inputs={d.inputs} values={values} onChange={setValues} idPrefix="comp" />
          </section>
          <section className="card">
            <h2 className="lib-h">Its failure modes</h2>
            <div className="maint-scroll lib-scroll">
              <table className="lib-table">
                <thead><tr><th>Failure mode</th><th>Set off by</th><th className="num">Mean</th><th>Units</th><th className="num">5–95%</th></tr></thead>
                <tbody>
                  {counted.map((m) => (
                    <tr key={m.record_id}>
                      <td><Link to={recordPath(m.record_id)}>{m.mode}</Link> <span className="rim-tquiet">{m.code}</span></td>
                      <td>{TRIGGER_WORDS[m.trigger] || m.trigger_words}</td>
                      <td className="num">{sig(m.record.mean)}</td><td>{m.record.units}</td><td className="num">{rangeText(m.record)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {alts.length > 0 && (
              <>
                <h3 className="lib-h3">Listed, not added</h3>
                <ul>{alts.map((m) => <li key={m.record_id}><Link to={recordPath(m.record_id)}>{m.mode}</Link> ({m.code}): {m.not_added}.</li>)}</ul>
              </>
            )}
          </section>
          {(d.caveats || []).length > 0 && <section className="card"><h2 className="lib-h">Caveats</h2><ul>{d.caveats.map((c) => <li key={c}>{c}</li>)}</ul></section>}
        </div>
      )}
      {using && d && <UseAsModelDialog record={{ id, label: d.label, source: source?.short_name || sourceId, kind: "component" }} onClose={() => setUsing(false)} />}
    </div>
  );
}

// A covariate source's page intro (NSWC-11): what its models are, in words, and the Navy's statement.
function CovariateSourceIntro({ source }) {
  return (
    <section className="card lib-cov-intro" aria-label="About these models">
      <h2 className="lib-h">Covariate models: base rate × condition factors</h2>
      <p>Each component’s failure rate starts at a base rate and is scaled by factors for the conditions it works in:
        load, speed, temperature, pressure, contamination, material and more. Open a component to see its model in words,
        its factors and the handbook’s limits on every input, and try it with your own conditions. In a reliability
        prediction, a mechanical part can take one of these with its conditions.</p>
      <p className="lib-disclaimer"><strong>Not endorsed by the Navy.</strong> {source.disclaimer}</p>
    </section>
  );
}

// The components' parts or failure modes, one row each: the component (a link to its record), the
// part, its base rate with the unit, and how many condition factors scale it.
function CovariateTable({ rows, total, shown }) {
  return (
    <div className="maint-scroll lib-scroll">
      <table className="lib-table">
        <thead><tr><th>Component</th><th>Part or failure mode</th><th>Base rate</th><th className="num">Factors</th><th>Equation</th></tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id}>
              <td><Link to={recordPath(r.recordId)}>{r.component}</Link></td>
              <td>{r.mode}</td><td>{r.base}</td><td className="num">{r.factors}</td><td>Eq. {r.equation}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="rim-tquiet">{rows.length} parts and failure modes in {shown} of {total} components.</p>
    </div>
  );
}

// A record's covariates (a pipe's length, the clock and running hours, the demands a year, a handbook
// part's environment and quality) with its rate under them: the shared calculator.
function RecordTry({ rec, inputs }) {
  const [values, setValues] = useState({});
  return (
    <section className="card">
      <h2 className="lib-h">Try it</h2>
      <p className="rw-fhelp">What it needs before it gives a rate (its covariates). The same inputs appear wherever it’s used: Use as a model…, a prior in a fit, a position, an RBD block.</p>
      <CovariateCalculator recordId={rec.id} inputs={inputs} values={values} onChange={setValues} idPrefix="try" />
    </section>
  );
}

// A covariate record's own sections (NSWC-11): the model in words first, then the formula with
// each factor (what it's for, its figure or table and page), the inputs with their units, defaults
// and limits, Try it, the failure modes it covers, and the citation with the Navy's statement.
function CovariateRecord({ rec, d, source }) {
  const m = rec.covariate_model || {};
  const cov = d.covariate || {};
  const [values, setValues] = useState({});
  const cite = rec.citation || {};
  return (
    <div className="lib-record">
      <section className="card">
        <h2 className="lib-h">The model in words</h2>
        <p>{modelWords(rec)}</p>
        <dl className="ml-dl">
          <dt>Rate</dt><dd>{(rec.units?.as_given || "").replace(/^./, (c) => c.toUpperCase())} ({unitShort(m.rate_unit)}){cov.per_cycle ? ". In a prediction it needs how many cycles it makes an hour." : "."}</dd>
          <dt>Shape</dt><dd>{modelShape(cov)}</dd>
          {rec.notes && <><dt>Notes</dt><dd className="lib-notes">{rec.notes}</dd></>}
        </dl>
      </section>
      <section className="card">
        <h2 className="lib-h">The formula</h2>
        <p className="lib-formula"><code>{m.formula}</code> <span className="rim-tquiet">(Eq. {m.equation}, p. {m.page})</span></p>
        {(m.modes || []).map((mode) => (
          <div key={mode.key} className="lib-cov-mode">
            <h3 className="lib-h3">{mode.name}{mode.symbol ? ` (${mode.symbol})` : ""}{mode.count ? " × how many there are" : ""}</h3>
            {mode.uses ? (
              <p>Its own model: <Link to={recordPath(mode.uses)}>{(cov.modes || []).find((x) => x.key === mode.key)?.uses_name || mode.uses}</Link>{mode.note ? `. ${mode.note}` : "."}</p>
            ) : (
              <div className="maint-scroll">
                <table className="lib-table lib-cov-factors">
                  <thead><tr><th>Symbol</th><th>Factor</th><th>From</th><th>Page</th></tr></thead>
                  <tbody>
                    <tr><td>{mode.base.symbol}</td><td>{mode.base.name}{"value" in mode.base ? `: ${mode.base.value} ${unitShort(m.rate_unit)}` : ""}</td><td>{mode.base.equation ? `Eq. ${mode.base.equation}` : mode.base.source || "—"}</td><td>{mode.base.page}</td></tr>
                    {(mode.factors || []).map((f) => (
                      <tr key={f.symbol}><td>{f.symbol}</td><td>{f.name}{f.words ? <span className="rim-tquiet"> · {f.words}</span> : null}</td>
                        <td>{[f.equation ? `Eq. ${f.equation}` : null, f.source].filter(Boolean).join(", ") || "—"}</td><td>{f.page}</td></tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {mode.note && !mode.uses && <p className="rim-tquiet">{mode.note}</p>}
          </div>
        ))}
      </section>
      <section className="card" aria-labelledby="cov-try">
        <h2 id="cov-try" className="lib-h">Try it</h2>
        <p className="rim-tquiet">Change the conditions to see the rate. Blank inputs take the default shown; the handbook’s limits are under each one.</p>
        <CovariateCalculator recordId={rec.id} inputs={cov.inputs || []} unit={m.rate_unit} values={values} onChange={setValues} idPrefix="try" />
      </section>
      {(rec.failure_modes || []).length > 0 && (
        <section className="card">
          <h2 className="lib-h">Failure modes it covers</h2>
          <ul>{rec.failure_modes.map((f) => <li key={f}>{f}</li>)}</ul>
        </section>
      )}
      <section className="card">
        <h2 className="lib-h">Source and licence</h2>
        <p>{cite.title}{cite.report ? ` (${cite.report})` : ""}, {cite.table}, p. {cite.page}, {cite.year}.</p>
        {d.disclaimer && <p className="lib-disclaimer"><strong>Not endorsed by the Navy.</strong> {d.disclaimer}</p>}
        {source?.licence && <p className="rim-tquiet">{source.licence.name}.</p>}
        {(d.caveats || []).length > 0 && <ul>{d.caveats.filter((c) => c !== d.disclaimer).map((c) => <li key={c}>{c}</li>)}</ul>}
      </section>
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
  const pts = rec && !isCovariate(rec) ? (life ? lifeCurve(rec.distribution, summary) : curve(rec.distribution, summary.p05, summary.p95)) : null;
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
      {rec && isCovariate(rec) && <CovariateRecord rec={rec} d={d} source={source} />}
      {rec && !isCovariate(rec) && (
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
              {rec.kind === "rate" && ["gamma", "lognormal"].includes(rec.distribution?.family) && (
                <><dt>As a model</dt><dd>
                  Use as a model… saves an exponential at the mean rate and keeps this {rec.distribution.family} on the
                  rate (times to failure are exponential at a plant’s rate; the {rec.distribution.family} is how that rate
                  varies from plant to plant). The model’s page shows the 5–95% range across plants beside each value.
                  {/per foot/i.test(valueUnits) ? " Give the pipe’s length: the model is for that length." : ""}
                  {" "}Its covariates (below) say what else it needs.
                </dd></>
              )}
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
          {(d.covariates || []).length > 0 && <RecordTry rec={rec} inputs={d.covariates} />}
          {(d.components || []).length > 0 && (
            <section className="card">
              <h2 className="lib-h">Part of {d.components.length === 1 ? "a component" : "these components"}</h2>
              <p className="rw-fhelp">With the component’s other failure modes, for its chance of failing over a period.</p>
              <ul>{d.components.map((c) => <li key={c.id}><Link to={componentPath(c.id)}>{c.label}</Link> ({c.modes} failure modes)</li>)}</ul>
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
