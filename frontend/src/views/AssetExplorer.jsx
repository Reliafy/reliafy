import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { getMaintenanceTree, listMaintenanceItems } from "../api.js";
import { useWorkspace } from "../WorkspaceProvider.jsx";
import TreePane from "../components/TreePane.jsx";
import TreeDetail from "../components/TreeDetail.jsx";
import { ShowMe } from "../components/SectionPage.jsx";
import { PlusIcon } from "../components/LibRows.jsx";
import { NewItemModal, NewLocationModal } from "./MaintenanceLists.jsx";
import { FromRcmModal, ImportModal, NewPositionModal } from "./MaintenanceHome.jsx";
import {
  ARRANGEMENTS, ancestorsOf, arrangementOf, buildDisplay, carryOver, clampWidth, computeFilter, explorerPath,
  filterOpen, flatten, levelSet, loadTreeState, saveTreeState,
} from "../assetTree.js";
import { EXPLORER_LABEL } from "../navigation.js";
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

const PHONE_QUERY = "(max-width: 720px)";
function usePhone() {
  const [phone, setPhone] = useState(() => window.matchMedia(PHONE_QUERY).matches);
  useEffect(() => {
    const mq = window.matchMedia(PHONE_QUERY);
    const onChange = () => setPhone(mq.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);
  return phone;
}

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
  const mode = arrangementOf(params.get("arrange"), saved.mode);
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

  const display = useMemo(() => buildDisplay(data, mode, mode === "items" ? itemList : null), [data, mode, itemList]);
  const filter = useMemo(() => (data ? computeFilter(display, {
    query, chips: mode === "items" ? chips.filter((c) => c !== "empty") : chips, extra: notPlaced ? (r) => r.type === "pos" && !r.ref.location : null,
  }) : null), [data, display, query, chips, notPlaced, mode]);
  useEffect(() => setFopen(filter ? filterOpen(filter) : null), [filter]);
  const defaultOpen = useMemo(() => levelSet(display, 2), [display]);
  const baseOpen = openBy[mode] || defaultOpen;
  const open = filter ? fopen || filterOpen(filter) : baseOpen;
  const { list, index } = useMemo(() => flatten(display, open, filter), [display, open, filter]);
  const focus = display.rows.has(selected[mode]) ? selected[mode] : list[0]?.key ?? null;

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
    setSelected((s) => ({ ...s, [mode]: key }));
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
    setSelected((s) => ({ ...s, [mode]: key }));
    if (phone && opts.go) navigate(location.pathname + location.search, { state: { treeDetail: key } });
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
    navigate(explorerPath(m), { state: keep ? { treeReveal: keep } : undefined });
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
  const statusText = !data ? "" : filter
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
  const back = phone && (
    <button type="button" className="secondary td-back" onClick={() => navigate(-1)}>‹ {title}</button>
  );

  return (
    <div className={"tx" + (phone ? " phone" : "") + (phone && detailKey ? " show-detail" : "")}>
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
        onEnter={(key) => (phone ? pick(key, { go: true }) : headingRef.current?.focus())}
      />
      <section className="tx-detail" aria-label="Details"
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
                      back={back} version={version} empty={emptyDetail} />
        )}
      </section>

      {modal === "position" && (
        <NewPositionModal positions={pickerList(data)} parentId={focus && display.rows.get(focus)?.type === "pos" ? focus : null}
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
    </div>
  );
}
