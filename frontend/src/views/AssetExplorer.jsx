import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { getMaintenanceTree, getRcmOptions, listMaintenanceItems } from "../api.js";
import { useWorkspace } from "../WorkspaceProvider.jsx";
import TreePane from "../components/TreePane.jsx";
import TreeDetail, { HeaderTabs, KIND, SlimHeader, forgetPositions, prefetchPosition } from "../components/TreeDetail.jsx";
import DecisionModal from "../components/DecisionModal.jsx";
import { RollupBadges } from "../components/RcmStatusBadge.jsx";
import { ColumnChooser, Details, EDITABLE } from "../components/RcmWorksheet.jsx";
import Tabs from "../components/ui/Tabs.jsx";
import { useAskText, useConfirm } from "../components/ConfirmProvider.jsx";
import useTreeRcm from "../components/useTreeRcm.js";
import {
  cellRow, graftRcm, hasLinkedEvidence, isRcmRow, openFor, positionOf, rowActions, tableCols, withTableCols,
} from "../explorerRcm.js";
import { COLUMN, LEVEL_OF, checkValue, loadPrefs, savePrefs } from "../rcmWorksheet.js";
import FullScreenButton from "../components/FullScreenButton.jsx";
import useFullScreen from "../components/useFullScreen.js";
import { hasOpenLayer, isFullScreenKey } from "../fullScreen.js";
import { shownTab, tabParam, tabsFor } from "../explorerTabs.js";
import { ShowMe } from "../components/SectionPage.jsx";
import { PlusIcon } from "../components/LibRows.jsx";
import { NewItemModal, NewLocationModal } from "./MaintenanceLists.jsx";
import { FromRcmModal, ImportModal, NewPositionModal } from "./MaintenanceHome.jsx";
import { DEFAULT_ARRANGEMENT, DEFAULT_LEVEL, changedFromUsual, levelShown, showingOnly } from "../treeControls.js";
import {
  ARRANGEMENTS, CHIPS, ancestorsOf, arrangementOf, buildDisplay, carryOver, clampWidth, computeFilter, explorerPath,
  filterOpen, flatten, levelSet, loadTreeState, saveTreeState,
} from "../assetTree.js";
import { canPin, crumbAction, inBranch, levelMatches, pinDisplay, pinPath, pinTarget } from "../treePin.js";
import { EXPLORER_LABEL } from "../navigation.js";
import { liveKids, moveTargets, summaryActions, viewOnlyReason, withPin } from "../treeRowMenu.js";
import { MoveModal, RenameModal, RetireModal } from "../components/TreeRowModals.jsx";
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
// it. Picking a function, failure or mode opens its details beside the table.
// Each row's menu (right-click, its ⋯ button, or Shift+F10) adds inside it (a
// function on a position, a functional failure on a function, a failure mode
// on a functional failure) and has the row's other actions; the heading's Add
// function adds to the position picked; the tree grows. On the Summary tab the tree is the positions alone
// and the page about the row picked is beside it. Full screen (F, Esc to leave)
// gives the tree and the panel the whole screen, as the RBD editor's.
//
// "Pin this branch" (a row's menu, or the pin in the panel's heading) shows
// only that row and what's inside it (treePin.js): ?pin=<id>, so Back un-pins
// and a link opens pinned; not remembered on this device. The tree's column
// header says so ("Pinned: <name>", its path in the tooltip, and a ✕ to show
// everything; on a phone the pinned row itself), with no row of its own, and
// "Show whole tree" heads the ⋯ menu. The way up in the panel's heading still shows the whole path: a crumb
// above the pinned row moves the pin up to it. Asked to show a row outside the
// branch (?sel=, a link, a new row), the page shows the whole tree again and
// says so; a pinned row that's gone (retired, deleted) quietly un-pins.
//
// Switching tabs moves nothing but what's meant to change (a wide screen): the
// same frame on both (TreePane's two slim rows over the tree, the panel's
// heading and tabs in them), the tree as wide on both, its scroll, what's open
// and the row picked kept, and the focus left on the tab picked.

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
  const { workspace, activeTeam } = useWorkspace();
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
  // A change Back should undo (pinning a branch, and un-pinning it).
  const pushQuery = useCallback((change, state) => {
    const q = new URLSearchParams(params);
    change(q);
    if (q.toString() === params.toString()) return;
    navigate(`${location.pathname}?${q}${location.hash}`, { state });
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
  // The level each arrangement was last opened to from the ⋯ menu (null once
  // rows are opened or closed one by one; the usual level before any).
  const [levelBy, setLevelBy] = useState({});
  const [fopen, setFopen] = useState(null);
  const [scrollTo, setScrollTo] = useState(null);
  const [modal, setModal] = useState(null);
  // The Summary tab's row menu: the row a new position or location goes
  // inside, and the row being renamed, moved or retired ({kind, row}).
  const [newParent, setNewParent] = useState(null);
  const [rowModal, setRowModal] = useState(null);
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
        forgetPositions();
        setData(d);
        setVersion((v) => v + 1);
      })
      .catch((e) => setError({ text: e.message, notAllowed: e.status === 404 || e.status === 403 }));
  }, []);
  useEffect(() => load(), [load]);

  // The RCM tab: the RCM read into the tree, and what's being worked on.
  const askText = useAskText();
  const confirm = useConfirm();
  // Read a moment after the tree is in, on the Summary tab too, so the first
  // switch to the RCM tab draws its rows at once.
  const { rcm, error: rcmError, ops } = useTreeRcm({ on: rcmOn, prefetch: !!data, onTreeChanged: load, askText });
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
  const say = (text, tone = "ok", { fade = false } = {}) => setMessage({ text, tone, at: Date.now(), fade });
  // A message about a change made from the Summary tab's row menu goes after a while.
  useEffect(() => {
    if (!message?.fade) return undefined;
    const t = setTimeout(() => setMessage((m) => (m === message ? null : m)), 6000);
    return () => clearTimeout(t);
  }, [message]);
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
  const whole = useMemo(() => (rcmOn && rcm ? graftRcm(base, rcm) : base), [base, rcmOn, rcm]);
  const linkedEvidence = useMemo(() => hasLinkedEvidence(rcm), [rcm]);
  // A branch pinned (?pin=): the pane's tree starts at that row, and
  // everything below (open rows, levels, the filter, counts) works on it alone.
  const pinParam = params.get("pin");
  const pinKey = data ? pinTarget(whole, mode, pinParam) : null;
  const display = useMemo(() => (pinKey ? pinDisplay(whole, pinKey) : whole), [whole, pinKey]);
  const [pinNote, setPinNote] = useState(null);
  // A pinned row that isn't in the tree (retired, deleted, or not one this
  // arrangement shows): quietly the whole tree again.
  useEffect(() => {
    if (data && pinParam && !pinKey) setQuery_((q) => q.delete("pin"));
  }, [data, pinParam, pinKey, setQuery_]);
  useEffect(() => {
    if (!pinNote) return undefined;
    const t = setTimeout(() => setPinNote(null), 8000);
    return () => clearTimeout(t);
  }, [pinNote]);
  const filter = useMemo(() => (data ? computeFilter(display, {
    query, chips: mode === "items" ? chips.filter((c) => c !== "empty") : chips, extra: notPlaced ? (r) => r.type === "pos" && !r.ref.location : null,
  }) : null), [data, display, query, chips, notPlaced, mode]);
  useEffect(() => setFopen(filter ? filterOpen(filter) : null), [filter]);
  const defaultOpen = useMemo(() => levelSet(whole, 2), [whole]);
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
  // (once each time the tab opens; what's open after that is yours). Before the
  // tab is drawn, so its rows don't appear closed for a frame and then open.
  const openedRcm = useRef(false);
  useLayoutEffect(() => {
    if (!rcmOn) {
      openedRcm.current = false;
      return;
    }
    if (!rcm || openedRcm.current || !display.rows.has(selected.positions)) return;
    openedRcm.current = true;
    const more = openFor(display, selected.positions);
    setOpenBy((o) => ({ ...o, positions: new Set([...(o.positions || levelSet(whole, 2)), ...more]) }));
  }, [rcmOn, rcm, display, whole, selected.positions]);

  // On the RCM tab, the Summary's page for the position picked is read a
  // moment ahead, so switching to Summary shows it whole at once.
  const selIsPos = selPos != null && display.rows.get(selPos)?.type === "pos";
  useEffect(() => {
    if (!rcmOn || !selIsPos) return undefined;
    const t = setTimeout(() => prefetchPosition(selPos, version), 400);
    return () => clearTimeout(t);
  }, [rcmOn, selIsPos, selPos, version]);

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
  // nor with a modifier: Ctrl+F still finds); Esc leaves it. In the tree too:
  // there F is full screen, not a jump to a row starting with F (TreePane's
  // fullScreenKey); the other letters still jump.
  useEffect(() => {
    if (phone) return undefined;
    const onKey = (e) => {
      if (e.defaultPrevented || !isFullScreenKey(e) || hasOpenLayer(document)) return;
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
    // Asked for a row outside the pinned branch: the whole tree again, and say so.
    const want = pending.current;
    if (want && pinKey && !display.rows.has(want) && whole.rows.has(want)) {
      setPinNote("Showing the whole tree again");
      setQuery_((q) => q.delete("pin"));
      return;
    }
    if (pending.current && display.rows.has(pending.current)) {
      const key = pending.current;
      pending.current = null;
      shown.current = mode;
      reveal(key);
    } else if (shown.current !== mode) {
      // Once per arrangement, as soon as the tree is in, whether or not a row
      // was remembered: else, with none remembered, the first row picked by a
      // click would be "revealed" here as the position it's on, taking the
      // pick off a function, failure or mode just clicked.
      shown.current = mode;
      if (display.rows.has(selected[mode])) reveal(selected[mode]);
    }
  }, [data, display, whole, pinKey, reveal, mode, selected, setQuery_]);

  const detailKey = phone ? location.state?.treeDetail : null;
  const pick = (key, opts = {}) => {
    const r = display.rows.get(key);
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

  // Adding from a row's menu, the heading or the details: the new row is
  // picked, the way down to it opened and brought into view once the RCM is
  // read again.
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
  // The confirm stays open (its button saying "Deleting…") until the server
  // has done it, so it's sent once; a refusal shows in the confirm.
  const remove = async (r) => {
    const level = LEVEL_OF[r.type].label.toLowerCase();
    const ok = await confirm({
      title: `Delete this ${level}?`, body: ops.removeText(r), confirmLabel: `Delete ${level}`,
      pendingLabel: "Deleting…", run: () => ops.remove(r).then(() => true),
    });
    if (!ok) return;
    setRcmFocus(isRcmRow(display.rows.get(r.parent)) ? r.parent : null);
    say(`Deleted the ${level}.`);
  };
  // Pin a branch: the address says so (Back undoes it). The selection stays
  // when it's inside the branch, else it's the pinned row; with `select`, the
  // pinned row is picked.
  const pinTo = (key, { select = false, state } = {}) => {
    if (!canPin(whole.rows.get(key), mode)) return;
    setPinNote(null);
    const keep = select || focus == null || !inBranch(whole, focus, key) ? key : focus;
    if (keep !== focus) {
      setRcmFocus(null);
      setSelected((s) => ({ ...s, [mode]: keep }));
    }
    const kr = whole.rows.get(keep);
    pushQuery((q) => {
      q.set("pin", key);
      q.set("sel", isRcmRow(kr) ? positionOf(kr) : keep);
    }, state);
  };
  // The whole tree again; with `select`, that row picked.
  const unpin = ({ select = null } = {}) => {
    setPinNote(null);
    if (select != null) {
      setRcmFocus(null);
      setSelected((s) => ({ ...s, [mode]: select }));
    }
    pushQuery((q) => q.delete("pin"));
  };
  // A crumb in the panel's heading: inside the branch it's picked; above it,
  // the pin moves up to it (one step at a time), or, for one of the pane's own
  // headings, the whole tree shows with it picked.
  const crumbGo = (key, select) => {
    const act = crumbAction(pinKey ? display : null, whole, mode, key);
    if (act === "select") return select(key);
    if (act === "pin") return pinTo(key, { select: true, state: phone && !rcmOn ? { treeDetail: key } : undefined });
    return unpin({ select: key });
  };
  const above = pinKey ? (key) => !display.rows.has(key) : null;
  const pinFor = (r) => (r && canPin(whole.rows.get(r.key), mode) ? {
    on: r.key === pinKey,
    onClick: () => (r.key === pinKey ? unpin() : pinTo(r.key, { select: true })),
  } : null);
  const pinItem = (r) => (canPin(r, mode)
    ? [r.key === pinKey ? { id: "unpin", label: "Show whole tree" } : { id: "pin", label: "Pin this branch" }] : []);

  // A row's menu (TreePane's rowMenu): what it offers, and doing it. On the
  // RCM tab, adding inside the row and its other actions; on the Summary tab,
  // changing the tree (new inside, rename, move, retire: treeRowMenu.js); and
  // on any row that can be pinned, Pin this branch.
  const viewOnly = viewOnlyReason(activeTeam);
  const kids = useMemo(() => liveKids(data?.positions), [data]);
  const rowMenu = {
    actions: (r) => (rcmOn
      ? [...(rcm ? rowActions(r, { canRename: !phone }) : []), ...pinItem(r)]
      : withPin(summaryActions(r, { mode, viewOnly, kidsOf: (k) => kids.get(k) || 0 }), pinItem(r))),
    onAction: (r, id) => {
      if (id === "tree-new") {
        setNewParent(r.key);
        setModal(r.type === "loc" ? "location" : "position");
      } else if (id === "tree-rename" || id === "tree-move" || id === "tree-retire") setRowModal({ kind: id.slice(5), row: r });
      else if (id === "pin") pinTo(r.key, { select: true });
      else if (id === "unpin") unpin();
      else if (id === "add-fn") runAdd({ ref: { add: "fn", position_id: r.key } });
      else if (id === "add-fail" || id === "add-mode") addInside(r);
      else if (id === "rename") { setRcmFocus(r.key); setEditing({ key: r.key, col: "name" }); }
      else if (id === "decide") setDeciding(r);
      else if (id === "delete") remove(r);
    },
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
  // The dialog stays open (Apply saying "Saving…") until the server has it;
  // a refusal shows in the dialog, with everything as it was typed.
  const saveDecision = async (answer) => {
    await ops.decide(deciding, answer);
    setDeciding(null);
    say("Saved the decision.");
  };

  const toggle = (key, force) => {
    setLevelBy((l) => ({ ...l, [mode]: null }));
    const next = new Set(open);
    const want = force ?? !next.has(key);
    if (want) next.add(key);
    else next.delete(key);
    setOpenSet(next);
  };

  // The levels: after closing, the pick moves up to the row it's hidden in.
  const setLevel = (n) => {
    setLevelBy((l) => ({ ...l, [mode]: n }));
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
    if (pinKey) skipPinOpen.current = true; // the pin stays with the arrangement it was made in
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

  // What isn't as usual in the tree's ⋯ menu, and putting it back: Positions,
  // the usual level, no Show only filters (the search box is on show, so it
  // stays as typed).
  const level = levelShown(levelBy, mode);
  const levelsOn = mode !== "flat" && mode !== "items";
  const chipsOn = CHIPS.filter((c) => chips.includes(c.id) && (!c.positionsOnly || mode !== "items") && (!c.rcmOnly || rcmOn));
  const changed = changedFromUsual({ mode, arrange: !rcmOn, level, levels: levelsOn, chips: chipsOn, pinned: !!pinKey });
  const resetView = () => {
    setChips([]);
    if (!rcmOn && mode !== DEFAULT_ARRANGEMENT) {
      setLevelBy((l) => ({ ...l, [DEFAULT_ARRANGEMENT]: DEFAULT_LEVEL }));
      onMode(DEFAULT_ARRANGEMENT); // its address has no pin
      return;
    }
    if (pinKey || (levelsOn && level !== DEFAULT_LEVEL && typeof level === "number")) {
      setLevelBy((l) => ({ ...l, [mode]: DEFAULT_LEVEL }));
      setOpenBy((o) => ({ ...o, [mode]: levelSet(whole, DEFAULT_LEVEL) }));
    }
    if (pinKey) {
      skipPinOpen.current = true;
      unpin();
    }
  };

  // When the pin changes (pinned, moved up, un-pinned, or Back): the pinned
  // row opens, and the way down to the row picked (and to the branch just
  // left), so it's in view. The ⋯ menu ticks a level only while what's open
  // still is one, counted from the tree's top.
  const seenPin = useRef(undefined);
  const skipPinOpen = useRef(false);
  useEffect(() => {
    if (!data || seenPin.current === pinKey) return;
    const was = seenPin.current;
    seenPin.current = pinKey;
    if (skipPinOpen.current) {
      skipPinOpen.current = false;
      return;
    }
    if (was === undefined && pinKey == null) return;
    const keys = [];
    if (pinKey) keys.push(pinKey);
    if (focus != null) keys.push(...ancestorsOf(whole, focus));
    if (was) keys.push(was, ...ancestorsOf(whole, was));
    if (filter) setFopen((s) => new Set([...(s || filterOpen(filter)), ...keys]));
    else {
      const next = new Set([...(openBy[mode] || defaultOpen), ...keys]);
      setOpenBy((o) => ({ ...o, [mode]: next }));
      if (levelsOn && typeof level === "number" && !levelMatches(display, next, level)) setLevelBy((l) => ({ ...l, [mode]: null }));
    }
    if (focus != null) setScrollTo({ key: focus, at: Date.now() });
  }); // eslint-disable-line react-hooks/exhaustive-deps

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
    setNewParent(null);
    pending.current = id;
    load();
  };
  const closeModal = () => {
    setModal(null);
    setNewParent(null);
  };
  // After a rename, move or retire from the row menu: the tree read again,
  // the row kept picked (moved: shown in its new place; retired: the row it
  // was inside picked instead), and a few words to say so.
  const rowChanged = (row, { select = row.key, text }) => {
    setRowModal(null);
    if (select != null) pending.current = select;
    load();
    say(text, "ok", { fade: true });
    if (select != null) setTimeout(() => document.getElementById(`tp-${select}`)?.focus({ preventScroll: true }), 300);
  };
  // Where a row can move to: its kind's tree, without it and what's inside it.
  const targetsFor = (row) => moveTargets(row.type === "loc" ? data?.locations : data?.positions, row.key);

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
  // Pinned: the branch's own counts.
  const notAnalysed = !data ? 0 : pinKey ? display.notAnalysed : data.positions.filter((p) => p.not_analysed).length;
  const locationCount = !data ? 0 : pinKey ? display.locations : data.locations.length;
  const statusText = !data ? "" : rcmOn && !filter
    ? (rcmError ? `The RCM didn't load: ${rcmError}` : !rcm ? `${n(placedCount, "position")} · loading the RCM…`
      : `${n(placedCount, "position")} · ${notAnalysed.toLocaleString("en-AU")} not analysed · RCM is by position`)
    : filter
    ? [`${n(filter.match.size, "match", "matches")}, shown with what they're inside`, showingOnly(chipsOn.map((c) => c.label))].filter(Boolean).join(" · ")
    : mode === "locations"
      ? `${n(locationCount, "location")} · ${n(placedCount, "position")}`
      : mode === "items" ? n(display.items, "item") : n(placedCount, "position");

  const notice = notPlaced && (
    <p className="tp-notice">
      <span className="maint-badge">Not at a location yet</span>{" "}
      <Link to={explorerPath(mode)} replace>Show every position</Link>
    </p>
  );

  // The panel shows the row from the whole tree, so its way up is the whole path.
  const row = (phone ? detailKey : focus) != null ? whole.rows.get(phone ? detailKey : focus) ?? null : null;
  const posRow = selPos != null ? display.rows.get(selPos) : null;
  const fullButton = !phone && <FullScreenButton ref={fullBtn} full={full} onClick={toggleFull} shortcutNote="also in the tree" />;

  // The RCM tab: the table's columns beside the tree, the heading over them,
  // and the details of the function, failure or mode picked.
  // The Evidence check column only once evidence is linked somewhere (or as
  // chosen in the Columns menu).
  const shownCols = tableCols(rprefs, linkedEvidence);
  const cols = shownCols.map((id) => COLUMN[id]).filter(Boolean);
  const widths = {};
  for (const c of cols) widths[c.id] = rprefs.widths[c.id] ?? c.width;
  const table = rcmOn ? {
    cols, widths, treeW: width, total: width + cols.reduce((t, c) => t + widths[c.id], 0),
    editing, readOnly: false,
    canEditName: (r) => EDITABLE.has(r.type),
    onEdit: (key, col) => { setRcmFocus(key); setEditing({ key, col }); },
    onCommit: commit, onCancel: () => setEditing(null), onDecision: (r) => setDeciding(r),
    // The position picked, when it has no functions yet: its row says how to start.
    hint: rcm?.positions && posRow?.type === "pos" && !posRow.rcmKids ? posRow.key : null,
  } : null;
  const msg = message && <p className={"tt-msg " + message.tone} role="status">{message.text}</p>;
  // The panel's heading and tabs, in the two slim rows over the tree on both
  // tabs (a wide screen): the same elements on each, so nothing in them is
  // drawn afresh and the focus stays on the tab picked.
  const summaryRow = !rcmOn && data && !nothing ? row : null;
  const head = phone ? null : rcmOn ? posRow && posRow.type === "pos" && (
    <SlimHeader display={whole} row={posRow} onSelect={reveal} onCrumb={(k) => crumbGo(k, reveal)} above={above}
                pin={pinFor(posRow)} headingRef={headingRef} fullScreenButton={fullButton} message={msg}
                meta={rcm?.positions ? <span className="tt-rollup"><RollupBadges rollup={rollupOf(rcm, posRow.key)} /></span> : null}
                actions={(
                  <>
                    <button type="button" className="sm"
                            // A double-click asks once (its second click is the dialog's, which ignores it).
                            onClick={(e) => { if (e.detail < 2) runAdd({ ref: { add: "fn", position_id: posRow.key } }); }}>Add function</button>
                    <ColumnChooser cols={shownCols} onCols={(next, o) => setRprefs((p) => withTableCols(p, next, shownCols, o))} />
                  </>
                )} />
  ) : summaryRow && (
    <SlimHeader display={whole} row={summaryRow} onSelect={reveal} onCrumb={(k) => crumbGo(k, reveal)} above={above}
                pin={pinFor(summaryRow)} headingRef={headingRef} fullScreenButton={fullButton}
                meta={KIND[summaryRow.type] ? <span className="tt-kind">{KIND[summaryRow.type]}</span> : null} primaryOpen
                message={message?.fade ? msg : null} />
  );
  const tabsRow = rcmOn ? (posRow?.type === "pos" ? posRow : null) : summaryRow;
  const headTabs = !phone && tabsRow && <HeaderTabs row={tabsRow} tab={tab} onTab={setTab} />;
  const detailsRow = rcmOn && panel && isRcmRow(focusRow) ? cellRow(focusRow) : null;
  const rcmSide = detailsRow && (
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
  // A row picked in the panel (a crumb, a row in "Directly inside").
  const selectFromPanel = (k) => {
    if (!phone) return reveal(k);
    setSelected((s) => ({ ...s, [mode]: k }));
    return navigate(location.pathname + location.search, { state: { treeDetail: k }, replace: true });
  };
  const back = phone && (
    <button type="button" className="secondary td-back" onClick={() => navigate(-1)}>‹ {title}</button>
  );
  // The Summary tab's page about the row picked: beside the tree in the pane
  // (a wide screen, its heading and tabs over it in the slim rows), or its own
  // screen on a phone.
  const summary = !rcmOn && (
    <section className="tx-detail" aria-label="Details"
             onKeyDown={(e) => {
               if (e.key === "Escape" && !phone && focus) document.getElementById(`tp-${focus}`)?.focus();
             }}>
      {(!phone || detailKey) && (
        <TreeDetail ref={headingRef} display={whole} row={data && !nothing ? row : null} today={data?.today || ""}
                    onSelect={selectFromPanel} onCrumb={(k) => crumbGo(k, selectFromPanel)} above={above}
                    pin={data && !nothing ? pinFor(row) : null}
                    back={back} version={version} empty={emptyDetail} headless={!phone}
                    tab={tab} onTab={setTab} fullScreenButton={fullButton} />
      )}
    </section>
  );
  const side = rcmOn ? rcmSide : phone ? null : summary;

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
        onCloseAll={() => {
          setLevelBy((l) => ({ ...l, [mode]: 0 }));
          setOpenSet(new Set());
        }}
        phone={phone}
        width={width}
        onWidth={setWidth}
        collapsed={collapsed}
        onCollapse={setCollapsed}
        onNew={data ? () => setModal(mode === "locations" ? "location" : mode === "items" ? "item" : "position") : null}
        newLabel={mode === "locations" ? "New location" : mode === "items" ? "New item" : "New position"}
        level={level}
        changed={changed}
        onReset={resetView}
        menuActions={data && mode !== "locations" && mode !== "items" ? [
          { id: "import", label: "Import from a spreadsheet", onSelect: () => setModal("import") },
          { id: "rcm", label: "From an RCM study", onSelect: () => setModal("rcm") },
        ] : []}
        notice={notice}
        statusText={statusText}
        empty={phone && (error || nothing) ? emptyDetail : paneEmpty}
        scrollTo={scrollTo}
        onEnter={(key) => {
          const r = display.rows.get(key);
          if (isRcmRow(r)) {
            setPanel(true);
            return setTimeout(() => detailsHeading.current?.focus(), 0);
          }
          return phone ? pick(key, { go: true }) : headingRef.current?.focus();
        }}
        rcmMarks={rcmOn || chips.includes("unanalysed")}
        table={table}
        rowMenu={rowMenu}
        fullScreenKey={!phone}
        head={head}
        headTabs={headTabs}
        side={side}
        phoneTabs={phoneTabs}
        // The row picked stays where it is on screen when the tab changes, and
        // when the RCM's rows first arrive.
        layoutKey={`${tab}:${rcmOn && rcm ? "rcm" : ""}`}
        anchorKey={selPos}
        branch={pinKey ? {
          key: pinKey, name: whole.rows.get(pinKey).ref.name || "(no name)", path: pinPath(whole, pinKey), onUnpin: () => unpin(),
        } : null}
        branchNote={pinNote}
        arrangeLocked={rcmOn ? "RCM is by position, so the RCM tab shows the positions tree" : null}
      />
      {phone && summary}

      {modal === "position" && (
        <NewPositionModal positions={pickerList(data)}
                          parentId={newParent ?? (selPos && display.rows.get(selPos)?.type === "pos" ? selPos : null)}
                          onClose={closeModal} onCreated={(p) => created(p.id)} />
      )}
      {modal === "location" && (
        <NewLocationModal
          locations={(data?.locations || []).map((l) => ({ ...l, parent: l.parent_id ? { name: data.locations.find((x) => x.id === l.parent_id)?.name } : null }))}
          parentId={newParent ?? (focus && display.rows.get(focus)?.type === "loc" ? focus : null)}
          onClose={closeModal} onDone={(l) => created(l.id)} />
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
      {rowModal?.kind === "rename" && (
        <RenameModal row={rowModal.row} onClose={() => setRowModal(null)}
                     onDone={(name) => rowChanged(rowModal.row, { text: `Renamed it “${name}”.` })} />
      )}
      {rowModal?.kind === "move" && (
        <MoveModal row={rowModal.row} targets={targetsFor(rowModal.row)} parentId={rowModal.row.ref.parent_id || null}
                   onClose={() => setRowModal(null)}
                   onDone={(to) => rowChanged(rowModal.row, { text: to ? `Moved it inside “${to}”.` : "Moved it to the top level." })} />
      )}
      {rowModal?.kind === "retire" && (
        <RetireModal row={rowModal.row} onClose={() => setRowModal(null)}
                     onDone={() => rowChanged(rowModal.row, {
                       select: rowModal.row.ref.parent_id && display.rows.has(rowModal.row.ref.parent_id) ? rowModal.row.ref.parent_id : null,
                       text: `Retired “${rowModal.row.ref.name}”.`,
                     })} />
      )}
      {deciding && options && (
        <DecisionModal options={options} mode={deciding.ref} onSave={saveDecision} onClose={() => setDeciding(null)} limits />
      )}
    </div>
  );
}

// A position's own evidence checks, for its heading on the RCM tab.
function rollupOf(rcm, positionId) {
  return (rcm.positions || []).find((p) => p.id === positionId)?.rollup || null;
}
