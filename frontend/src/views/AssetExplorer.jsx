import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { getMaintenanceTree, getRcmOptions, listMaintenanceItems } from "../api.js";
import { useWorkspace } from "../WorkspaceProvider.jsx";
import TreePane from "../components/TreePane.jsx";
import TreeDetail, { DetailHeader } from "../components/TreeDetail.jsx";
import DecisionModal from "../components/DecisionModal.jsx";
import { RollupBadges } from "../components/RcmStatusBadge.jsx";
import { ColumnChooser, Details, EDITABLE } from "../components/RcmWorksheet.jsx";
import Tabs from "../components/ui/Tabs.jsx";
import { useAskText, useConfirm } from "../components/ConfirmProvider.jsx";
import useTreeRcm from "../components/useTreeRcm.js";
import { cellRow, graftRcm, isRcmRow, openFor, positionOf } from "../explorerRcm.js";
import { COLUMN, LEVEL_OF, checkValue, loadPrefs, savePrefs } from "../rcmWorksheet.js";
import FullScreenButton from "../components/FullScreenButton.jsx";
import useFullScreen from "../components/useFullScreen.js";
import { hasOpenLayer, isFullScreenKey } from "../fullScreen.js";
import { shownTab, tabParam, tabsFor } from "../explorerTabs.js";
import { ShowMe } from "../components/SectionPage.jsx";
import { PlusIcon } from "../components/LibRows.jsx";
import { NewItemModal, NewLocationModal } from "./MaintenanceLists.jsx";
import { FromRcmModal, ImportModal, NewPositionModal } from "./MaintenanceHome.jsx";
import {
  ARRANGEMENTS, ancestorsOf, arrangementOf, buildDisplay, carryOver, clampWidth, computeFilter, explorerPath,
  filterOpen, flatten, levelSet, loadTreeState, saveTreeState,
} from "../assetTree.js";
import { EXPLORER_LABEL } from "../navigation.js";
import usePhone from "../usePhone.js";
import "./Maintenance.css";
import "./AssetExplorer.css";

// Operate › Assets › Explorer: one page, one tree pane over the whole
// register, arranged by positions, locations or items, or as a flat list of
// positions (Arrange by switches, and the address follows: ?arrange=). The
// tree is a second-level menu beside the site menu; the panel beside it shows
// the row picked, with "Open the full page" for the position's (or
// location's, or item's) own page. On a phone the tree is the whole screen
// and picking a row slides to the panel; Back (or the phone's back gesture)
// slides back.
//
// With no ?arrange=, it opens on the arrangement used last on this device
// (else Positions) and says so in the address. ?place=none (from the Assets
// list's last row): only the positions at no location yet. ?sel=<id>: open
// with that row picked. The old Positions, Items and Locations addresses
// redirect here (redirects.js).
//
// The panel has tabs (explorerTabs.js): ?tab=rcm opens a position's RCM, and
// the tab stays as you walk the tree (rows without it show Summary); the
// address keeps the position picked (?sel=).
//
// On the RCM tab the tree and the RCM are one table (TreePane with its
// columns): the tree, arranged by positions, is the first column, each
// position's functions › functional failures › failure modes nested in it,
// and every row has the RCM's columns beside it; the panel's heading sits over
// it. Picking a function, failure or mode opens its details beside the table;
// "Add …" rows under the position picked (and the heading's Add function) add
// to it, and the tree grows. On the Summary tab the tree is the positions alone
// and the page about the row picked is beside it. Full screen (F, Esc to leave)
// gives the tree and the panel the whole screen, as the RBD editor's.

const HELP = { guide: "rcm-study" };

// Every position depth first, for the "Inside" pickers.
function pickerList(data) {
  const d = buildDisplay(data, "positions");
  const out = [];
  const walk = (keys) => {
    for (const k of keys) {
      const r = d.rows.get(k);
      if (r.type === "pos") out.push({ id: r.key, name: r.ref.name, depth: r.depth });
      walk(r.kids);
    }
  };
  walk(d.roots);
  return out;
}

export default function AssetExplorer() {
  const navigate = useNavigate();
  const location = useLocation();
  const [params] = useSearchParams();
  const { workspace } = useWorkspace();
  const phone = usePhone();
  const saved = useMemo(() => loadTreeState(workspace), [workspace]);
  const tab = tabParam(params.get("tab"));
  const rcmOn = tab === "rcm";
  // RCM is by position: on its tab the tree is arranged by positions.
  const mode = rcmOn ? "positions" : arrangementOf(params.get("arrange"), saved.mode);
  const notPlaced = (mode === "positions" || mode === "flat") && params.get("place") === "none";
  const title = EXPLORER_LABEL;
  const treeLabel = ARRANGEMENTS.find((a) => a.value === mode).tree;

  // The address always says the arrangement, so it can be shared as it is.
  useEffect(() => {
    if (params.get("arrange") === mode) return;
    const q = new URLSearchParams(params);
    q.set("arrange", mode);
    navigate(`${location.pathname}?${q}${location.hash}`, { replace: true, state: location.state });
  }, [params, mode, navigate, location]);

  const setQuery_ = useCallback((change) => {
    const q = new URLSearchParams(params);
    change(q);
    if (q.toString() === params.toString()) return;
    navigate(`${location.pathname}?${q}${location.hash}`, { replace: true, state: location.state });
  }, [params, navigate, location]);

  const [data, setData] = useState(null);
  // The items list (class, make and model for each item), for the Items
  // arrangement: fetched when it's first shown, and again after a change.
  const [itemList, setItemList] = useState(null);
  const [error, setError] = useState(null);
  const [version, setVersion] = useState(0);
  const [openBy, setOpenBy] = useState(saved.open);
  const [selected, setSelected] = useState(saved.selected);
  const [width, setWidth] = useState(() => clampWidth(saved.width, window.innerWidth));
  const [collapsed, setCollapsed] = useState(saved.collapsed);
  const [query, setQuery] = useState("");
  const [chips, setChips] = useState([]);
  const [fopen, setFopen] = useState(null);
  const [scrollTo, setScrollTo] = useState(null);
  const [modal, setModal] = useState(null);
  const headingRef = useRef(null);
  const detailsHeading = useRef(null);
  const frame = useRef(null);
  const fullBtn = useRef(null);
  const { full, toggle: toggleFull } = useFullScreen(frame, { returnFocus: fullBtn });
  const pending = useRef(params.get("sel") || location.state?.treeReveal || null);

  const load = useCallback(() => {
    setError(null);
    getMaintenanceTree()
      .then((d) => {
        setData(d);
        setVersion((v) => v + 1);
      })
      .catch((e) => setError({ text: e.message, notAllowed: e.status === 404 || e.status === 403 }));
  }, []);
  useEffect(() => load(), [load]);

  // The RCM tab: the RCM read into the tree, and what's being worked on.
  const askText = useAskText();
  const confirm = useConfirm();
  const { rcm, error: rcmError, ops } = useTreeRcm({ on: rcmOn, onTreeChanged: load, askText });
  const [rcmFocus, setRcmFocus] = useState(null); // a function, failure or mode picked (its position is selected)
  const [panel, setPanel] = useState(false); // its details beside the table
  const [editing, setEditing] = useState(null); // {key, col}: a cell being edited
  const [deciding, setDeciding] = useState(null); // a failure mode in the decision dialog
  const [options, setOptions] = useState(null);
  const [rprefs, setRprefs] = useState(() => loadPrefs());
  const [message, setMessage] = useState(null);
  useEffect(() => {
    if (rcmOn && !options) getRcmOptions().then(setOptions).catch(() => {});
  }, [rcmOn, options]);
  useEffect(() => {
    const t = setTimeout(() => savePrefs(rprefs), 200);
    return () => clearTimeout(t);
  }, [rprefs]);
  const say = (text, tone = "ok") => setMessage({ text, tone, at: Date.now() });
  const wantItems = mode === "items";
  useEffect(() => {
    if (!wantItems || !version) return undefined;
    let live = true;
    // Without it the items still show, from the tree: only class, make and model are missing.
    listMaintenanceItems().then((d) => live && setItemList(d.items || [])).catch(() => {});
    return () => {
      live = false;
    };
  }, [wantItems, version]);

  const base = useMemo(() => buildDisplay(data, mode, mode === "items" ? itemList : null), [data, mode, itemList]);
  const working = selected.positions;
  const display = useMemo(() => (rcmOn && rcm ? graftRcm(base, rcm, { addFor: working }) : base), [base, rcmOn, rcm, working]);
  const filter = useMemo(() => (data ? computeFilter(display, {
    query, chips: mode === "items" ? chips.filter((c) => c !== "empty") : chips, extra: notPlaced ? (r) => r.type === "pos" && !r.ref.location : null,
  }) : null), [data, display, query, chips, notPlaced, mode]);
  useEffect(() => setFopen(filter ? filterOpen(filter) : null), [filter]);
  const defaultOpen = useMemo(() => levelSet(display, 2), [display]);
  const baseOpen = openBy[mode] || defaultOpen;
  const open = filter ? fopen || filterOpen(filter) : baseOpen;
  const { list, index } = useMemo(() => flatten(display, open, filter), [display, open, filter]);
  const focus = rcmOn && rcmFocus && display.rows.has(rcmFocus) ? rcmFocus
    : display.rows.has(selected[mode]) ? selected[mode] : list[0]?.key ?? null;
  const focusRow = focus != null ? display.rows.get(focus) : null;
  // The position the selection is on (a function, failure or mode: its position).
  const selPos = isRcmRow(focusRow) ? positionOf(focusRow) : focus;

  // With a tab open beyond Summary, the address follows the row picked
  // (?sel=), once the tree is in, so a link opens on it with that tab.
  useEffect(() => {
    if (!data || selPos == null || pending.current || tab === "summary") return;
    if (params.get("sel") === selPos) return;
    setQuery_((q) => q.set("sel", selPos));
  }, [data, selPos, params, setQuery_, tab]);

  // Opening the RCM tab opens the position picked down to its failure modes
  // (once each time the tab opens; what's open after that is yours).
  const openedRcm = useRef(false);
  useEffect(() => {
    if (!rcmOn) {
      openedRcm.current = false;
      return;
    }
    if (!rcm || openedRcm.current || !display.rows.has(selected.positions)) return;
    openedRcm.current = true;
    const more = openFor(display, selected.positions);
    setOpenBy((o) => ({ ...o, positions: new Set([...(o.positions || levelSet(display, 2)), ...more]) }));
  }, [rcmOn, rcm, display, selected.positions]);

  const setTab = (t) => {
    if (t === tab) return;
    setEditing(null);
    if (t !== "rcm") {
      // Back to Summary: the rows below positions go; the selection is the position they were on.
      setRcmFocus(null);
      setPanel(false);
      setChips((c) => c.filter((x) => !["undecided", "hidden", "check"].includes(x)));
    }
    let keep = null;
    if (t === "rcm" && mode !== "positions") {
      keep = carryOver(focusRow, "positions");
      if (keep) setSelected((s) => ({ ...s, positions: keep }));
    }
    setQuery_((q) => {
      if (t === "summary") q.delete("tab");
      else q.set("tab", t);
      if (t === "rcm") q.set("arrange", "positions");
    });
  };

  // F toggles full screen (not while typing, nor with a dialog or menu open,
  // nor with a modifier: Ctrl+F still finds); Esc leaves it.
  useEffect(() => {
    if (phone) return undefined;
    const onKey = (e) => {
      if (!isFullScreenKey(e) || hasOpenLayer(document)) return;
      // In the tree, letters jump to a row (type-ahead): F there isn't full screen.
      if (e.target.closest?.("[role='tree'], [role='treegrid']")) return;
      e.preventDefault();
      toggleFull();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [phone, toggleFull]);

  // Remembered on this device, a moment after each change, and on the way out.
  const latest = useRef(null);
  latest.current = { mode, open: openBy, selected, width, collapsed };
  useEffect(() => {
    const t = setTimeout(() => saveTreeState(workspace, latest.current), 200);
    return () => clearTimeout(t);
  }, [workspace, mode, openBy, selected, width, collapsed]);
  useEffect(() => {
    const flush = () => saveTreeState(workspace, latest.current);
    window.addEventListener("pagehide", flush);
    return () => {
      window.removeEventListener("pagehide", flush);
      flush();
    };
  }, [workspace]);

  const setOpenSet = (next) => {
    if (filter) setFopen(next);
    else setOpenBy((o) => ({ ...o, [mode]: next }));
  };

  // Open the way down to a row, pick it and bring it into view.
  const reveal = useCallback((key) => {
    if (!display.rows.has(key)) return;
    const up = ancestorsOf(display, key);
    if (filter) setFopen((s) => new Set([...(s || filterOpen(filter)), ...up]));
    else setOpenBy((o) => ({ ...o, [mode]: new Set([...(o[mode] || defaultOpen), ...up]) }));
    const r = display.rows.get(key);
    if (isRcmRow(r)) {
      setRcmFocus(key);
      setSelected((s) => ({ ...s, [mode]: positionOf(r) }));
    } else {
      setRcmFocus(null);
      setSelected((s) => ({ ...s, [mode]: key }));
    }
    setScrollTo({ key, at: Date.now() });
  }, [display, filter, mode, defaultOpen]);

  // A row asked for by the address, or carried over from another arrangement;
  // else the one remembered, brought into view once the tree is drawn.
  const shown = useRef(null);
  useEffect(() => {
    if (!data) return;
    if (pending.current && display.rows.has(pending.current)) {
      const key = pending.current;
      pending.current = null;
      shown.current = mode;
      reveal(key);
    } else if (shown.current !== mode && display.rows.has(selected[mode])) {
      shown.current = mode;
      reveal(selected[mode]);
    }
  }, [data, display, reveal, mode, selected]);

  const detailKey = phone ? location.state?.treeDetail : null;
  const pick = (key, opts = {}) => {
    const r = display.rows.get(key);
    if (r?.type === "add") {
      if (opts.keyboard) setRcmFocus(key);
      else runAdd(r);
      return;
    }
    if (isRcmRow(r)) {
      setRcmFocus(key);
      setSelected((s) => ({ ...s, [mode]: positionOf(r) }));
      if (opts.go) setPanel(true);
      return;
    }
    setRcmFocus(null);
    setSelected((s) => ({ ...s, [mode]: key }));
    if (phone && opts.go && !rcmOn) navigate(location.pathname + location.search, { state: { treeDetail: key } });
  };

  // Adding from the tree (an "Add …" row), the heading or the details: the new
  // row is picked and brought into view once the RCM is read again.
  const runAdd = (r) => {
    const kind = r.ref.add;
    ops.add(kind, { positionId: r.ref.position_id, functionId: r.ref.function_id, failureId: r.ref.functional_failure_id ?? null })
      .then((id) => {
        if (!id) return;
        pending.current = id;
        setPanel(true);
        say(`Added the ${kind === "fn" ? "function" : kind === "fail" ? "functional failure" : "failure mode"}.`);
      }, (e) => say(e.message, "error"));
  };
  const addInside = (r) => runAdd({ ref: {
    add: r.type === "fn" ? "fail" : "mode", position_id: r.ref.position_id,
    function_id: r.type === "fn" ? r.ref.id : null, functional_failure_id: r.type === "fail" ? r.ref.id : null,
  } });
  const remove = async (r) => {
    const level = LEVEL_OF[r.type].label.toLowerCase();
    const ok = await confirm({ title: `Delete this ${level}?`, body: ops.removeText(r), confirmLabel: `Delete ${level}` });
    if (!ok) return;
    try {
      await ops.remove(r);
      setRcmFocus(isRcmRow(display.rows.get(r.parent)) ? r.parent : null);
      say(`Deleted the ${level}.`);
    } catch (e) {
      say(e.message, "error");
    }
  };
  // One cell changed: checked as the server checks it, then written.
  const commit = (r, col, raw) => {
    const res = checkValue(col, cellRow(r), raw);
    if (res.error) {
      say(res.error, "error");
      return res.error;
    }
    ops.set(r, col, res.value).then(() => say("Saved."), (e) => say(e.message, "error"));
    setEditing(null);
    return true;
  };
  const saveDecision = async (answer) => {
    const r = deciding;
    setDeciding(null);
    try {
      await ops.decide(r, answer);
      say("Saved the decision.");
    } catch (e) {
      say(e.message, "error");
    }
  };

  const toggle = (key, force) => {
    const next = new Set(open);
    const want = force ?? !next.has(key);
    if (want) next.add(key);
    else next.delete(key);
    setOpenSet(next);
  };

  // The levels: after closing, the pick moves up to the row it's hidden in.
  const setLevel = (n) => {
    let next = levelSet(display, n);
    if (filter) next = new Set([...next].filter((k) => filter.keep.has(k)));
    setOpenSet(next);
    if (focus != null) {
      const { index: shown } = flatten(display, next, filter);
      let k = focus;
      while (k != null && !shown.has(k)) k = display.rows.get(k).parent;
      if (k != null && k !== focus) setSelected((s) => ({ ...s, [mode]: k }));
      if (k != null) setScrollTo({ key: k, at: Date.now() });
    }
  };

  const onMode = (m) => {
    if (m === mode) return;
    const keep = carryOver(focus != null ? display.rows.get(focus) : null, m);
    const nextSelected = keep ? { ...selected, [m]: keep } : selected;
    setSelected(nextSelected);
    latest.current = { ...latest.current, mode: m, selected: nextSelected };
    saveTreeState(workspace, latest.current);
    pending.current = keep;
    // The tab comes along.
    navigate(explorerPath(m, { tab: tab === "summary" ? null : tab }),
             { state: keep ? { treeReveal: keep } : undefined });
  };

  // Ctrl+\ folds the pane away and back.
  useEffect(() => {
    const onKey = (e) => {
      if (e.key === "\\" && (e.ctrlKey || e.metaKey)) {
        e.preventDefault();
        setCollapsed((c) => !c);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const created = (id) => {
    setModal(null);
    pending.current = id;
    load();
  };

  const nothing = data && (mode === "locations" ? !data.locations.length && !data.positions.length
    : mode === "items" ? !display.items : !data.positions.length);
  const EMPTY = {
    locations: ["No locations yet", "Add the places you look after (a site, a house), the areas and rooms inside them, and the stores."],
    items: ["No items yet", "Items are the physical things, each with its own history. Fit one from a position's page, or add a spare that isn't fitted yet."],
  };
  const emptyDetail = error?.notAllowed ? (
    <div className="card empty">
      <h2>Not on for this account</h2>
      <p>Reliafy Maintenance (positions, locations and work orders) isn't on for this account yet.</p>
    </div>
  ) : error ? (
    <div className="card error td-error">
      <p>The tree didn't load: {error.text} Your data is safe; check your connection and try again.</p>
      <button type="button" className="secondary" onClick={load}>Try again</button>
    </div>
  ) : !data ? (
    <div className="card empty">Loading…</div>
  ) : nothing ? (
    <div className="card empty section-empty">
      <h2>{EMPTY[mode]?.[0] || "No positions yet"}</h2>
      <p>{EMPTY[mode]?.[1]
        || "Add the first position, or start from an RCM study: its system becomes a position, with the study's tasks."}</p>
      <div className="section-empty-action">
        {mode === "locations" ? (
          <button type="button" onClick={() => setModal("location")}><PlusIcon /> New location</button>
        ) : mode === "items" ? (
          <>
            <button type="button" onClick={() => setModal("item")}><PlusIcon /> New item</button>
            <button type="button" className="secondary" onClick={() => onMode("positions")}>Fit one to a position</button>
          </>
        ) : (
          <>
            <button type="button" onClick={() => setModal("position")}><PlusIcon /> New position</button>
            <button type="button" className="secondary" onClick={() => setModal("rcm")}>From an RCM study</button>
            <button type="button" className="secondary" onClick={() => setModal("import")}>Import from a spreadsheet</button>
          </>
        )}
      </div>
      <p className="section-empty-more"><ShowMe help={HELP}>How RCM studies become positions and tasks</ShowMe></p>
    </div>
  ) : (
    <div className="card empty">Pick a row in the tree to see it here.</div>
  );

  const paneEmpty = !data ? (error?.notAllowed ? "Not on for this account." : error ? "Couldn't load the tree." : "Loading the tree…")
    : filter && notPlaced && !query.trim() && !chips.length ? "Every position is at a location."
    : filter ? (
      <>Nothing matches{query.trim() ? ` “${query.trim()}”` : ""}. <button type="button" className="link" onClick={() => { setQuery(""); setChips([]); }}>Clear the filter</button></>
    ) : nothing ? `${EMPTY[mode]?.[0] || "No positions yet"}.` : "Nothing here.";

  const placedCount = data ? display.positions : 0;
  const n = (count, one, many = `${one}s`) => `${count.toLocaleString("en-AU")} ${count === 1 ? one : many}`;
  const notAnalysed = data ? data.positions.filter((p) => p.not_analysed).length : 0;
  const statusText = !data ? "" : rcmOn && !filter
    ? (rcmError ? `The RCM didn't load: ${rcmError}` : !rcm ? `${n(placedCount, "position")} · loading the RCM…`
      : `${n(placedCount, "position")} · ${notAnalysed.toLocaleString("en-AU")} not analysed · RCM is by position`)
    : filter
    ? `${n(filter.match.size, "match", "matches")}, shown with what they're inside`
    : mode === "locations"
      ? `${n(data.locations.length, "location")} · ${n(placedCount, "position")}`
      : mode === "items" ? n(display.items, "item") : n(placedCount, "position");

  const notice = notPlaced && (
    <p className="tp-notice">
      <span className="maint-badge">Not at a location yet</span>{" "}
      <Link to={explorerPath(mode)} replace>Show every position</Link>
    </p>
  );

  const row = (phone ? detailKey : focus) != null ? display.rows.get(phone ? detailKey : focus) : null;
  const posRow = selPos != null ? display.rows.get(selPos) : null;
  const fullButton = !phone && <FullScreenButton ref={fullBtn} full={full} onClick={toggleFull} />;

  // The RCM tab: the table's columns beside the tree, the heading over them,
  // and the details of the function, failure or mode picked.
  const cols = rprefs.cols.map((id) => COLUMN[id]).filter(Boolean);
  const widths = {};
  for (const c of cols) widths[c.id] = rprefs.widths[c.id] ?? c.width;
  const table = rcmOn ? {
    cols, widths, treeW: width, total: width + cols.reduce((t, c) => t + widths[c.id], 0),
    editing, readOnly: false,
    canEditName: (r) => EDITABLE.has(r.type),
    onEdit: (key, col) => { setRcmFocus(key); setEditing({ key, col }); },
    onCommit: commit, onCancel: () => setEditing(null), onDecision: (r) => setDeciding(r),
  } : null;
  const msg = message && <p className={"tt-msg " + message.tone} role="status">{message.text}</p>;
  const head = rcmOn && posRow && posRow.type === "pos" && (
    <div className="td tt-headpanel">
      <DetailHeader display={display} row={posRow} onSelect={reveal} tab={tab} onTab={setTab} headingRef={headingRef}
                    fullScreenButton={fullButton}
                    meta={rcm?.positions ? <span className="tt-rollup"><RollupBadges rollup={rollupOf(rcm, posRow.key)} /></span> : null}
                    actions={(
                      <>
                        <ColumnChooser cols={rprefs.cols} onCols={(next) => setRprefs((p) => ({ ...p, cols: next }))} />
                        <button type="button" className="sm" onClick={() => runAdd({ ref: { add: "fn", position_id: posRow.key } })}>Add function</button>
                      </>
                    )} />
      {msg}
    </div>
  );
  const detailsRow = rcmOn && panel && isRcmRow(focusRow) && focusRow.type !== "add" ? cellRow(focusRow) : null;
  const side = detailsRow && (
    <div className="rw tt-side">
      {phone && <div className="rw-scrim" onClick={() => setPanel(false)} aria-hidden="true" />}
      <Details r={detailsRow} display={display} readOnly={false} phone={phone} headingRef={detailsHeading} ops={ops}
               onCommit={commit} onAdd={addInside} onDelete={remove} onDecision={(r) => setDeciding(r)}
               onClose={() => { setPanel(false); document.getElementById(`tp-${focus}`)?.focus({ preventScroll: true }); }}
               onSelect={(k) => reveal(k)} />
    </div>
  );
  const phoneTabs = phone && posRow && posRow.type === "pos" && (
    <Tabs tabs={tabsFor(posRow)} value={shownTab(tab, posRow)} onChange={setTab} label="What to show" className="tp-tabs" />
  );
  const back = phone && (
    <button type="button" className="secondary td-back" onClick={() => navigate(-1)}>‹ {title}</button>
  );

  return (
    <div ref={frame} className={"tx" + (phone ? " phone" : "") + (phone && detailKey && !rcmOn ? " show-detail" : "")
      + (full ? " is-full" : "") + (rcmOn ? " tx-table" : "")}>
      <TreePane
        title={title}
        treeLabel={treeLabel}
        display={display}
        list={list}
        index={index}
        open={open}
        filter={filter}
        query={query}
        onQuery={setQuery}
        chips={chips}
        onChips={setChips}
        mode={mode}
        onMode={onMode}
        focus={focus}
        onPick={pick}
        onToggle={toggle}
        onLevel={setLevel}
        onCloseAll={() => setOpenSet(new Set())}
        phone={phone}
        width={width}
        onWidth={setWidth}
        collapsed={collapsed}
        onCollapse={setCollapsed}
        onNew={data ? () => setModal(mode === "locations" ? "location" : mode === "items" ? "item" : "position") : null}
        newLabel={mode === "locations" ? "New location" : mode === "items" ? "New item" : "New position"}
        menu={data && mode !== "locations" && mode !== "items" && (
          <>
            <button type="button" className="ovm-item" onClick={() => setModal("import")}>Import from a spreadsheet</button>
            <button type="button" className="ovm-item" onClick={() => setModal("rcm")}>From an RCM study</button>
          </>
        )}
        notice={notice}
        statusText={statusText}
        empty={phone && (error || nothing) ? emptyDetail : paneEmpty}
        scrollTo={scrollTo}
        onEnter={(key) => {
          const r = display.rows.get(key);
          if (r?.type === "add") return runAdd(r);
          if (isRcmRow(r)) {
            setPanel(true);
            return setTimeout(() => detailsHeading.current?.focus(), 0);
          }
          return phone ? pick(key, { go: true }) : headingRef.current?.focus();
        }}
        rcmMarks={rcmOn || chips.includes("unanalysed")}
        table={table}
        head={head}
        side={side}
        phoneTabs={phoneTabs}
        layoutKey={tab}
        anchorKey={selPos}
        arrangeLocked={rcmOn ? "RCM is by position, so the RCM tab shows the positions tree" : null}
      />
      {!rcmOn && <section className="tx-detail" aria-label="Details"
               onKeyDown={(e) => {
                 if (e.key === "Escape" && !phone && focus) document.getElementById(`tp-${focus}`)?.focus();
               }}>
        {(!phone || detailKey) && (
          <TreeDetail ref={headingRef} display={display} row={data && !nothing ? row : null} today={data?.today || ""}
                      onSelect={(k) => {
                        if (!phone) return reveal(k);
                        setSelected((s) => ({ ...s, [mode]: k }));
                        return navigate(location.pathname + location.search, { state: { treeDetail: k }, replace: true });
                      }}
                      back={back} version={version} empty={emptyDetail}
                      tab={tab} onTab={setTab} fullScreenButton={fullButton} />
        )}
      </section>}

      {modal === "position" && (
        <NewPositionModal positions={pickerList(data)} parentId={selPos && display.rows.get(selPos)?.type === "pos" ? selPos : null}
                          onClose={() => setModal(null)} onCreated={(p) => created(p.id)} />
      )}
      {modal === "location" && (
        <NewLocationModal
          locations={(data?.locations || []).map((l) => ({ ...l, parent: l.parent_id ? { name: data.locations.find((x) => x.id === l.parent_id)?.name } : null }))}
          parentId={focus && display.rows.get(focus)?.type === "loc" ? focus : null}
          onClose={() => setModal(null)} onDone={(l) => created(l.id)} />
      )}
      {modal === "item" && (
        <NewItemModal
          locations={(data?.locations || []).map((l) => ({ ...l, parent: l.parent_id ? { name: data.locations.find((x) => x.id === l.parent_id)?.name } : null }))}
          onClose={() => setModal(null)} onDone={(it) => created(it.id)} />
      )}
      {modal === "import" && <ImportModal onClose={() => setModal(null)} onDone={() => { setModal(null); load(); }} />}
      {modal === "rcm" && (
        <FromRcmModal positions={pickerList(data)} onClose={() => setModal(null)} onCreated={(r) => created(r.position.id)} />
      )}
      {deciding && options && (
        <DecisionModal options={options} mode={deciding.ref} onSave={saveDecision} onClose={() => setDeciding(null)} />
      )}
    </div>
  );
}

// A position's own evidence checks, for its heading on the RCM tab.
function rollupOf(rcm, positionId) {
  return (rcm.positions || []).find((p) => p.id === positionId)?.rollup || null;
}
