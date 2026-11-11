import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { getDesignRollup, listFailureReports } from "../api.js";
import {
  CONSEQUENCES, DEFAULT_FILTERS, DESIGN_FILTERS, SORTS, STATUS_CHIPS, builtItemChoices, builtItemPlace, consequenceShort,
  countsSentence, filtering, levelText, positionsInScope, queryParams, scopeOf, statusLabel,
} from "../failureReports.js";
import { isDesignRow } from "../explorerTabs.js";
import { PRODUCTS_GUIDE } from "../products.js";
import FailureReportDetail from "./FailureReportDetail.jsx";
import { Field, FormModal, PositionPicker, fmtDate } from "./MaintenanceParts.jsx";
import { ShowMe } from "./SectionPage.jsx";
import { usePanelMenu } from "../panelMenu.js";
import "./FailureReports.css";

// The Explorer's Failure reports tab: every report at the row picked and
// below it (a position and everything inside it; a location's positions; the
// reports an item was involved in), newest first, open ones unless asked
// otherwise. The counts in a line, chips for the stage, a search box, the
// consequence, failure mode, dates and order to narrow it, and "Show more"
// for a long list. A row opens the report in place of the list (?report= in
// the address, so a link opens on it). "Add failure report…" (a position's row
// menu, and the panel heading's "…" menu, given through `onMenu`) files one at
// the position picked (a location or an item: which position, first).
//
// `reports` is the page's: {id (the report open), open(id | null), onNew
// (positionId, name), onChanged (the tree read again), viewOnly}.
//
// On a product's page (a design's position, the product's own row included) the
// list is the reports raised on the items built from the product, at the position
// implementing the row on each item and below it (the server rolls them up given
// the design position), every one, open first; each row says which item (serial).
// No report is filed on a design: "Report a failure" asks which built item it was
// on, then files it at that item's position (with one item built, straight there).

const HELP = { guide: "failure-reports-on-your-asset-tree" };
const BUILD_HELP = { guide: PRODUCTS_GUIDE };
// A touch screen has no right-click: there, each row's ⋯ button opens its menu.
const touch = () => typeof window !== "undefined" && !!window.matchMedia?.("(hover: none)").matches;
const PAGE = 50;

function PickPositionModal({ positions, onClose, onPick }) {
  const [id, setId] = useState(positions[0]?.id || null);
  return (
    <FormModal title="Which position?" submitLabel="Next" canSubmit={!!id} onClose={onClose}
               onSubmit={async () => onPick(positions.find((p) => p.id === id))}>
      <p className="lib-date">A failure report sits at a position. Pick the one it happened at.</p>
      <Field label="Position">
        <PositionPicker positions={positions} value={id} onChange={setId} emptyLabel="Choose…" />
      </Field>
    </FormModal>
  );
}

// A report filed from a product's design: which item built from it (by serial).
function PickItemModal({ items, onClose, onPick }) {
  const [id, setId] = useState(items[0]?.id || "");
  return (
    <FormModal title="Which item?" submitLabel="Next" canSubmit={!!id} onClose={onClose}
               onSubmit={async () => onPick(items.find((it) => it.id === id))}>
      <p className="lib-date">A failure report is about one item built from this product. Pick the one it happened on.</p>
      <Field label="Item (serial)">
        <select value={id} autoFocus onChange={(e) => setId(e.target.value)}>
          {items.map((it) => <option key={it.id} value={it.id}>{it.label}</option>)}
        </select>
      </Field>
    </FormModal>
  );
}

function Row({ r, scopeKind, onOpen }) {
  const level = levelText(r.level);
  const where = level || (scopeKind === "pos" ? "" : r.position?.name || "");
  const unit = r.unit && (r.unit.serial ? `Serial ${r.unit.serial}` : "(no serial)");
  const sub = [unit, where, r.item?.name, r.failure_mode?.text].filter(Boolean).join(" · ");
  return (
    <li>
      <button type="button" className="fr-row" onClick={() => onOpen(r.id)}>
        <span className="fr-label">{r.label}</span>
        <span className="fr-title">{r.title}</span>
        <span className="fr-sub lib-date">{sub || "At this position"}</span>
        <span className="fr-when lib-date">{fmtDate(r.occurred_on)}</span>
        <span className="fr-pills">
          {r.consequence && <span className={`td-pill cons-${r.consequence}`}>{consequenceShort(r.consequence)}</span>}
          <span className={`td-pill st-${r.status}`}>{statusLabel(r.status)}</span>
          {r.open_actions > 0 && <span className="lib-date fr-open-actions">{r.open_actions} open {r.open_actions === 1 ? "action" : "actions"}</span>}
        </span>
      </button>
    </li>
  );
}

export default function FailureReportsPanel({ row, display, today, version, reports, onMenu = null }) {
  const scope = scopeOf(row);
  const scopeKey = scope ? `${row.type}:${row.key}` : "";
  const design = isDesignRow(row);
  const defaults = design ? DESIGN_FILTERS : DEFAULT_FILTERS;
  const [filters, setFilters] = useState(defaults);
  const [q, setQ] = useState("");
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const [more, setMore] = useState(false);
  const [picking, setPicking] = useState(false);
  // A design: the items built from the product (where a report can be filed), null while read.
  const [built, setBuilt] = useState(null);
  const [builtError, setBuiltError] = useState(null);
  // The failure modes seen in this scope's reports, for the filter.
  const [modes, setModes] = useState(new Map());
  const seq = useRef(0);

  // The search box waits for typing to settle; the rest filters at once.
  useEffect(() => {
    const t = setTimeout(() => setFilters((f) => (f.q === q ? f : { ...f, q })), 250);
    return () => clearTimeout(t);
  }, [q]);
  // Another row: back to the usual filters, its list read afresh (the last
  // row's isn't shown meanwhile).
  useEffect(() => {
    setFilters((f) => (f === defaults ? f : defaults));
    setQ("");
    setModes(new Map());
    setData(null);
  }, [scopeKey]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    setBuilt(null);
    setBuiltError(null);
    if (!design || row?.type !== "pos") return undefined;
    let live = true;
    getDesignRollup(row.key)
      .then((d) => live && setBuilt(builtItemChoices(d.items)))
      .catch((e) => live && setBuiltError(e.message));
    return () => { live = false; };
  }, [scopeKey, design, version]); // eslint-disable-line react-hooks/exhaustive-deps

  const fetchList = useCallback((offset = 0) => {
    if (!scope) return;
    const n = ++seq.current;
    if (offset) setMore(true);
    else setLoading(true);
    setError(null);
    listFailureReports(queryParams(filters, scope, { limit: PAGE, offset }))
      .then((d) => {
        if (n !== seq.current) return;
        setData((old) => (offset && old ? { ...d, reports: [...old.reports, ...(d.reports || [])] } : d));
        setModes((m) => {
          const next = new Map(m);
          for (const r of d.reports || []) if (r.failure_mode?.id) next.set(r.failure_mode.id, r.failure_mode.text);
          return next;
        });
      })
      .catch((e) => n === seq.current && setError(e.message))
      .finally(() => {
        if (n !== seq.current) return;
        setLoading(false);
        setMore(false);
      });
  }, [filters, scope?.position_id, scope?.location_id, scope?.item_id]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { fetchList(0); }, [fetchList, version]);

  const set = (k, v) => setFilters((f) => ({ ...f, [k]: v }));
  const positions = useMemo(() => positionsInScope(display, row), [display, row]);
  const fileOn = (choice) => reports.onNew(choice.id, builtItemPlace(choice));
  const addHere = () => {
    if (reports.viewOnly) return;
    if (design) {
      if (built?.length === 1) fileOn(built[0]);
      else if (built?.length) setPicking(true);
    } else if (row.type === "pos") reports.onNew(row.key, row.ref.name);
    else setPicking(true);
  };
  const canAdd = !reports.viewOnly && (design ? !!built?.length : row.type === "pos" || positions.length > 0);
  const addTitle = reports.viewOnly || (design
    ? (built && !built.length ? "No items have been built from this product yet." : undefined)
    : row.type !== "pos" && !positions.length
      ? (row.type === "item" ? "This item isn't fitted to a position; a report sits at a position." : "No positions here to report a failure at.") : undefined);
  usePanelMenu(onMenu, [{ id: "report-new", label: design ? "Report a failure…" : "Add failure report…", onSelect: addHere, disabled: !canAdd, title: addTitle }]);

  if (reports.id) {
    return (
      <FailureReportDetail id={reports.id} today={today} viewOnly={reports.viewOnly}
                           onBack={() => reports.open(null)} onStatusChanged={reports.onChanged} />
    );
  }

  const counts = data?.counts || {};
  const total = ["reported", "investigating", "corrective_action", "verifying", "closed", "rejected"].reduce((t, k) => t + (counts[k] || 0), 0);
  const chipCount = (id) => (id === "all" ? total : id === "open" ? counts.open || 0 : counts[id] || 0);
  const narrowed = filtering(filters, defaults);
  const list = data?.reports || [];
  // Nothing here at all (and nothing narrowing it): the stage chips, search
  // and filters would only be a row of zeros, so they wait for a first report.
  const none = !!data && !error && total === 0 && !list.length && !narrowed;

  let body;
  if (error) {
    body = <p className="lib-date">Couldn't load the failure reports: {error} <button type="button" className="link" onClick={() => fetchList(0)}>Try again</button></p>;
  } else if (!data && loading) {
    body = <p className="lib-date">Loading…</p>;
  } else if (!list.length && !narrowed && design) {
    body = (
      <div className="fr-empty">
        <p>No failure reports on the items built from this product here yet.</p>
      </div>
    );
  } else if (!list.length && !narrowed) {
    body = (
      <div className="fr-empty">
        <p>No failure reports here yet. To add one, {touch() ? "tap ⋯ on a position in the tree" : "right-click a position in the tree"} and choose Add failure report…, or use More actions (…) above.</p>
        <p className="section-empty-more"><ShowMe help={HELP}>How failure reports work</ShowMe></p>
      </div>
    );
  } else if (!list.length) {
    body = (
      <p className="lib-date">Nothing matches these filters.{" "}
        <button type="button" className="link" onClick={() => { setFilters(defaults); setQ(""); }}>{design ? "Show every report" : "Show open reports"}</button>
      </p>
    );
  } else {
    body = (
      <>
        <ul className="fr-list" aria-label="Failure reports" aria-busy={loading || undefined}>
          {list.map((r) => <Row key={r.id} r={r} scopeKind={row.type} onOpen={reports.open} />)}
        </ul>
        {data.total > list.length && (
          <p className="fr-more">
            <button type="button" className="secondary sm" disabled={more} onClick={() => fetchList(list.length)}>
              {more ? "Loading…" : `Show more (${(data.total - list.length).toLocaleString("en-AU")} left)`}
            </button>
          </p>
        )}
      </>
    );
  }

  // A design with nothing built from it: one line, and how to build an item.
  if (design && built && !built.length && !error && (!data || total === 0)) {
    return (
      <div className="fr-panel">
        <div className="fr-empty">
          <p>No items have been built from this product yet, so there are no failure reports to show or file.{" "}
            <ShowMe help={BUILD_HELP}>How to build an item</ShowMe></p>
        </div>
      </div>
    );
  }
  // A design: "Report a failure" (once the items built are read).
  let designAdd = null;
  if (design && !reports.viewOnly) {
    designAdd = builtError
      ? <p className="lib-date">Couldn't read the items built from this product: {builtError}</p>
      : <button type="button" className="secondary sm" onClick={addHere} disabled={!built?.length}>Report a failure</button>;
  }

  return (
    <div className="fr-panel">
      <div className="fr-head">
        <p className="fr-counts">{data ? countsSentence(counts, data.scope, { kind: row.type }) : " "}</p>
        {designAdd}
      </div>
      {!none && (
      <div className="fr-filters">
        <div className="fr-chips" role="group" aria-label="Stage">
          {STATUS_CHIPS.map((c) => {
            const on = filters.status === c.id;
            return (
              <button key={c.id} type="button" className={`chip ${on ? "chip-accent" : "chip-neutral"}`} aria-pressed={on}
                      onClick={() => set("status", c.id)}>
                {c.label}{data ? <span className="fr-chip-n">{chipCount(c.id)}</span> : null}
              </button>
            );
          })}
        </div>
        <div className="fr-controls">
          <input type="search" value={q} placeholder="Search reports" aria-label="Search failure reports" onChange={(e) => setQ(e.target.value)} />
          <select value={filters.consequence} aria-label="Consequence" onChange={(e) => set("consequence", e.target.value)}>
            <option value="">Any consequence</option>
            {CONSEQUENCES.filter((c) => c.id).map((c) => <option key={c.id} value={c.id}>{c.label}</option>)}
          </select>
          <select value={filters.failure_mode_id} aria-label="Failure mode" onChange={(e) => set("failure_mode_id", e.target.value)}>
            <option value="">Any failure mode</option>
            {[...modes.entries()].sort((a, b) => a[1].localeCompare(b[1])).map(([id, text]) => <option key={id} value={id}>{text}</option>)}
          </select>
          <label className="fr-date"><span>Since</span><input type="date" value={filters.since} max={filters.until || undefined} onChange={(e) => set("since", e.target.value)} /></label>
          <label className="fr-date"><span>Until</span><input type="date" value={filters.until} min={filters.since || undefined} onChange={(e) => set("until", e.target.value)} /></label>
          <select value={filters.sort} aria-label="Order" onChange={(e) => set("sort", e.target.value)}>
            {SORTS.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
          </select>
        </div>
      </div>
      )}
      {body}
      {picking && design && (
        <PickItemModal items={built || []} onClose={() => setPicking(false)}
                       onPick={(it) => { setPicking(false); fileOn(it); }} />
      )}
      {picking && !design && (
        <PickPositionModal positions={positions} onClose={() => setPicking(false)}
                           onPick={(p) => { setPicking(false); reports.onNew(p.id, p.name); }} />
      )}
    </div>
  );
}
