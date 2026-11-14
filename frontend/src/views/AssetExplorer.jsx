import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { madeTask } from "../taskStart.js";
import { VIEW_PARAMS } from "../measurementsTab.js";
import {
  MEAS_TABLE_COLS, MEAS_TREE_HEAD, MeasCell, MeasDialogs, MeasSide, measPhoneRow, measRowActions, retireMeasurement, useTreeMeasurements,
} from "../components/MeasurementTable.jsx";
import { graftMeasurements, isMeasRow, measAddActions, measKey, openForMeasurements, rollupText as measRollup } from "../explorerMeasurements.js";
import { measurementsCsv } from "../measurementsTable.js";
import {
  LibraryAttachModal, MODEL_COLUMNS, MODEL_TREE_HEAD, ModelCell, ModelDialogs, ModelSide, NewRbdModal, ParamsModal, RbdLinkModal, modelPhoneRow, modelRowActions,
  unlinkModel, useTreeModels,
} from "../components/ModelTable.jsx";
import { AddToLibraryDialog } from "../components/LibraryParts.jsx";
import { FitPane } from "../components/FitLifeModel.jsx";
import PredictionPane from "../components/PredictionPane.jsx";
import RbdPane from "../components/RbdPane.jsx";
import MissionPane, { NewMissionPane } from "../components/MissionPane.jsx";
import { MISSION_COLUMNS, MISSION_TREE_HEAD, MissionCell, MissionRollup, missionPhoneRow, useTreeMissions } from "../components/MissionTable.jsx";
import {
  NEW_MISSION, changedPhases, graftMissions, isMissionRow, isPhaseRow, missionKey, missionParam, missionRowActions, movePhase, openForMissions,
  parseMissionParam, phaseKey, positionMissionActions, rollupText as missionRollup, withNewPhase, withoutPhase,
} from "../explorerMissions.js";
import CovariateBindPane from "../components/CovariateBindPane.jsx";
import RedundancyPane from "../components/RedundancyPane.jsx";
import OperatingPlanPane from "../components/OperatingPlanPane.jsx";
import TreeSheetPane from "../components/TreeSheetPane.jsx";
import { bindingForRecord, bindingFromParam, bindingParam } from "../covariate.js";
import { PANE_PARAMS, TABLE_PANES, keepPaneFor, paneFromQuery, setPaneQuery } from "../tablePane.js";
import { fitPreset, priorFrom } from "../fitDialog.js";
import { MODEL_POSITION_ITEMS, MODEL_USUAL, attachGroups, builtRbdLink, graftModels, inUseWords, isModelRow, modelKey, openForModels, rollupText as modelRollup, classModelHint, lifeModelOf,
  opensInPane, bindingOf,
} from "../explorerModels.js";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import {
  createPositionMission, deleteMission, getMission, updateMission, getFmeaExcelBlob, getItemClasses, getMaintenanceTree, getProduct, getWorkspaceRcm, getPositionRcm, getRcmOptions,
  hasFmeaExcel, linkPositionModel, restoreRcm, restoreTree,
} from "../api.js";
import { useWorkspace } from "../WorkspaceProvider.jsx";
import TreePane from "../components/TreePane.jsx";
import TreeDetail, { HeaderTabs, SlimHeader, forgetPositions, prefetchPosition, rememberChange, usePosition } from "../components/TreeDetail.jsx";
import DecisionModal from "../components/DecisionModal.jsx";
import LinkFailurePicker from "../components/FailureLinks.jsx";
import RcmImportModal from "../components/RcmImportModal.jsx";
import RcmMoveModal from "../components/RcmMoveModal.jsx";
import { MeasurementMoveModal } from "../components/TaskMeasurement.jsx";
import { withMeasurement } from "../taskMeasurement.js";
import useRcmDrag from "../components/useRcmDrag.js";
import {
  answerNotes, dragBlock, dragSource, moveItems, planDrop, refusalText, shownAfter, stepTarget, undoBatch,
} from "../rcmDrag.js";
import { exportFilename, importSummary, positionRcmCsv } from "../rcmImport.js";
import { saveText } from "../sparesPlan.js";
import { RollupBadges } from "../components/RcmStatusBadge.jsx";
import { ColumnChooser, Details, EDITABLE } from "../components/RcmWorksheet.jsx";
import { ShrinkIcon } from "../components/icons.jsx";
import Tabs from "../components/ui/Tabs.jsx";
import { useAskText, useConfirm } from "../components/ConfirmProvider.jsx";
import useTreeRcm from "../components/useTreeRcm.js";
import {
  NARROW_TABLE, cellRow, functionSummary, graftRcm, hasLinkedEvidence, isRcmRow, newStandardRows, openFor, opensItem, opensPanel, positionOf, rowActions,
  standardKeys, tableCols, unlinkEmptiesFailure, usualCols,
  withTableCols, workingsFor,
} from "../explorerRcm.js";
import { COLUMN, LEVEL_OF, checkValue, loadPrefs, savePrefs, tasksOf } from "../rcmWorksheet.js";
// The FME(C)A tab: the same tree-table with the worksheet's columns, its own
// graft (a function's failure modes right under it), chips, prefs and checks.
import { failuresOn as fmeaFailuresOn, graftFmea, positionSummary, rowActions as fmeaRowActions } from "../explorerFmea.js";
import {
  CHIP_IDS as FMEA_CHIP_IDS, COLUMN as FMEA_COLUMN, COLUMNS as FMEA_COLUMNS, TREE_HEAD as FMEA_TREE_HEAD, WIDE_TABLE, checkValue as checkFmeaValue,
  loadPrefs as loadFmeaPrefs, nextSort, phoneLine as fmeaPhoneLine, savePrefs as saveFmeaPrefs, scoredWords, siblingOrder as fmeaOrder,
  tableCols as fmeaTableCols, usualCols as fmeaUsualCols, withTableCols as withFmeaCols,
} from "../fmeaWorksheet.js";
import { readFmeaOptions } from "../fmea.js";
import RcmPositionPanel from "../components/RcmPositionPanel.jsx";
import { AssignFailureModal, FmeaPositionPanel } from "../components/FmeaPanels.jsx";
import { saveBlob } from "../sparesPlan.js";
import { saveErrorText } from "../confirm.js";
import FullScreenButton from "../components/FullScreenButton.jsx";
import useFullScreen from "../components/useFullScreen.js";
import { hasOpenLayer, isFullScreenKey, isTyping } from "../fullScreen.js";
import { addressTab, isDesignRow, rowKind, shownTab, tabCarried, tabForArrangement, tabsFor } from "../explorerTabs.js";
import { ShowMe } from "../components/SectionPage.jsx";
import { openGuide } from "../components/HelpButton.jsx";
import { PlusIcon } from "../components/LibRows.jsx";
import { NewLocationModal } from "./MaintenanceLists.jsx";
import { ImportModal, NewPositionModal } from "./MaintenanceHome.jsx";
import { DEFAULT_LEVEL, changedFromUsual, levelShown, showingOnly } from "../treeControls.js";
import {
  ARRANGEMENTS, CHIPS, PANE, ancestorsOf, arrangementFor, arrivalNamed, arrivalRoot, assetOf, assetOfId, opensAsset, rcmPositionOf, scopedArrangeQuery, scopedArrangements, buildDisplay, carryOver, clampWidth, computeFilter, explorerPath, fitTreeWidth, treeColumnWidth,
  filterOpen, flatten, levelSet, loadTreeState, saveTreeState,
} from "../assetTree.js";
import { keepLevel } from "../outlineTree.js";
import { canPin, crumbAction, inBranch, levelMatches, pinCoversAll, pinDisplay, pinPath, pinTarget } from "../treePin.js";
import { EXPLORER_LABEL } from "../navigation.js";
import { ASSETS_LIST_PATH, explorerCarry } from "../maintenanceAssets.js";
import { addsFirst, isolateItems, liveKids, lsaLead, maintenanceLead, moveTargets, showsAddRow, summaryActions, tabMenu as menuOnTab, viewOnlyReason, withPin } from "../treeRowMenu.js";
import { canIsolate, depthWords, isolateIncompleteItem, isolateIncompleteOpen, isolateOpen, levelsBelow } from "../treeIsolate.js";
import { removeTaskFromMode } from "../components/RcmModeTasks.jsx";
import { MoveModal, RenameModal } from "../components/TreeRowModals.jsx";
import { DeleteRcmModal, DeleteTreeModal } from "../components/DeleteTree.jsx";
import { DELETE_KIND, undoneText } from "../treeDelete.js";
import { RCM_DELETE_KIND, deletesWithCascade, rcmDeleteId, rcmUndoneText } from "../rcmDelete.js";
import NewFailureReportModal from "../components/NewFailureReportModal.jsx";
import LogEventModal from "../components/LogEventModal.jsx";
import usePhone from "../usePhone.js";
import {
  PRODUCTS_PATH, designActions, isDesignScope, scopeHasClasses, scopeTree,
} from "../products.js";
import { BuildItemModal } from "../components/ProductPanels.jsx";
import "./Maintenance.css";
import "./AssetExplorer.css";

// The new-position (or new-location) dialog opened from the tree's last row:
// at the top level, whatever row is picked.
const TOP = "\u0000top";

// Assets › Explorer: one page, one tree pane over the whole
// register, arranged by positions or by locations (the switch in the pane's
// heading, and the address follows: ?arrange=). The
// tree is a second-level menu beside the site menu; the panel beside it shows
// the row picked; its heading's "…" menu has "Open the full page" for the
// position's (or location's, or item's) own page. On a phone the tree is the whole screen
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
// Under each failure mode, one row per task of its decision (the fifth level,
// explorerRcm.js modeTaskRows): picked, its own details (kind and interval,
// what's done when found, instructions, evidence, what it serves, logistics).
// A task row is addressed like any row: ?tab=rcm&sel=T:<mode>:<task>.
// Each row's menu (right-click, its ⋯ button, or Shift+F10) adds inside it (a
// function on a position, a functional failure on a function, a failure mode
// on a functional failure) and has the row's other actions; the tree grows. On the Summary tab the tree is the positions alone
// and the page about the row picked is beside it. Full screen (F, Esc to leave)
// gives the tree and the panel the whole screen, as the RBD editor's.
//
// The panel's heading has the same two controls on every tab: the "…" menu
// (the tab's own items that aren't a row's: the RCM's Import worksheet…,
// Export CSV and Columns…; Open the full page last) and Full screen. Adding,
// pinning and the row's other changes are in the tree's row menu.
//
// "Pin this branch" (a row's menu, or its right-click) shows
// only that row and what's inside it (treePin.js): ?pin=<id>, so Back un-pins
// and a link opens pinned; not remembered on this device. The tree's column
// header says so ("Pinned: <name>", its path in the tooltip, and a ✕ to show
// everything; on a phone the pinned row itself), with no row of its own, and
// "Show whole tree" heads the ⋯ menu. The way up in the panel's heading still shows the whole path: a crumb
// above the pinned row moves the pin up to it. Asked to show a row outside the
// branch (?sel=, a link, a new row), the page shows the whole tree again and
// says so; a pinned row that's gone (retired, deleted) quietly un-pins.
//
// "Focus ›" in a row's menu (both tabs; treeIsolate.js) is a one-off change
// to what's open: every other branch closes (still on show), the rows above
// it stay open, and it opens 1, 2 or 3 levels below it, or all of them. Then
// it's picked and brought into view. Nothing is hidden and the address stays.
//
// The RCM tab's row menus: Move to… (and a failure mode's Move a task…) on
// every row that moves, with the mouse too: one picker for every kind
// (RcmMoveModal), the way to move without dragging and the easy way to move a
// long way. Move up / down (and a standard's) are offered only where there's
// no dragging: on a phone, and in a menu opened from the keyboard (Shift+F10
// or the Menu key), so the keyboard can still make every move a drag can.
//
// Switching tabs moves nothing but what's meant to change (a wide screen): the
// same frame on both (TreePane's two slim rows over the tree, the panel's
// heading and tabs in them), the tree as wide on both, its scroll, what's open
// and the row picked kept, and the focus left on the tab picked.

const HELP = { guide: "rcm-on-your-asset-tree" };
const HELP_FMEA = { guide: "fmea-on-your-asset-tree" };
const HELP_TREE = { guide: "build-your-asset-tree" };

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

// The FME(C)A worksheet's text columns: a parent row's "3 of 5 scored" runs
// across the first of them it shows (they're blank on a parent row).
const FMEA_ROLLUP_COLS = new Set(["failure", "cause", "effect_local", "effect_next", "effects", "detection_method"]);

// Scoped to one tree (`root`, or ?root=: a product's design from its page, an
// item's tree from Items) it shows that tree alone, by position; unscoped, it
// leaves the products' designs and items' trees out (products.js). `tabKey`:
// the address's name for its tabs (?view= on a product's page). `heading`: the
// picked row's heading level (1 where the tree is the page, as a product's is).
export default function AssetExplorer({ root: rootProp = null, tabKey = "tab", title: titleProp = null, heading: headingProp = null }) {
  const navigate = useNavigate();
  const location = useLocation();
  const [params] = useSearchParams();
  const root = rootProp || params.get("root") || null;
  const { workspace, activeTeam } = useWorkspace();
  const phone = usePhone();
  const narrow = useNarrowTable();
  const wide = useWideTable();
  const saved = useMemo(() => loadTreeState(workspace), [workspace]);
  const tab = addressTab(params.get(tabKey), { arrange: params.get("arrange"), sel: params.get("sel") });
  // The tree-table: the RCM tab, or the FME(C)A tab (the same table with the
  // worksheet's columns and its own graft; `fmeaOn` says which).
  const fmeaOn = tab === "fmea";
  const rcmOn = tab === "rcm" || fmeaOn;
  // The Measurements tab is a tree-table too (Derryn, 9 Nov 2026: "line up with the
  // tree, just like in the RCM table"): each position's measurement rows hang under
  // it, with the table's columns beside them. `tableOn`: either table.
  const measOn = tab === "measurements";
  // The Modelling tab (Derryn, 9 Nov 2026): the life models on each position hang under it, the same way.
  const modelsOn = tab === "models";
  // The Missions tab (Derryn, 9 Nov 2026): each position's RBD missions hang under it, the same way.
  const missionsOn = tab === "missions";
  const tableOn = rcmOn || measOn || modelsOn || missionsOn;
  // RCM (and the FME(C)A) is by position: on its tab the tree is arranged by positions.
  // One tree on show (a product's design, an item's tree) opens by positions; its
  // Locations (?arrange=locations) are its own layout, never what's remembered here.
  // An asset's tree has Classes too (?arrange=classes): the classes of what's fitted
  // inside that asset, and nothing else's (a design has nothing fitted, so no Classes).
  const [read, setData] = useState(null);
  // The tree read is for the root it was read with: a new root (Classes on the picked row's asset,
  // an asset opened on its own) takes the address at its word until its own read
  // is in, and the last tree isn't drawn meanwhile (another asset's rows never show in this one's).
  const [dataRoot, setDataRoot] = useState(root);
  const data = dataRoot === root ? read : null;
  const scopedClasses = !!root && scopeHasClasses(data, { ownPage: !!rootProp });
  const mode = arrangementFor({ param: params.get("arrange"), remembered: saved.mode, rcm: tableOn, scoped: !!root, classes: scopedClasses });
  const notPlaced = mode === "positions" && params.get("place") === "none";
  const title = titleProp || EXPLORER_LABEL;
  // Inside a product's page (its own h1), the picked row's name is an h2.
  const heading = headingProp ?? (rootProp ? 2 : 1);
  const treeLabel = ARRANGEMENTS.find((a) => a.value === mode).tree;

  // The address always says the arrangement, so it can be shared as it is.
  useEffect(() => {
    if (rootProp || params.get("arrange") === mode) return; // a product's page keeps its own address
    const q = new URLSearchParams(params);
    q.set("arrange", mode);
    navigate(`${location.pathname}?${q}${location.hash}`, { replace: true, state: location.state });
  }, [params, mode, navigate, location, rootProp]);

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

  const [error, setError] = useState(null);
  const [version, setVersion] = useState(0);
  const [openBy, setOpenBy] = useState(saved.open);
  const [selected, setSelected] = useState(saved.selected);
  const [width, setWidth] = useState(() => clampWidth(saved.width, window.innerWidth));
  // A width the user dragged to (kept); until then the tree column fits its names, the same on every tab (fitWidth below).
  const [widthSet, setWidthSet] = useState(() => !!saved.widthSet);
  // The edge dragged (or ← →): kept; double-clicked (back to the usual width): fitted again.
  const onWidth = useCallback((w) => {
    setWidth(w);
    setWidthSet(w !== PANE.initial);
  }, []);
  const [collapsed, setCollapsed] = useState(saved.collapsed);
  const [query, setQuery] = useState("");
  const [chips, setChips] = useState([]);
  // The level each arrangement was last opened to from the ⋯ menu (null once
  // rows are opened or closed one by one; the usual level before any).
  const [levelBy, setLevelBy] = useState({});
  const [fopen, setFopen] = useState(null);
  const [scrollTo, setScrollTo] = useState(null);
  const [modal, setModal] = useState(null);
  // Excel import and export (TreeSheetPane): {start: "import" | "export", branch: {id, name} | null, n}, in the
  // panel's place beside the tree (no modal), or null. Not a row's: it stays open while rows are picked.
  const [sheet, setSheet] = useState(null);
  const sheetHeading = useRef(null);
  // The Summary tab's row menu: the row a new position or location goes
  // inside, and the row being renamed, moved or retired ({kind, row}).
  const [newParent, setNewParent] = useState(null);
  const [newAt, setNewAt] = useState(null); // New position here: the place it's made at
  const [rowModal, setRowModal] = useState(null);
  // A failure report being filed ({id, name}: the position; select: the row
  // to show it under on the Failure reports tab once filed).
  const [reportFor, setReportFor] = useState(null);
  const [eventFor, setEventFor] = useState(null); // Log an event…: {id, name} of the position
  const [buildFor, setBuildFor] = useState(null); // the product the row menu's Build an item… is for
  const headingRef = useRef(null);
  const detailsHeading = useRef(null);
  const frame = useRef(null);
  const fullBtn = useRef(null);
  // The "…" items the tab's body gives (the failure reports', measurements',
  // signals': panelMenu.js), and the RCM's column chooser opened from it.
  const [tabMenu, setTabMenu] = useState(null);
  const [colsOpen, setColsOpen] = useState(false);
  // The Measurements tab: its columns (remembered), and a dialog its actions open.
  const [measCols, setMeasColsState] = useState(() => {
    try {
      const got = JSON.parse(localStorage.getItem("reliafy.measurements.treecols") || "null");
      if (Array.isArray(got) && got.length) return MEAS_TABLE_COLS.map((c) => c.id).filter((id) => got.includes(id));
    } catch { /* storage blocked: the usual columns */ }
    return MEAS_TABLE_COLS.map((c) => c.id);
  });
  const setMeasCols = (next) => {
    setMeasColsState(next);
    try { localStorage.setItem("reliafy.measurements.treecols", JSON.stringify(next)); } catch { /* not kept */ }
  };
  const [measModal, setMeasModal] = useState(null);
  // The Modelling tab: its columns (remembered; B10 is offered in Columns…), and a dialog its actions open.
  const [modelCols, setModelColsState] = useState(() => {
    try {
      const got = JSON.parse(localStorage.getItem("reliafy.models.treecols") || "null");
      if (Array.isArray(got) && got.length) return MODEL_COLUMNS.map((c) => c.id).filter((id) => got.includes(id));
    } catch { /* storage blocked: the usual columns */ }
    return MODEL_USUAL;
  });
  const setModelCols = (next) => {
    setModelColsState(next);
    try { localStorage.setItem("reliafy.models.treecols", JSON.stringify(next)); } catch { /* not kept */ }
  };
  const [modelModal, setModelModal] = useState(null);
  // "Fit a life model…", "Add a prediction…" and a position's RBD fill the table area (?fit= /
  // ?predict=<position id>, ?rbd=<RBD id>&on=<position id>, so a reload keeps it open;
  // tablePane.js), the tree kept beside it (Derryn, 9 Nov 2026: "It shouldn't be a modal itself").
  // `paneSeed`: what the opener chose for it ({kind, id, start, link, built, n}); a reload opens it
  // fresh. `paneDirty`: whether anything in it has been changed
  // (leaving it for another row asks first only then).
  const [paneSeed, setPaneSeed] = useState(null);
  const paneDirty = useRef(false);
  const paneSaving = useRef(false);
  const paneHeading = useRef(null);
  const { full, toggle: toggleFull } = useFullScreen(frame, { returnFocus: fullBtn });
  const pending = useRef(params.get("sel") || paneFromQuery(params)?.id || location.state?.treeReveal || null);

  // The address and router state as they are now, for the tree read's answer (it lands later).
  const here = useRef(null);
  here.current = { params, location, navigate, root };
  const load = useCallback(() => {
    setError(null);
    const show = (d) => {
      if (here.current.root !== root) return; // a read for a tree no longer asked for
      forgetPositions();
      setData(scopeTree(d, root));
      setDataRoot(root);
      setVersion((v) => v + 1);
    };
    // One asset open (?root=): read that asset alone, so nothing of another one is sent.
    getMaintenanceTree({ within: root })
      .then((d) => {
        // There's no whole-register Explorer (Derryn, 14 Nov 2026: "If they want to see every
        // asset, they can't. They have to go out and view all the assets and select one at a
        // time."). A link that named a row lands on that row's asset, on its own (arrivalRoot);
        // anything else (the bare address, an old ?all=1 link, a row in no asset) lands on the
        // Assets list, to pick one. The register's read only says where to go: it's never drawn.
        // (?place=none, the positions at no place, is the one view without a root.)
        if (!root) {
          const { params: now, location: at, navigate: go, root: rootNow } = here.current;
          if (rootNow) return undefined; // one asset opened meanwhile: its own read is on its way
          // What the address asked for (a tab, a pane, a Library record to fit) comes along, to
          // the asset picked there.
          const toAssets = () => (now.get("place") ? show(d)
            : go(ASSETS_LIST_PATH, { replace: true, state: { fromExplorer: explorerCarry(now) } }));
          const isolate = (to) => {
            const q = new URLSearchParams(now);
            q.set("root", to);
            go(`${at.pathname}?${q}${at.hash}`, { replace: true, state: at.state });
          };
          const to = arrivalRoot(d, now, paneFromQuery(now)?.id);
          if (to) return isolate(to);
          // A link to an RCM row (a function, a failure mode: a decision's linked working) names
          // no tree row: the position whose RCM holds it says which asset.
          const named = arrivalNamed(d, now);
          if (named) {
            return getWorkspaceRcm().then((rcm) => {
              const pos = rcmPositionOf(rcm, named);
              const asset = pos ? assetOfId(d, pos) : null;
              if (asset) return isolate(asset);
              return toAssets();
            }, toAssets);
          }
          return toAssets();
        }
        return show(d);
      })
      .catch((e) => {
        const refused = e.status === 404 || e.status === 403;
        // One asset asked for and not found: gone (deleted, or an old link) when the whole
        // register still reads; else Maintenance isn't on here.
        if (root && e.status === 404) {
          getMaintenanceTree().then(() => setError({ text: e.message, gone: true }),
                                    () => setError({ text: e.message, notAllowed: true }));
          return;
        }
        setError({ text: e.message, notAllowed: refused });
      });
  }, [root]);
  useEffect(() => load(), [load]);
  // A delete made on a full page (a position or location) comes here with its
  // toast and Undo (the router's state), shown once.
  useEffect(() => {
    const d = location.state?.deleted;
    if (!d) return;
    setToast({ text: d.text, restore: { kind: d.kind, id: d.id, name: d.name }, at: Date.now() });
    navigate(`${location.pathname}${location.search}`, { replace: true, state: null });
  }, [location.state]); // eslint-disable-line react-hooks/exhaustive-deps
  // So does a few words about what was just added (Products' ready-made product):
  // beside the heading for a while, or, with more to read, in a toast that stays.
  useEffect(() => {
    const note = location.state?.note;
    if (!note?.text) return;
    if (note.fade) say(note.text, "ok", { fade: true });
    else setToast({ text: note.text, stay: true, at: Date.now() });
    navigate(`${location.pathname}${location.search}`, { replace: true, state: null });
  }, [location.state]); // eslint-disable-line react-hooks/exhaustive-deps

  // The RCM tab: the RCM read into the tree, and what's being worked on.
  const askText = useAskText();
  const confirm = useConfirm();
  // Read a moment after the tree is in, on the Summary tab too, so the first
  // switch to the RCM tab draws its rows at once.
  const { rcm, error: rcmError, ops, load: loadRcm } = useTreeRcm({ on: rcmOn, prefetch: !!data, onTreeChanged: load, askText, within: root });
  // A position an FMEA / RCM worksheet is being imported onto ({id, name}).
  const [sheetFor, setSheetFor] = useState(null);
  const [rcmFocus, setRcmFocus] = useState(null); // a function, failure or mode picked (its position is selected)
  const [notesAt, setNotesAt] = useState(null); // a function's notes asked for in full: {key, at}
  const [panel, setPanel] = useState(false); // its details beside the table
  const [editing, setEditing] = useState(null); // {key, col}: a cell being edited
  const [deciding, setDeciding] = useState(null); // a failure mode in the decision dialog
  // The details filling the table's room, the tree column kept beside them
  // (a double-click on a row's name, Open…, Expand). Picking another row
  // keeps it; once the details close it ends, so the next click on a row
  // shows them beside the table again.
  const [expanded, setExpanded] = useState(false);
  useEffect(() => { if (!panel && expanded) setExpanded(false); }, [panel, expanded]);
  const [addStart, setAddStart] = useState(null); // {key, list, at}: a row's list in its details opened on its add row (a row menu's Add …)
  const [linking, setLinking] = useState(null); // {row, direction}: the picker that links functional failures
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
  // The FME(C)A tab's own: its columns (remembered apart from the RCM's), the
  // action priority table from the options, the column sorted by, and
  // whether the server offers the Excel export (asked once per position picked).
  const [fprefs, setFprefs] = useState(() => loadFmeaPrefs());
  useEffect(() => {
    const t = setTimeout(() => saveFmeaPrefs(fprefs), 200);
    return () => clearTimeout(t);
  }, [fprefs]);
  const fopts = useMemo(() => readFmeaOptions(options?.fmea), [options]);
  const [fsort, setFsort] = useState(null); // {col, dir}
  const [excel, setExcel] = useState(null); // null: not asked yet
  const [assigning, setAssigning] = useState(null); // a "No functional failure yet" row: Assign to a functional failure…
  const say = (text, tone = "ok", { fade = false } = {}) => setMessage({ text, tone, at: Date.now(), fade });
  // A message about a change made from the Summary tab's row menu goes after a while.
  useEffect(() => {
    if (!message?.fade) return undefined;
    const t = setTimeout(() => setMessage((m) => (m === message ? null : m)), 6000);
    return () => clearTimeout(t);
  }, [message]);
  // Rearranging the RCM by drag and drop (or a row menu's Move to…): the
  // failure modes picked to move together, the toast with Undo after a move,
  // the Move to… dialog, and the words said to screen readers.
  const [picked, setPicked] = useState(() => new Set());
  // A delete's toast has restore ({kind, id, name}) in place of undo.
  const [toast, setToast] = useState(null); // {text, undo, extra, show, at, busy, restore, stay}
  const [moving, setMoving] = useState(null); // {src} or {taskFrom}: the Move to… dialog
  // A move asking what its tasks by use count there: {need, choose, cancel}.
  const [measuring, setMeasuring] = useState(null);
  const [spoken, setSpoken] = useState("");
  const announce = useCallback((text) => setSpoken((was) => (was === text ? `${text}\u00a0` : text)), []);
  useEffect(() => {
    if (!toast || toast.busy || toast.stay) return undefined; // stay: more to read, there until dismissed
    const t = setTimeout(() => setToast((x) => (x === toast ? null : x)), toast.undo || toast.restore ? 12000 : 5000);
    return () => clearTimeout(t);
  }, [toast]);
  // By Classes: the item-class taxonomy, read with the tree (and again after each change). Until
  // it's in, the tree is empty rather than every position under "No class" for a moment.
  const [classTree, setClassTree] = useState(null);
  const byClasses = mode === "classes";
  useEffect(() => {
    if (!byClasses) return undefined;
    let live = true;
    getItemClasses()
      .then((d) => live && setClassTree(d.tree || []))
      .catch(() => live && setClassTree([]));
    return () => { live = false; };
  }, [byClasses, version]);
  const base = useMemo(() => buildDisplay(byClasses ? (data && classTree ? { ...data, classes: classTree } : null) : data, mode),
    [data, mode, byClasses, classTree]);
  // By Classes, a position's Summary reads its row in the Positions tree (what's inside it,
  // what's overdue there or inside), the same facts whichever way the tree is arranged.
  const structure = useMemo(() => (byClasses && data ? buildDisplay(data, "positions") : null), [byClasses, data]);
  // The Measurements tab: every position's points, settings, channels and consumables.
  const meas = useTreeMeasurements({ on: measOn && !!data, display: data ? base : null });
  // The Modelling tab: every model attached to a position.
  const pmodels = useTreeModels({ on: modelsOn && !!data, within: root });
  // The Missions tab: every position's RBDs and their missions.
  const pmissions = useTreeMissions({ on: missionsOn && !!data, within: root });
  const whole = useMemo(() => (rcmOn && rcm ? (fmeaOn ? graftFmea(base, rcm) : graftRcm(base, rcm))
    : measOn && meas.data ? graftMeasurements(base, meas.data, data?.today || new Date().toISOString().slice(0, 10), meas.fittedAt)
      : modelsOn && pmodels.links ? graftModels(base, pmodels.links)
        : missionsOn && pmissions.links ? graftMissions(base, pmissions.links, pmissions.hasModel, pmissions.otherModel)
          : base), [base, rcmOn, fmeaOn, rcm, measOn, meas.data, meas.fittedAt, data?.today, modelsOn, pmodels.links, missionsOn, pmissions.links, pmissions.hasModel, pmissions.otherModel]);
  const linkedEvidence = useMemo(() => hasLinkedEvidence(rcm), [rcm]);
  // The modes picked that are still in the tree after a read.
  useEffect(() => {
    setPicked((was) => {
      if (!was.size) return was;
      const kept = [...was].filter((k) => whole.rows.get(k)?.type === "mode");
      return kept.length === was.size ? was : new Set(kept);
    });
  }, [whole]);
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
    query, chips, extra: notPlaced ? (r) => r.type === "pos" && !r.ref.location : null,
  }) : null), [data, display, query, chips, notPlaced]);
  useEffect(() => setFopen(filter ? filterOpen(filter) : null), [filter]);
  const defaultOpen = useMemo(() => levelSet(whole, 2), [whole]);
  const baseOpen = openBy[mode] || defaultOpen;
  const open = filter ? fopen || filterOpen(filter) : baseOpen;
  // The FME(C)A tab's sort (a column header clicked): the failure modes under
  // each function in that order; the tree itself stays as it is.
  const order = useMemo(() => (fmeaOn && fsort ? fmeaOrder(display, fsort) : null), [fmeaOn, fsort, display]);
  const { list, index } = useMemo(() => flatten(display, open, filter, order), [display, open, filter, order]);
  // The tree column (a wide screen): fitted to the names on show until the user drags it (the
  // review, Nov 2026: at 1600 px names were cut to a few letters). The same width on every tab,
  // so switching tabs moves nothing: worked out from the tree with its RCM in it (read with the
  // tree, whatever the tab) and the rows open in this arrangement, not from the tab's own rows.
  // (A product's page doesn't fit: it opens at the usual width, treeColumnWidth.)
  const fitTree = useMemo(() => (!phone && !widthSet && !rootProp && data ? (rcm ? graftRcm(base, rcm) : base) : null),
    [phone, widthSet, rootProp, data, rcm, base]);
  const fitWidth = useMemo(() => {
    if (!fitTree) return null;
    const shown = pinKey && fitTree.rows.has(pinKey) ? pinDisplay(fitTree, pinKey) : fitTree;
    const { list: rows } = flatten(shown, openBy[mode] || levelSet(fitTree, 2));
    return fitTreeWidth(rows.map((v) => {
      const r = shown.rows.get(v.key);
      // A reference row's "on <position>" after its name counts too.
      const on = r?.type === "cause" && r.ref?.on ? `   on ${r.ref.on}` : "";
      return { depth: v.depth, text: ((isRcmRow(r) ? r?.ref?.text : r?.ref?.name) || "") + on };
    }), window.innerWidth);
  }, [fitTree, pinKey, openBy, mode]);
  const shownWidth = treeColumnWidth({ width, widthSet, fit: fitWidth, product: !!rootProp });
  // A row asked for (?sel=, a link, a new row) that's in the tree is the one
  // shown, even before the effect below reveals it: else the first row is shown
  // for a render and its panels ask for the wrong row's data.
  const want = pending.current != null && display.rows.has(pending.current) ? pending.current : null;
  const focus = tableOn && rcmFocus && display.rows.has(rcmFocus) ? rcmFocus
    : want ?? (display.rows.has(selected[mode]) ? selected[mode] : list[0]?.key ?? null);
  const focusRow = focus != null ? display.rows.get(focus) : null;
  // The position the selection is on (a function, failure or mode: its position).
  const selPos = isRcmRow(focusRow) || isMeasRow(focusRow) || isModelRow(focusRow) || isMissionRow(focusRow) ? positionOf(focusRow) : focus;

  // A link on the page that names another row (?sel=: a task's row from the LSA tab's
  // Serves, a task's package): that row is revealed once it's in the tree, before the
  // address is set back to the position picked (the effect below).
  const selParam = params.get("sel");
  const lastSel = useRef(selParam);
  useEffect(() => {
    if (selParam === lastSel.current) return;
    lastSel.current = selParam;
    if (!selParam || selParam === selPos || selParam === focus) return;
    pending.current = selParam;
    if (display.rows.has(selParam)) reveal(selParam);
  }, [selParam]); // eslint-disable-line react-hooks/exhaustive-deps

  // With a tab open beyond Summary, the address follows the row picked
  // (?sel=), once the tree is in, so a link opens on it with that tab. A class
  // shows its one tab without the address naming it: walking on from the class
  // to a position names it there, so Condition monitoring stays picked
  // (explorerTabs.js tabCarried). The row walked to is the one whose details are
  // on show: on a phone that's the row the address's state names, which arrives
  // a render after the row is picked, so the walk is read from it (and the
  // address is changed with that state, not the one before it). Back at the
  // tree on a phone nothing is on show, so the next row opens as any row does
  // there: on the tab its address names.
  const walkedFrom = useRef(null);
  useEffect(() => {
    const at = phone ? location.state?.treeDetail : focus;
    const shown = at != null ? display.rows.get(at) ?? null : null;
    const from = walkedFrom.current;
    if (data) walkedFrom.current = shown;
    if (!data || selPos == null || pending.current) return;
    const carried = shown && from !== shown && shown.key === selPos ? tabCarried(from, shown, { named: params.has(tabKey) }) : null;
    if (!carried && (tab === "summary" || params.get("sel") === selPos)) return;
    // Another row: a report open in the Failure reports tab was the last row's.
    // A point or channel open in full in the Measurements tab was the last row's too, and so was
    // a fit or a prediction open in the Modelling tab's table area.
    setQuery_((q) => {
      if (carried) q.set(tabKey, carried);
      q.set("sel", selPos);
      q.delete("report");
      // The packaging open in the LSA tab was the last row's as well.
      if (q.get("packaging") !== selPos) q.delete("packaging");
      for (const k of VIEW_PARAMS) q.delete(k);
      keepPaneFor(q, selPos);
    });
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

  // A standard row (or a "No standard" row) that arrives with a read under a
  // function that is open opens too, so the functional failures on show stay
  // on show when they move under it (the one text split into a list, a first
  // standard added, a failure re-pointed). The rows known from the read
  // before are remembered; the first read is the baseline (openFor opens the
  // position picked).
  const stdSeen = useRef(null);
  useLayoutEffect(() => {
    if (!rcmOn || !rcm) {
      if (!rcmOn) stdSeen.current = null;
      return;
    }
    if (stdSeen.current === null) {
      stdSeen.current = standardKeys(whole);
      return;
    }
    const now = standardKeys(whole);
    const fresh = newStandardRows(whole, stdSeen.current, openBy.positions || defaultOpen);
    stdSeen.current = now;
    if (fresh.length) setOpenBy((o) => ({ ...o, positions: new Set([...(o.positions || levelSet(whole, 2)), ...fresh]) }));
  }, [rcmOn, rcm, whole]); // eslint-disable-line react-hooks/exhaustive-deps

  // After a worksheet is imported onto a position: that position opens down to
  // its failure modes once the RCM is read again.
  // Opening the Measurements tab opens the position picked, so its rows show
  // (once each time the tab opens, once its measurements are in).
  const openedMeas = useRef(false);
  useLayoutEffect(() => {
    if (!measOn) {
      openedMeas.current = false;
      return;
    }
    if (!meas.data || openedMeas.current || !display.rows.has(selected.positions)) return;
    openedMeas.current = true;
    const more = openForMeasurements(display, selected.positions);
    setOpenBy((o) => ({ ...o, positions: new Set([...(o.positions || levelSet(whole, 2)), ...more]) }));
  }, [measOn, meas.data, display, whole, selected.positions]);
  // Opening the Modelling tab opens the position picked, so its models show.
  const openedModels = useRef(false);
  useLayoutEffect(() => {
    if (!modelsOn) {
      openedModels.current = false;
      return;
    }
    if (!pmodels.links || openedModels.current || !display.rows.has(selected.positions)) return;
    openedModels.current = true;
    const more = openForModels(display, selected.positions);
    setOpenBy((o) => ({ ...o, positions: new Set([...(o.positions || levelSet(whole, 2)), ...more]) }));
  }, [modelsOn, pmodels.links, display, whole, selected.positions]);
  // Opening the Missions tab opens the position picked, so its missions show.
  const openedMissions = useRef(false);
  useLayoutEffect(() => {
    if (!missionsOn) {
      openedMissions.current = false;
      return;
    }
    if (!pmissions.links || openedMissions.current || !display.rows.has(selected.positions)) return;
    openedMissions.current = true;
    const more = openForMissions(display, selected.positions);
    setOpenBy((o) => ({ ...o, positions: new Set([...(o.positions || levelSet(whole, 2)), ...more]) }));
  }, [missionsOn, pmissions.links, display, whole, selected.positions]);
  // A link to a point, channel or consumable (?point=, ?channel=, ?consumable=):
  // its row picked and its details open beside the table, once it's in the tree.
  const viewParam = !measOn ? null : params.get("point") ? measKey(params.get("point"))
    : params.get("channel") ? measKey(`channel:${params.get("channel")}`)
      : params.get("consumable") ? measKey(`consumable:${params.get("consumable")}`) : null;
  const viewShown = useRef(null);
  useEffect(() => {
    if (!viewParam || viewShown.current === viewParam || !display.rows.has(viewParam)) return;
    viewShown.current = viewParam;
    reveal(viewParam);
    setPanel(true);
  }, [viewParam, display]); // eslint-disable-line react-hooks/exhaustive-deps

  const openAfter = useRef(null);
  useEffect(() => {
    const key = openAfter.current;
    if (!key || !rcm || !display.rows.has(key)) return;
    openAfter.current = null;
    const more = openFor(display, key);
    setOpenBy((o) => ({ ...o, positions: new Set([...(o.positions || levelSet(whole, 2)), ...more]) }));
  }, [rcm, display, whole]);

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
    const toTable = t === "rcm" || t === "fmea" || t === "measurements" || t === "models" || t === "missions";
    if (!toTable) {
      // Back to Summary: the rows below positions go; the selection is the position they were on.
      setRcmFocus(null);
      setPanel(false);
    }
    // Each tab's own chips go with it (the FME(C)A's and the RCM's are about
    // different columns); between the two tables the row picked stays (the
    // same keys), a row the other table hasn't falling back to its position.
    if (t !== "rcm") setChips((c) => c.filter((x) => !["undecided", "hidden", "check"].includes(x)));
    if (t !== "fmea") setChips((c) => c.filter((x) => !FMEA_CHIP_IDS.includes(x)));
    if (t !== "fmea") setFsort(null);
    if (t !== "models") setChips((c) => c.filter((x) => x !== "stale"));
    if (toTable && tab !== "summary" && focusRow?.type === "pos") setPanel(false);
    let keep = null;
    if (toTable && mode !== "positions") {
      keep = carryOver(focusRow, "positions", { display: whole, positions: data?.positions });
      if (keep) setSelected((s) => ({ ...s, positions: keep }));
    }
    setQuery_((q) => {
      if (t === "summary") q.delete(tabKey);
      else q.set(tabKey, t);
      if (toTable) q.set("arrange", "positions");
      // The report open in the Failure reports tab goes with the tab.
      if (t !== "reports") q.delete("report");
      // And the packaging open in the LSA tab.
      if (t !== "lsa") q.delete("packaging");
      // And a task, its Add task or the trade rates open in the Maintenance tab.
      if (t !== "maintenance") for (const k of ["mtask", "addtask", "rates", "below"]) q.delete(k);
      // So does a point or channel open in full in the Measurements tab.
      if (t !== "measurements") for (const k of VIEW_PARAMS) q.delete(k);
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
      // In the RBD builder (the table area), F is the builder's own full screen.
      if (e.target?.closest?.(".rbd-shell")) return;
      e.preventDefault();
      toggleFull();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [phone, toggleFull]);

  // Remembered on this device, a moment after each change, and on the way out.
  const latest = useRef(null);
  latest.current = { mode, open: openBy, selected, width, widthSet, collapsed };
  // One tree on show (an asset opened on its own, an item's tree) keeps only the pane's own layout
  // (its width, folded or not): what's open and picked there isn't the whole Explorer's.
  const keepLayout = useCallback(() => {
    const now = latest.current;
    if (!root) return saveTreeState(workspace, now);
    if (rootProp) return undefined;
    return saveTreeState(workspace, { ...loadTreeState(workspace), width: now.width, widthSet: now.widthSet, collapsed: now.collapsed });
  }, [workspace, root, rootProp]);
  useEffect(() => {
    const t = setTimeout(keepLayout, 200);
    return () => clearTimeout(t);
  }, [keepLayout, mode, openBy, selected, width, widthSet, collapsed]);
  useEffect(() => {
    if (root && rootProp) return undefined;
    const flush = keepLayout;
    window.addEventListener("pagehide", flush);
    return () => {
      window.removeEventListener("pagehide", flush);
      flush();
    };
  }, [keepLayout, root, rootProp]);

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
    if (isRcmRow(r) || isMeasRow(r) || isModelRow(r) || isMissionRow(r)) {
      setRcmFocus(key);
      setSelected((s) => ({ ...s, [mode]: positionOf(r) }));
    } else {
      setRcmFocus(null);
      setSelected((s) => ({ ...s, [mode]: key }));
    }
    setScrollTo({ key, at: Date.now() });
  }, [display, filter, mode, defaultOpen]);

  // Something added in place in the details (a new row of one of its lists):
  // the way down to it opened in the tree, once the RCM is read again, the
  // pick staying where it is (the details keep adding to the same list).
  const openNew = useRef(null);
  const [newTick, setNewTick] = useState(0);
  useEffect(() => {
    const id = openNew.current;
    if (!id || !display.rows.has(id)) return;
    openNew.current = null;
    const up = ancestorsOf(display, id);
    if (filter) setFopen((s) => new Set([...(s || filterOpen(filter)), ...up]));
    else setOpenBy((o) => ({ ...o, [mode]: new Set([...(o[mode] || defaultOpen), ...up]) }));
  }, [display, filter, mode, defaultOpen, newTick]);

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
    // A reference row (a failure below that causes one above) goes to the real row.
    if (r?.type === "cause" && opts.go) return reveal(r.ref.cause_id);
    if (isRcmRow(r) || isMeasRow(r) || isModelRow(r) || isMissionRow(r)) {
      setRcmFocus(key);
      setSelected((s) => ({ ...s, [mode]: positionOf(r) }));
      if (opts.go) setPanel(true);
      return;
    }
    setRcmFocus(null);
    setSelected((s) => ({ ...s, [mode]: key }));
    // On the FME(C)A tab a position's own details (its criticality matrix) are beside the table.
    if ((fmeaOn || rcmOn) && r?.type === "pos" && opts.go) setPanel(true);
    if (phone && opts.go && !tableOn) navigate(location.pathname + location.search, { state: { treeDetail: key } });
  };

  // The fit or the prediction in the table area: which, and the position it's for (from the
  // address), opened and closed.
  // An operating plan opens the same way from the Measurements and Summary tabs (?plan=).
  const paneQuery = paneFromQuery(params);
  const paneAt = modelsOn || missionsOn ? paneQuery
    : (measOn || tab === "summary") && paneQuery?.kind === "plan" ? paneQuery : null;
  const paneRow = paneAt && whole.rows.has(paneAt.id) ? whole.rows.get(paneAt.id) : null;
  const panePosition = paneRow?.type === "pos"
    ? { id: paneRow.key, name: paneRow.ref.name || "(no name)", position_class: paneRow.ref.position_class || "" } : null;
  const paneKind = panePosition ? paneAt.kind : null;
  // An address for a position that isn't in the tree (deleted, or another tree): the table as usual.
  useEffect(() => {
    if (paneAt && data && !panePosition) setQuery_((q) => { for (const k of PANE_PARAMS) q.delete(k); });
  }, [paneAt?.id, data, !!panePosition]); // eslint-disable-line react-hooks/exhaustive-deps
  const openPane = (kind, position, { start = {}, link = null, query = null, rbd = null, built = null, from = null } = {}) => {
    paneDirty.current = false;
    setPaneSeed((s) => ({ kind, id: position.id, start, link, built, n: (s?.n || 0) + 1 }));
    setPanel(false);
    if (selPos !== position.id && display.rows.has(position.id)) reveal(position.id);
    setQuery_((q) => {
      setPaneQuery(q, kind, position.id, { rbd, from });
      query?.(q);
    });
    setTimeout(() => paneHeading.current?.focus({ preventScroll: true }), 0);
  };
  const openFit = (position, opts) => openPane("fit", position, opts);
  // Excel import and export beside the tree, on the Summary tab (the plain tree).
  const openSheet = (start, branch = null) => {
    if (tableOn) setTab("summary");
    setSheet((x) => ({ start, branch, n: (x?.n || 0) + 1 }));
    setTimeout(() => sheetHeading.current?.focus({ preventScroll: true }), 0);
  };
  const openPredict = (position, link = null) => openPane("predict", position, { link });
  // Redundancy inside… (Modelling and Missions): which positions inside back each other up.
  const openRedundancy = async (position) => {
    if (!(await leavePane())) return;
    openPane("redundancy", position);
  };
  // A covariate model with covariates fixed at the position (?bind=<source>:<ref>&on=<position>).
  const openBind = (position, binding, { link = null, name = "" } = {}) =>
    openPane("bind", position, { link, start: { name }, rbd: bindingParam(binding.source, binding.ref) });
  // Leaving the pane for other work: asks first only if something in it was changed.
  const leavePane = async () => {
    if (!panePosition || !paneDirty.current) return true;
    if (!(await confirm(TABLE_PANES[paneKind].discard))) return false;
    paneDirty.current = false;
    return true;
  };
  // × or Esc on an RBD: the builder keeps what it has until saved, so it asks first when changed.
  const closeRbd = async () => {
    if (await leavePane()) closePane();
  };
  // A position's RBD in the table area: the RBD builder itself (RbdPane). `built`: what Build from
  // what's inside… just made, shown over it.
  const openRbd = async (position, rbdId, { built = null } = {}) => {
    if (!rbdId || !(await leavePane())) return;
    openPane("rbd", position, { rbd: rbdId, built });
  };
  // The positions one level inside, each with the model its block will take (or none: a placeholder).
  const insideOf = (pid) => (whole.rows.get(pid)?.kids || []).map((k) => whole.rows.get(k))
    .filter((k) => k?.type === "pos").map((k) => {
      const used = (pmodels.links || []).find((l) => l.position_id === k.key && l.in_use);
      return { id: k.key, name: k.ref.name || "(no name)", model: used ? `${used.model?.name || used.name} (${inUseWords(used)})` : null };
    });
  // Build from what's inside… (and Rebuild, `link` its RBD row): the backend derives the diagram
  // from the positions inside (rbd_derive: placeholders flagged, never a made-up figure), saves it
  // and links it here; it then opens in the table area. A position has one built diagram: where
  // it has one already, Build opens that one (here when its rows are read, else by the backend,
  // which answers `existing`), so using the menu again never leaves a second. The Modelling and
  // Missions tabs both build through here.
  const building = useRef(false);
  const buildRbd = async (position, link = null) => {
    if (building.current) return;
    const had = link ? null : builtRbdLink(pmodels.links, position.id);
    if (had) return openRbd(position, had.model_id);
    const kidsNow = insideOf(position.id);
    if (!kidsNow.length) {
      say(`There are no positions inside ${position.name} to make blocks from.`, "error");
      return;
    }
    if (!(await leavePane())) return;
    building.current = true;
    say(`${link ? "Rebuilding" : "Building"} an RBD from what's inside ${position.name}…`);
    try {
      const made = await linkPositionModel(position.id, { build_rbd: true, ...(link ? { replace_link_id: link.id } : {}) });
      say(made.existing ? `Opened ${made.name}: ${position.name} already has an RBD built from what's inside.`
        : `${link ? "Rebuilt" : "Built"} ${made.name}.`);
      pmodels.load();
      if (missionsOn) pmissions.load();
      paneDirty.current = false;
      openPane("rbd", position, { rbd: made.model_id, built: { name: made.name, rebuilt: !!link, kids: kidsNow, notes: made.notes || [] } });
    } catch (e) {
      say(saveErrorText(e, { offline: navigator.onLine === false }), "error");
    } finally {
      building.current = false;
    }
  };
  // Rebuild from what's inside…: the diagram opens in the table area with the question over it
  // (RbdPane: what a rebuild does, Rebuild or Cancel), so nothing changes on the menu click alone.
  const askRebuild = async (position, link) => {
    if (!link || !(await leavePane())) return;
    openPane("rbd", position, { rbd: link.model_id, link, start: { rebuild: true } });
  };
  // Back to the table, the row picked as it was (focus on it); `focusRow`: false when another row is being picked.
  const closePane = ({ focusRow = true } = {}) => {
    paneDirty.current = false;
    paneSaving.current = false;
    setPaneSeed(null);
    setQuery_((q) => { for (const k of PANE_PARAMS) q.delete(k); });
    if (focusRow) setTimeout(() => document.getElementById(`tp-${focus}`)?.focus({ preventScroll: true }), 0);
  };
  // Picking another row with the pane open closes it, asking first only if something was changed.
  const pickRow = async (key, opts = {}) => {
    const r = display.rows.get(key);
    // On the whole register, an asset's own top row opens that asset on its own (?root=), where
    // nothing of another asset shows; Back returns to the whole register. Not on a tree-table's
    // tab (RCM, Measurements, Modelling, Missions): a row picked there is the table's row.
    if (!root && opts.go && !tableOn && opensAsset(data, r, mode)) {
      // On a phone its details open, as a row's do there.
      navigate(explorerPath(mode, { root: key, sel: key, tab: tab === "summary" ? null : tab }),
               phone ? { state: { treeDetail: key } } : undefined);
      return;
    }
    // The Missions tab: a click on a mission or phase row opens it, as a model row opens on the
    // Modelling tab (the same mission open already: left as it is, unsaved edits and all).
    if (missionsOn && opts.go && !phone && isMissionRow(r)) {
      pick(key, opts);
      const open = paneKind === "mission" && paneAt?.mission === missionParam(r.ref.rbd.id, r.ref.mission.id);
      if (!open) openMissionRow(r);
      return;
    }
    if (panePosition && key !== panePosition.id) {
      if (paneDirty.current && !(await confirm(TABLE_PANES[paneKind].discard))) return;
      closePane({ focusRow: false });
    }
    pick(key, opts);
  };

  // Adding from a row's menu, the heading or the details: the new row is
  // picked, the way down to it opened and brought into view once the RCM is
  // read again.
  const runAdd = (r) => {
    const kind = r.ref.add;
    ops.add(kind, {
      positionId: r.ref.position_id, functionId: r.ref.function_id, failureId: r.ref.functional_failure_id ?? null,
      standardId: r.ref.standard_id ?? null,
    })
      .then((id) => {
        if (!id) return;
        pending.current = id;
        setPanel(true);
        say(`Added the ${kind === "fn" ? "function" : kind === "std" ? "performance standard" : kind === "fail" ? "functional failure" : "failure mode"}.`);
      }, (e) => say(saveErrorText(e, { offline: navigator.onLine === false }), "error"));
  };
  // Inside a function: a functional failure (under no standard); inside a
  // standard's row: one that breaches it; inside the "No standard" row: one
  // under none; inside a functional failure: a failure mode.
  const addInside = (r) => runAdd({ ref: {
    add: r.type === "fn" || r.type === "std" || r.type === "nostd" ? "fail" : "mode", position_id: r.ref.position_id,
    function_id: r.type === "fn" ? r.ref.id : r.type === "std" || r.type === "nostd" ? r.ref.function_id : null,
    standard_id: r.type === "std" ? r.ref.standard_id : null,
    functional_failure_id: r.type === "fail" ? r.ref.id : null,
  } });
  // The confirm stays open (its button saying "Deleting…") until the server
  // has done it, so it's sent once; a refusal shows in the confirm.
  const remove = async (r) => {
    const level = LEVEL_OF[r.type].label.toLowerCase();
    // A standard comes off its function (its failures stay); the rest are deleted.
    const verb = r.type === "std" ? "Remove" : "Delete";
    const ok = await confirm({
      title: `${verb} this ${level}?`, body: ops.removeText(r), confirmLabel: `${verb} ${level}`,
      pendingLabel: `${verb === "Remove" ? "Removing" : "Deleting"}…`, failedWhat: `${verb.toLowerCase()} it`,
      run: () => ops.remove(r).then(() => true),
    });
    if (!ok) return;
    setRcmFocus(isRcmRow(display.rows.get(r.parent)) ? r.parent : null);
    say(`${verb === "Remove" ? "Removed" : "Deleted"} the ${level}.`);
  };
  // Delete on an RCM row (its menu, or the foot of its details): a function,
  // standard, failure or mode goes with everything under it, in a dialog that
  // counts it first, then a toast with Undo; the old single standard text is
  // cleared as before.
  const removeRow = (r) => (deletesWithCascade(r) ? setRowModal({ kind: "rcm-delete", row: r }) : remove(r));
  // Linking functional failures (from a row's menu or the panel): the picker,
  // and taking a link off, with one confirm when it would leave the higher
  // failure with nothing explaining it.
  const openLink = (r, direction) => setLinking({ row: r, direction });
  const unlinkPair = async (effectId, causeId) => {
    if (unlinkEmptiesFailure(whole, effectId, causeId)) {
      const e = whole.rows.get(effectId);
      const ok = await confirm({
        title: "Unlink this cause?",
        body: `This was the only explanation of “${(e.ref.text || "").slice(0, 80)}”. It will have no cause or failure mode, so its position is no longer analysed.`,
        confirmLabel: "Unlink anyway", pendingLabel: "Unlinking…", failedWhat: "unlink it",
        run: () => ops.unlink(effectId, causeId).then(() => true),
      });
      if (ok) say("Unlinked.");
      return;
    }
    ops.unlink(effectId, causeId).then(() => say("Unlinked."), (e) => say(saveErrorText(e, { what: "unlink it", offline: navigator.onLine === false }), "error"));
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
  // headings or the whole tree's one top row, the whole tree shows with it picked.
  const crumbGo = (key, select) => {
    const act = crumbAction(pinKey ? display : null, whole, mode, key);
    if (act === "select") return select(key);
    if (act === "pin") return pinTo(key, { select: true, state: phone && !tableOn ? { treeDetail: key } : undefined });
    return unpin({ select: key });
  };
  const above = pinKey ? (key) => !display.rows.has(key) : null;
  const pinItem = (r) => (canPin(r, mode)
    ? [r.key === pinKey ? { id: "unpin", label: "Show whole tree" } : { id: "pin", label: "Pin this branch" }] : []);
  // On the RCM tab a row can go five levels deep (down to the tasks): its menu offers them.
  const isolateItem = (r) => isolateItems(display.rows.get(r.key) || r, {
    can: canIsolate(display.rows.get(r.key) || r, mode, canPin), levels: tableOn && !fmeaOn ? levelsBelow(display, r.key) : 0,
  });
  // Isolate: the rest of the tree closed, this row opened `depth` levels
  // below it, picked and brought into view; said to screen readers.
  // Focus on incomplete rows: the way to what's still to finish under this row
  // (functions with no functional failure, failures with no failure mode,
  // modes with no decision) opened, the rest closed; the first one picked.
  const isolateIncomplete = (r) => {
    const row = display.rows.get(r.key);
    if (!row) return;
    const { open: next, rows: found } = isolateIncompleteOpen(display, open, r.key);
    const name = row.ref.name || row.ref.text || "this row";
    if (!found.length) {
      announce(`Nothing incomplete under ${name}.`);
      say(`Nothing incomplete under ${name}: every function has a functional failure and every failure mode a decision.`);
      return;
    }
    setLevelBy((l) => ({ ...l, [mode]: null }));
    setOpenSet(next);
    const first = found[0];
    setRcmFocus(first.key);
    setSelected((x) => ({ ...x, [mode]: positionOf(first) }));
    setScrollTo({ key: first.key, at: Date.now() });
    announce(`Collapsed the rest of the tree: ${found.length} incomplete row${found.length === 1 ? "" : "s"} under ${name}.`);
  };
  const isolateAt = (r, depth) => {
    const row = display.rows.get(r.key);
    if (!row) return;
    const next = isolateOpen(display, open, r.key, depth);
    setLevelBy((l) => ({ ...l, [mode]: null }));
    setOpenSet(next);
    if (isRcmRow(row)) {
      setRcmFocus(row.key);
      setSelected((x) => ({ ...x, [mode]: positionOf(row) }));
    } else {
      setRcmFocus(null);
      setSelected((x) => ({ ...x, [mode]: row.key }));
    }
    setScrollTo({ key: row.key, at: Date.now() });
    const name = row.ref.name || row.ref.text || "(no name)";
    announce(row.kids.length ? `Collapsed the rest of the tree; ${name} opened ${depthWords(depth)}.` : `Collapsed the rest of the tree around ${name}.`);
  };

  // A row's menu (TreePane's rowMenu): what it offers, and doing it. On the
  // RCM tab, adding inside the row and its other actions; on the Summary tab,
  // changing the tree (new inside, rename, move, retire: treeRowMenu.js); and
  // on any row that can be pinned, Pin this branch.
  // ---- moving things in the RCM tree (drag and drop, Move to…, Move up / down) ----
  // Every move is one batch, checked by the server first and all or nothing;
  // the toast says what moved and offers Undo (also Ctrl+Z / Cmd+Z while it
  // shows), which sends the batch's undo back as one batch.
  const offline = () => navigator.onLine === false;
  const checkMove = useCallback((operations) => ops.arrange(operations, { dryRun: true }).then(
    (a) => ({ ok: true, notes: answerNotes(a) }),
    // Not a refusal (no connection, a server error): the drop goes ahead and the server checks it then.
    // A move that needs a choice goes ahead too: the drop asks what its tasks count there.
    (e) => (e.status === 409 && e.data?.needs_choice ? { ok: true, notes: ["It will ask what its tasks count there."] }
      : e.status === 422 ? { ok: false, reason: refusalText(e) } : { ok: true, notes: [] }),
  ), [ops]);
  // What a move's tasks by use should count at the new position, asked in a
  // dialog: resolves with the measurement choices, or rejects (cancelled) when
  // the user leaves it where it is.
  const askMeasurement = (need) => new Promise((resolve, reject) => {
    setMeasuring({
      need,
      choose: (measurement) => { setMeasuring(null); resolve(measurement); },
      cancel: () => { setMeasuring(null); reject(Object.assign(new Error("Not moved: nothing was changed."), { cancelled: true })); },
    });
  });
  const applyMove = async (src, plan, key) => {
    // A task's row dropped on another failure mode (or linked from its menu): a copy, never a move.
    // It joins the target's decision (the decide route) or is linked to it (the link route).
    if (plan.copy) {
      const target = whole.rows.get(plan.copy.target);
      if (!target) throw new Error("That failure mode isn't on the tree any more.");
      try {
        if (plan.copy.decision) await ops.decide(target, { consequence: target.ref.consequence || null, decision: plan.copy.decision });
        else await ops.linkTask(target, src.task.id);
      } catch (e) {
        throw new Error(e.status === 422 ? refusalText(e) : saveErrorText(e, { offline: offline() }));
      }
      pending.current = shownAfter(src, plan.copy.target);
      setToast({ text: plan.done, undo: null, at: Date.now() });
      announce(plan.done);
      return null;
    }
    let answer;
    try {
      answer = await ops.arrange(plan.ops);
    } catch (e) {
      if (e.status === 409 && e.data?.needs_choice) {
        const need = e.data.needs_choice;
        announce(`${e.message} Choose what it should count.`);
        const measurement = await askMeasurement(need);
        return applyMove(src, { ...plan, ops: withMeasurement(plan.ops, need.op_index ?? 0, measurement) }, key);
      }
      throw new Error(e.status === 422 ? refusalText(e) : saveErrorText(e, { offline: offline() }));
    }
    const notes = answerNotes(answer);
    const text = [plan.done, ...notes].join(" ");
    const show = shownAfter(src, key);
    pending.current = show;
    setPicked(new Set());
    setToast({ text, undo: undoBatch(answer), extra: plan.extraUndo || [], show, at: Date.now() });
    announce(`${text} Press Control Z to undo.`);
    return answer;
  };
  const dropMove = (src, plan, key) => {
    // A task's row dropped where it can't be linked: the drop cue said so; nothing more.
    if (plan.refuse && plan.quiet) {
      announce(`Not linked: ${plan.refuse}`);
      return;
    }
    if (plan.refuse) {
      say(`Not moved: ${plan.refuse}`, "error");
      announce(`Not moved: ${plan.refuse}`);
      return;
    }
    applyMove(src, plan, key).catch((e) => {
      if (e.cancelled) {
        say(e.message);
        announce(e.message);
        return;
      }
      say(`Not moved: ${e.message}`, "error");
      announce(`Not moved: ${e.message}`);
    });
  };
  const undoDelete = async (t) => {
    setToast({ ...t, busy: true });
    try {
      // An RCM row's delete (restoreRcm), or a position's or location's.
      const rcmRow = !!t.restore.rcm;
      const answer = rcmRow ? await restoreRcm(t.restore.id) : await restoreTree(t.restore.kind, t.restore.id);
      if (rcmRow) setRcmFocus(t.restore.focus ?? null);
      else pending.current = t.restore.id;
      if (rcmOn) await loadRcm();
      load();
      const text = rcmRow ? rcmUndoneText({ ...answer, name: t.restore.name }) : undoneText({ ...answer, name: t.restore.name });
      setToast({ text, undo: null, at: Date.now() });
      announce(text);
    } catch (e) {
      const why = e.status === 422 ? refusalText(e) : saveErrorText(e, { offline: offline() });
      setToast({ text: `Couldn't undo it: ${why}`, undo: null, tone: "error", at: Date.now() });
      announce(`Couldn't undo it: ${why}`);
    }
  };
  const undoMove = async () => {
    const t = toast;
    if (t?.restore && !t.busy) return undoDelete(t);
    if (!t?.undo?.length || t.busy) return;
    setToast({ ...t, busy: true });
    try {
      try {
        await ops.arrange([...t.undo, ...t.extra]);
      } catch (e) {
        // The places it came from have changed meanwhile: put it back, anywhere among them.
        if (e.status !== 422 || !t.extra.length) throw e;
        await ops.arrange(t.undo);
      }
      pending.current = t.show;
      setToast({ text: "Undone: everything is back where it was.", undo: null, at: Date.now() });
      announce("Undone.");
    } catch (e) {
      const why = e.status === 422 ? refusalText(e) : saveErrorText(e, { offline: offline() });
      setToast({ text: `Couldn't undo it: ${why}`, undo: null, tone: "error", at: Date.now() });
      announce(`Couldn't undo it: ${why}`);
    }
  };
  useEffect(() => {
    if (!toast?.undo?.length && !toast?.restore) return undefined;
    const onKey = (e) => {
      if (!(e.ctrlKey || e.metaKey) || e.shiftKey || e.altKey || e.key.toLowerCase() !== "z") return;
      if (e.target.closest?.("input, textarea, select, [contenteditable='true']") || hasOpenLayer(document)) return;
      e.preventDefault();
      undoMove();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }); // eslint-disable-line react-hooks/exhaustive-deps
  // Shift / Ctrl / Cmd-click on failure modes: picked, to drag or move together
  // (Ctrl / Cmd adds or takes one; Shift picks the run from the last one
  // picked). A plain click clears them (null).
  const pickMany = (key, e) => {
    if (key == null) return setPicked(new Set());
    const r = whole.rows.get(key);
    if (r?.type !== "mode") return null;
    setRcmFocus(key);
    setSelected((x) => ({ ...x, [mode]: positionOf(r) }));
    setPicked((was) => {
      const next = new Set(was);
      const anchorKey = [...was].pop() || (focusRow?.type === "mode" ? focusRow.key : null);
      if (e.shiftKey && anchorKey && index.has(anchorKey) && index.has(key)) {
        const [a, b] = [index.get(anchorKey), index.get(key)].sort((x, y) => x - y);
        for (let i = a; i <= b; i += 1) if (whole.rows.get(list[i].key)?.type === "mode") next.add(list[i].key);
      } else {
        if (!was.size && anchorKey && anchorKey !== key) next.add(anchorKey);
        if (next.has(key)) next.delete(key);
        else next.add(key);
      }
      announce(`${next.size} failure mode${next.size === 1 ? "" : "s"} picked.`);
      return next;
    });
    return null;
  };
  // Drag and drop is the RCM tab's (its tree has the levels a drop lands on).
  const { drag, begin: beginDrag } = useRcmDrag({
    whole, picked, enabled: rcmOn && !fmeaOn && !phone && !!rcm, check: checkMove, drop: dropMove, say: announce,
  });
  // A row menu's Move up / Move down: the drop before the one above, or after the one below.
  const stepMove = (r, by) => {
    const to = stepTarget(whole, r.key, by);
    const src = dragSource(whole, r.key);
    if (!to || !src) return;
    dropMove(src, planDrop(whole, src, to.key, to.zone), to.key);
  };

  const viewOnly = viewOnlyReason(activeTeam);
  const designScope = isDesignScope(data, root);
  const kids = useMemo(() => liveKids(data?.positions), [data]);
  // A measurement row's ⋯ (the Measurements tab).
  // A measurement row's details spread across the table, the tree kept (as an
  // RCM row's double-click, its Open and Enter do): a double-click on its name,
  // Open in its ⋯, or Enter on it. Esc (or Back to table) puts them beside it again.
  const openMeas = (key) => {
    pick(key, { go: true });
    if (!phone) setExpanded(true);
    setTimeout(() => detailsHeading.current?.focus(), 0);
  };
  // Adding under a position (its row's menu, or the heading's "…": explorerMeasurements.js measAddActions).
  const measAdd = (r, id) => {
    const target = { kind: "position", id: r.key };
    if (id === "add-point") setMeasModal({ kind: "add", target, preset: "condition" });
    else if (id === "add-setting") setMeasModal({ kind: "add", target, preset: "setting" });
    else if (id === "add-consumable") setMeasModal({ kind: "consumable", position: { id: r.key, name: r.ref.name || "(no name)" } });
    else if (id === "add-channel") setMeasModal({ kind: "channel", target });
  };
  const measAction = (r, id) => {
    if (id.startsWith("add-")) return measAdd(r, id);
    const row = r.ref.row;
    if (id === "page" || id === "bands") openMeas(r.key);
    else if (id === "record") setMeasModal({ kind: "read", item: row.item });
    else if (id === "use") setMeasModal({ kind: "use", item: row.item });
    else if (id === "limits") setMeasModal({ kind: "limits", item: row.item });
    else if (id === "move") setMeasModal({ kind: "move", item: row.item });
    else if (id === "retire") retireMeasurement(confirm, row, (text) => { say(text); meas.load(); });
  };
  // The Modelling tab's attach groups for a position (explorerModels.attachGroups), and what each item opens.
  const predictionOf = (pid) => (pmodels.links || []).find((l) => l.position_id === pid && l.role === "prediction") || null;
  const modelGroups = (pid, positionClass) => attachGroups({ positionClass: positionClass || "", hasPrediction: !!predictionOf(pid),
    hasLifeModel: !!lifeModelOf(pmodels.links, pid), builtRbd: !!builtRbdLink(pmodels.links, pid), viewOnly,
    hasInside: insideOf(pid).length > 0 });
  const attachAt = (pid, id) => {
    const rr = whole.rows.get(pid);
    const position = { id: pid, name: rr?.ref.name || "(no name)", position_class: rr?.ref.position_class || "" };
    if (id === "model-attach-fit-life") return openFit(position);
    if (id === "model-attach-predict") return openPredict(position);
    if (id === "model-refresh-predict") return openPredict(position, predictionOf(pid));
    if (id === "model-attach-rbd-build") return buildRbd(position);
    if (id === "model-attach-redundancy") return openRedundancy(position);
    if (id === "model-attach-rbd-new") {
      return setModelModal({ kind: "rbd-new", position, hasInside: insideOf(pid).length > 0, hasModel: !!lifeModelOf(pmodels.links, pid) });
    }
    if (id === "model-attach-rbd-open") return openRbd(position, builtRbdLink(pmodels.links, pid)?.model_id);
    if (id === "model-attach-rbd-rebuild") return askRebuild(position, builtRbdLink(pmodels.links, pid));
    // Add to library…: the position's life model in use (else its first) snapshotted into a data library.
    if (id === "model-attach-to-library") return setModelModal({ kind: "to-library", position, link: lifeModelOf(pmodels.links, pid) });
    return setModelModal({ kind: id.slice(13), position });
  };
  // A model row's details spread across the table (a double-click, Open, Enter), as a measurement row's.
  // An RBD row opens the builder in the table area instead (opensInPane).
  const openModel = (key) => {
    const link = whole.rows.get(key)?.ref?.link;
    if (opensInPane(link)) {
      const pr = whole.rows.get(link.position_id);
      return openRbd({ id: link.position_id, name: pr?.ref.name || "(no name)" }, link.model_id);
    }
    pick(key, { go: true });
    if (!phone) setExpanded(true);
    setTimeout(() => detailsHeading.current?.focus(), 0);
  };
  const modelAction = (r, id) => {
    const link = r.ref.link;
    const position = { id: r.ref.position_id, name: whole.rows.get(r.ref.position_id)?.ref.name || "(no name)" };
    if (id === "model-open") openModel(r.key);
    else if (id === "model-rbd-pane") openRbd(position, link.model_id);
    else if (id === "model-page" && link.model?.path) leavePane().then((ok) => ok && navigate(link.model.path));
    else if (id === "model-refit") {
      const scope = link.source?.scope;
      openFit({ ...position, position_class: whole.rows.get(r.ref.position_id)?.ref.position_class || "" },
        { link, start: { data: scope === "class" ? "class" : "position" } });
    }
    else if (id === "model-predict") openPredict(position, link);
    else if (id === "model-bind") openBind(position, bindingOf(link), { link, name: link.model?.name || link.name });
    else if (id === "model-to-library") setModelModal({ kind: "to-library", position, link });
    else if (id === "model-rebuild") askRebuild(position, link);
    else if (id === "model-use") {
      linkPositionModel(position.id, { use_link_id: link.id }).then(() => {
        say(`${link.model?.name || link.name} is now ${position.name}'s model in use.`);
        pmodels.load();
      }, (e) => say(e.message, "error"));
    }
    else if (id === "model-bayes") {
      const withClass = { ...position, position_class: whole.rows.get(r.ref.position_id)?.ref.position_class || "" };
      // The fit pane with this row's model as the prior: a Bayesian row takes its new failures (its own prior kept).
      openFit(withClass, { ...priorFrom(link), from: link.id });
    }
    else if (id === "model-params-edit") setModelModal({ kind: "params", position, link });
    else if (id === "model-replace") setModelModal({ kind: "assign", position, link });
    else if (id === "model-unlink") unlinkModel(confirm, link, (text) => { say(text); setPanel(false); setRcmFocus(null); pmodels.load(); });
  };
  // The Missions tab: a mission opens in the table area (?mission=<RBD id>:<mission id>&on=<position>).
  // `phase`: the phase to open it on (its index: a phase row's), its name field focused.
  const openMission = async (positionId, rbdId, missionId, phase = null) => {
    if (!(await leavePane())) return;
    const pr = whole.rows.get(positionId);
    openPane("mission", { id: positionId, name: pr?.ref.name || "(no name)" }, { rbd: missionParam(rbdId, missionId), start: phase == null ? {} : { phase } });
  };
  // A mission or phase row opened (a double-click, Enter, Open…): a phase opens the mission on it.
  const openMissionRow = (r) => openMission(r.ref.position_id, r.ref.rbd.id, r.ref.mission.id, isPhaseRow(r) ? r.ref.phase.index : null);
  // A phase added, moved or deleted from the tree: the saved mission read, changed with the pane's
  // phase helpers (changedPhases) and saved through the mission's update route. `change`: editable
  // rows in, rows out. Resolves with the phases saved, or null (nothing saved; said why).
  const changeMissionPhases = async (r, change, done) => {
    if (!(await leavePane())) return null;
    const { rbd, mission } = r.ref;
    try {
      const detail = await getMission(rbd.id, mission.id);
      if (detail.rbd?.read_only) {
        say("This RBD is view only here: its missions can't be changed.", "error");
        return null;
      }
      const { phases, errors } = changedPhases(detail, change);
      if (errors.length) {
        say(`Not saved: ${errors[0]} Open the mission to put it right.`, "error");
        return null;
      }
      await updateMission(rbd.id, mission.id, { phases, expected_updated_at: detail.rbd?.updated_at });
      say(done(phases));
      pmissions.load();
      return phases;
    } catch (e) {
      say(saveErrorText(e, { offline: navigator.onLine === false }), "error");
      return null;
    }
  };
  const addPhase = async (r) => {
    const phases = await changeMissionPhases(r, withNewPhase, (ps) => `Added ${ps[ps.length - 1].name} to ${r.ref.mission.name}: give it its name and duration.`);
    if (!phases) return;
    pending.current = phaseKey(r.ref.rbd.id, r.ref.mission.id, phases.length - 1);
    openMission(r.ref.position_id, r.ref.rbd.id, r.ref.mission.id, phases.length - 1);
  };
  // The mission open in the pane changed from the tree: the pane opened on it again, fresh.
  const reopenIfShown = (r, phase) => {
    if (paneKind === "mission" && paneAt?.mission === missionParam(r.ref.rbd.id, r.ref.mission.id)) {
      openMission(r.ref.position_id, r.ref.rbd.id, r.ref.mission.id, phase);
    }
  };
  const stepPhase = async (r, by) => {
    const { index } = r.ref.phase;
    const phases = await changeMissionPhases(r, (rows) => movePhase(rows, index, by), () => `Moved ${r.ref.name} ${by < 0 ? "earlier" : "later"}.`);
    if (!phases) return;
    pending.current = phaseKey(r.ref.rbd.id, r.ref.mission.id, index + by);
    reopenIfShown(r, index + by);
  };
  const removePhase = async (r) => {
    const ok = await confirm({
      title: `Delete ${r.ref.name}?`, body: `The phase goes from ${r.ref.mission.name}; its other phases and the RBD stay as they are.`,
      confirmLabel: "Delete the phase", cancelLabel: "Keep it", destructive: true,
    });
    if (!ok) return;
    const { index } = r.ref.phase;
    const phases = await changeMissionPhases(r, (rows) => withoutPhase(rows, index), () => `Deleted ${r.ref.name}.`);
    if (!phases) return;
    pending.current = phases.length ? phaseKey(r.ref.rbd.id, r.ref.mission.id, Math.min(index, phases.length - 1)) : missionKey(r.ref.rbd.id, r.ref.mission.id);
    reopenIfShown(r, null);
  };
  const removeMission = async (positionId, rbdId, mission, ownRbd = false) => {
    const ok = await confirm({
      title: `Delete ${mission.name}?`,
      body: ownRbd ? "The mission, its phases and its own RBD go. Other missions and the position's RBDs stay as they are."
        : "The mission and its phases go; the RBD stays as it is.",
      confirmLabel: "Delete the mission", cancelLabel: "Keep it", destructive: true,
    });
    if (!ok) return false;
    try {
      await deleteMission(rbdId, mission.id);
      say(`Deleted ${mission.name}.`);
      pmissions.load();
      return true;
    } catch (e) {
      say(saveErrorText(e, { offline: navigator.onLine === false }), "error");
      return false;
    }
  };
  // Add a mission: its name asked first, in the table pane (?mission=new); then one RBD per mission,
  // built from what's inside the position (placeholders flagged) and named after the mission.
  const addMission = async (positionId) => {
    if (!(await leavePane())) return;
    const pr = whole.rows.get(positionId);
    openPane("mission", { id: positionId, name: pr?.ref.name || "(no name)" }, { rbd: NEW_MISSION });
  };
  const createMission = async (positionId, positionName, name) => {
    try {
      const made = await createPositionMission(positionId, { name });
      const ph = made.placeholders?.length ? ` ${made.placeholders.length} block${made.placeholders.length === 1 ? " is a placeholder" : "s are placeholders"}: give ${made.placeholders.length === 1 ? "it a model" : "them models"} in its RBD.` : "";
      const from = made.built_from === "model" ? `one block, ${positionName}'s own model in use`
        : made.built_from === "copy" ? `a copy of ${positionName}'s RBD, wired as it is there` : `what's inside ${positionName}`;
      const series = made.series_warning ? " Its blocks are in series: check the wiring in its RBD." : "";
      say(`Added ${made.mission.name} with an RBD of its own, built from ${from}.${ph}${series} Now give it its phases.`);
      pmissions.load();
      pending.current = missionKey(made.rbd.id, made.mission.id);
      openMission(positionId, made.rbd.id, made.mission.id);
    } catch (e) {
      // Shown in the pane, beside the name typed (nothing was made).
      throw new Error(saveErrorText(e, { offline: navigator.onLine === false }));
    }
  };
  const missionAction = (r, id) => {
    const pid = r.type === "pos" ? r.key : r.ref.position_id;
    const pr = whole.rows.get(pid);
    const position = { id: pid, name: pr?.ref.name || "(no name)", position_class: pr?.ref.position_class || "" };
    if (id === "mission-open" || id === "mission-phase-open") return openMissionRow(r);
    if (id === "mission-phase-add") return addPhase(r);
    if (id === "mission-phase-earlier" || id === "mission-phase-later") return stepPhase(r, id === "mission-phase-earlier" ? -1 : 1);
    if (id === "mission-phase-delete") return removePhase(r);
    if (id === "mission-rbd") return openRbd(position, r.ref.rbd.id);
    if (id === "mission-delete") return removeMission(pid, r.ref.rbd.id, r.ref.mission, !!r.ref.rbd.mission_rbd);
    if (id === "mission-new") return addMission(pid);
    if (id.startsWith("mission-open-rbd:")) return openRbd(position, id.slice(17));
    if (id === "mission-build-rbd") return buildRbd(position);
    if (id === "mission-redundancy") return openRedundancy(position);
    return undefined;
  };
  // The LSA tab's Package the tasks here…: the row picked, and its drafts open in the panel beside
  // the tree (?packaging=<the row>, read by LsaPanel; a task or a package open there closes). On a
  // phone the panel is its own screen, so Back returns to the tree.
  const packageAt = (r) => {
    setRcmFocus(null);
    setSelected((s) => ({ ...s, [mode]: r.key }));
    const q = new URLSearchParams(params);
    q.set("sel", r.key);
    q.set("packaging", r.key);
    q.delete("task");
    q.delete("package");
    navigate(`${location.pathname}?${q}${location.hash}`, phone ? { state: { treeDetail: r.key } } : { replace: true, state: location.state });
  };
  // The Maintenance tab's Add task…: the row picked, and the form opens in the panel beside the tree
  // (?addtask=<the row>, read by LsaPanel's maintenance variant). On a phone the panel is its own screen.
  const addTaskAt = (r) => {
    setRcmFocus(null);
    setSelected((s) => ({ ...s, [mode]: r.key }));
    const q = new URLSearchParams(params);
    q.set("sel", r.key);
    q.set("addtask", r.key);
    q.delete("mtask");
    q.delete("rates");
    navigate(`${location.pathname}?${q}${location.hash}`, phone ? { state: { treeDetail: r.key } } : { replace: true, state: location.state });
  };
  const rowMenu = {
    // The moves a drag does: on a phone, or from the keyboard (no dragging there).
    actions: (r, { keyboard = false } = {}) => {
      // The plain tree's tabs: the Summary menu; on a tab with something of its own for the row (Failure
      // reports' add, the LSA tab's Package the tasks here…), that first; on one with nothing for it, the
      // changes to the tree go after Focus and Pin (treeRowMenu.js tabMenu). A row the tab doesn't have
      // (an item on the LSA tab) shows Summary, so it gets the Summary menu.
      if (!tableOn) {
        const at = shownTab(tab, r);
        return menuOnTab(at, designActions(summaryActions(r, { mode, viewOnly, kidsOf: (k) => kids.get(k) || 0 }), designScope, { row: r, viewOnly }), {
          lead: at === "lsa" ? lsaLead(r, { design: isDesignRow(r), viewOnly })
            : at === "maintenance" ? maintenanceLead(r, { viewOnly }) : [],
          pin: [...isolateItem(r), ...pinItem(r)],
        });
      }
      // The Measurements tab: a measurement row's own (Open, Record…, Edit…, Move…, Retire…);
      // a position's: its adds (a measuring point, a setting, a consumable, a sensor channel), a
      // line, then the Summary menu, with isolating and pinning.
      if (modelsOn && isModelRow(r)) return modelRowActions(r, { viewOnly });
      // The Missions tab: a mission's own (Add a phase, Open, Show the RBD, Delete…), a phase's (Open…,
      // Move earlier / later, Delete…); a position's: add a mission to its RBD (or build one), then
      // Rename…, Focus ›, Pin this branch.
      if (missionsOn && isMissionRow(r)) return missionRowActions(r, { viewOnly });
      if (missionsOn && r.type === "pos") {
        const own = summaryActions(r, { mode, viewOnly }).filter((it) => MODEL_POSITION_ITEMS.includes(it.id));
        return [...positionMissionActions(display.rows.get(r.key) || r, { viewOnly }), { separator: true }, ...own, ...isolateItem(r), ...pinItem(r)];
      }
      // A position's own on the Modelling tab: attach a model (the heading's "…" isn't there on a phone).
      if (modelsOn && r.type === "pos") {
        // Two levels (Derryn, 9 Nov 2026): Life model ›, RBD ›, Prediction ›, a line, then only the
        // position items that make sense here (Rename…, Focus ›, Pin this branch).
        const own = summaryActions(r, { mode, viewOnly }).filter((it) => MODEL_POSITION_ITEMS.includes(it.id));
        return [...modelGroups(r.key, r.ref.position_class), { separator: true }, ...own, ...isolateItem(r), ...pinItem(r)];
      }
      if (measOn || modelsOn) {
        if (isMeasRow(r)) return measRowActions(r);
        if (measOn) {
          // How it runs (its operating plan), in the table area: what its hour counters will be forecast from.
          const plan = r.type === "pos" && !designScope ? [{ id: "plan-open", label: "Operating plan…" }] : [];
          return withPin(addsFirst([...measAddActions(r, { viewOnly }), ...plan], designActions(summaryActions(r, { mode, viewOnly, kidsOf: (k) => kids.get(k) || 0 }), designScope, { row: r, viewOnly })),
            [...isolateItem(r), ...pinItem(r)]);
        }
        return withPin(designActions(summaryActions(r, { mode, viewOnly, kidsOf: (k) => kids.get(k) || 0 }), designScope, { row: r, viewOnly }), [...isolateItem(r), ...pinItem(r)]);
      }
      if (!rcm) return [...isolateItem(r), ...pinItem(r)];
      // The FME(C)A tab: its own rows' actions (no moving: that's the RCM tab's).
      // Delete… stays last (pin and isolate go before it).
      if (fmeaOn) return withPin(fmeaRowActions(r, { canRename: !phone, viewOnly }), [...isolateItem(r), ...pinItem(r)]);
      const moves = phone || keyboard;
      // Move to… always (the picker: no dragging needed, and a long way); Move up / down only where there's no dragging.
      const own = withPin(rowActions(r, { canRename: !phone, moves, viewOnly }), moveItems(whole, whole.rows.get(r.key) || r, { picked, steps: moves }));
      return withPin(own, [...isolateItem(r), ...isolateIncompleteItem(display.rows.get(r.key) || r, { can: canIsolate(display.rows.get(r.key) || r, mode, canPin) }), ...pinItem(r)]);
    },
    onAction: (r, id) => {
      if (id.startsWith("meas-")) return measAction(r, id.slice(5));
      if (id.startsWith("model-attach-") || id === "model-refresh-predict") return attachAt(r.key, id);
      if (id.startsWith("model-")) return modelAction(r, id);
      if (id.startsWith("mission-")) return missionAction(r, id);
      if (id === "lsa-package") return packageAt(r);
      if (id === "plan-open") return leavePane().then((ok) => ok && openPane("plan", { id: r.key, name: r.ref.name || "(no name)" }));
      if (id === "maint-add-task") return addTaskAt(r);
      if (id === "pos-here") {
        setNewParent(TOP);
        setNewAt(r.key);
        setModal("position");
      } else if (id === "tree-new") {
        setNewParent(r.key);
        setModal(r.type === "loc" ? "location" : "position");
      } else if (id === "tree-rename" || id === "tree-move" || id === "tree-delete") setRowModal({ kind: id.slice(5), row: r });
      else if (id === "report-new") setReportFor({ id: r.key, name: r.ref.name, select: r.key });
      else if (id === "event-log") setEventFor({ id: r.key, name: r.ref.name });
      else if (id === "tree-export") openSheet("export", { id: r.key, name: r.ref.name || "(no name)" });
      else if (id === "build-item") buildFrom(r.key);
      else if (id === "make-own") makeOwn(r);
      else if (id === "pin") pinTo(r.key, { select: true });
      else if (id.startsWith("isolate:")) isolateAt(r, id === "isolate:all" ? "all" : Number(id.slice(8)));
      else if (id === "isolate-incomplete") isolateIncomplete(r);
      else if (id === "unpin") unpin();
      else if (id === "add-fn") runAdd({ ref: { add: "fn", position_id: r.key } });
      // Adding inside a row: its details open on that list's add row (a new row typed in place).
      else if (id === "add-std") openItem(r.key, { add: "std" });
      // A "No functional failure yet" row: the functional failure goes on its function.
      else if (id === "add-fail" && r.type === "nofail") openItem(r.ref.function_id, { add: "inside" });
      else if (id === "assign-fail") setAssigning(r);
      else if (id === "add-fail" || id === "add-mode") openItem(r.key, { add: "inside" });
      else if (id === "score") openItem(r.key);
      else if (id === "print") openPrint(r.key);
      else if (id === "export-excel") exportExcel(r);
      else if (id === "move-to") setMoving({ src: dragSource(whole, r.key, { picked }) });
      // A task's row: the picker, to link it to another failure mode as well (the keyboard's drag).
      else if (id === "link-task") setMoving({ src: dragSource(whole, r.key) });
      else if (id === "move-task") setMoving({ taskFrom: r.key });
      else if (id === "step-up" || id === "step-down") stepMove(r, id === "step-up" ? -1 : 1);
      else if (id === "move-up" || id === "move-down") {
        setRcmFocus(r.key);
        ops.moveStandard(r, id === "move-up" ? -1 : 1).then((did) => did && say("Moved."), (e) => say(saveErrorText(e, { offline: navigator.onLine === false }), "error"));
      } else if (id === "rename" && r.type === "fn") {
        // A function's description: in a dialog with its counter.
        setRcmFocus(r.key);
        ops.editFunction(r).then((ok) => ok && say("Saved."));
      } else if (id === "rename") { setRcmFocus(r.key); setEditing({ key: r.key, col: "name" }); }
      else if (id === "decide") setDeciding(r);
      else if (id === "open") openItem(r.key);
      // No decision yet: the task is its decision (Decide…); else another task joins it.
      else if (id === "add-task") { if (r.ref.decision) openItem(r.key, { add: "task" }); else setDeciding(r); }
      // A task's row: off this failure mode (a shared task stays with the others), or retired.
      else if (id === "remove-task") {
        const m = whole.rows.get(r.ref.mode_id);
        if (m) removeTaskFromMode({ confirm, ops, mode: m, task: r.ref.task, onSaid: say }).then((ok) => { if (ok) setRcmFocus(m.key); });
      } else if (id === "link-cause") openLink(r, "cause");
      else if (id === "link-effect") openLink(r, "effect");
      else if (id === "go") reveal(r.ref.cause_id);
      else if (id === "unlink") unlinkPair(r.ref.effect_id, r.ref.cause_id);
      // A function, standard, failure or mode goes with everything under it (a counted dialog, then Undo).
      else if (id === "delete") removeRow(r);
      else if (id === "import-sheet") setSheetFor({ id: r.key, name: r.ref.name });
      else if (id === "export-csv") exportRcm(r);
    },
  };
  // A position's RCM (it and everything inside it) as a CSV file, its columns
  // named as the import reads them.
  const exportRcm = (r) => {
    const name = fmeaOn ? "FMECA" : "RCM";
    getPositionRcm(r.key, "below")
      .then((ws) => {
        saveText(positionRcmCsv(ws), exportFilename(r.ref.name, { what: name }));
        say(`Downloaded the ${what} as CSV.`, "ok", { fade: true });
      }, (e) => say(e.message, "error"));
  };
  // The FME(C)A as an Excel file, from the server (the button shows only when
  // the server offers the route: asked once, for the position picked).
  const exportExcel = (r) => {
    getFmeaExcelBlob(r.key)
      .then((blob) => {
        saveBlob(blob, exportFilename(r.ref.name, { what: "FMECA", ext: "xlsx" }));
        say("Downloaded the FME(C)A as Excel.", "ok", { fade: true });
      }, (e) => say(e.message, "error"));
  };
  useEffect(() => {
    if (!fmeaOn || excel != null || selPos == null) return;
    hasFmeaExcel(selPos).then(setExcel);
  }, [fmeaOn, excel, selPos]);
  // After an import: the RCM and the tree read again, the position opened down
  // to its failure modes, and a few words on what was added.
  const sheetImported = (result) => {
    const pos = sheetFor;
    setSheetFor(null);
    const { adds, nothing } = importSummary(result.counts);
    openAfter.current = pos.id;
    pending.current = pos.id;
    Promise.resolve(loadRcm()).then(() => load());
    say(nothing ? `Nothing new to add to “${pos.name}”.` : `Added ${adds.join(", ")} to “${pos.name}”.`);
  };
  // One cell changed: checked as the server checks it, then written. The
  // cell (or the panel's field) keeps the text as typed until it's saved; if
  // it isn't (no connection, a refusal), it stays as typed with the reason, to
  // try again. Resolves true once saved, else to the reason.
  const commit = (r, col, raw) => {
    // A refusal shows where the value was typed (under the cell, or the
    // field), the value kept: not as a toast that cuts the reason short.
    // The FME(C)A's columns are checked by its rules (on either tab: the
    // details panel edits them on the RCM tab too); the RCM's by the RCM's.
    const check = FMEA_COLUMN[col] && !FMEA_COLUMN[col].rcm ? checkFmeaValue : checkValue;
    const res = check(col, cellRow(r), raw);
    if (res.error) return res.error;
    return ops.set(r, col, res.value).then(() => {
      setEditing((e) => (e && e.key === r.key && e.col === col ? null : e));
      say("Saved.");
      return true;
    }, (e) => saveErrorText(e, { offline: navigator.onLine === false }));
  };
  // A function, standard, failure or mode opened (a double-click on its
  // name, Open… in its menu): picked in the tree, the cell being edited
  // dropped, and its details shown filling the table's room (a phone: the
  // details sheet), the focus on their heading; `start` {add: "std" | "inside"
  // | "task"} opens one of its lists on its add row instead (the focus there).
  // The "No performance standard" and "Not under a functional failure" rows
  // open only to add inside them.
  const openItem = (key, start = null) => {
    const r = whole.rows.get(key);
    // A position (a double-click on its row): its own panel, picked as a click does, then expanded.
    if (r?.type === "pos" && !start) {
      setEditing(null);
      setRcmFocus(null);
      setSelected((s) => ({ ...s, [mode]: key }));
      setPanel(true);
      if (!phone) setExpanded(true);
      setTimeout(() => detailsHeading.current?.focus(), 0);
      return;
    }
    if (!opensItem(r) && !(start?.add && (r?.type === "nostd" || r?.type === "unassigned"))) return;
    setEditing(null);
    setRcmFocus(key);
    if (display.rows.has(key)) setSelected((s) => ({ ...s, [mode]: positionOf(r) }));
    setPanel(true);
    if (!phone) setExpanded(true);
    setAddStart(start?.add ? { key, list: start.add, at: Date.now() } : null);
    if (!start?.add) setTimeout(() => detailsHeading.current?.focus(), 0);
  };
  // Expanded and back: the focus goes into the details' heading, and back to the row.
  const expandDetails = () => {
    setExpanded(true);
    setTimeout(() => detailsHeading.current?.focus(), 0);
  };
  const collapseDetails = () => {
    setExpanded(false);
    setTimeout(() => document.getElementById(`tp-${focus}`)?.focus({ preventScroll: true }), 0);
  };
  // Esc anywhere on the page (the tree too, not only the details) returns
  // from expanded, unless a dialog or menu is open (Esc closes that first) or
  // a field is being typed in. The details' own Esc is handled there.
  const collapseRef = useRef(null);
  collapseRef.current = collapseDetails;
  const wideOn = tableOn && !phone && panel && expanded; // the details across the table
  useEffect(() => {
    if (!wideOn) return undefined;
    const onKey = (e) => {
      if (e.key !== "Escape" || e.defaultPrevented || hasOpenLayer(document) || isTyping(e)) return;
      collapseRef.current?.();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [wideOn]);
  // Esc with the fit or the prediction open: back to the table, unless a dialog, list or menu is
  // open over it (Esc closes that first). Capture phase, so a picker or list over the pane is still
  // seen before its own Escape takes it away.
  const closePaneRef = useRef(null);
  closePaneRef.current = paneKind === "rbd" || paneKind === "mission" ? closeRbd : closePane;
  const paneOpen = !!panePosition;
  useEffect(() => {
    if (!paneOpen) return undefined;
    const onKey = (e) => {
      if (e.key !== "Escape" || e.defaultPrevented || hasOpenLayer(document)) return;
      if (paneSaving.current) return; // saving: it closes itself once saved
      // The RBD builder's own: a block's name or a field being typed in, or its full screen.
      if (e.target?.closest?.(".rbd-shell") && isTyping(e)) return;
      if (document.querySelector(".rbd-builder.is-full") || document.fullscreenElement?.closest?.(".rbd-shell")) return;
      closePaneRef.current?.();
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [paneOpen]);
  // Esc with Excel import and export open: back to the row's details (a dialog or menu over it first).
  const sheetOpen = !!sheet;
  useEffect(() => {
    if (!sheetOpen) return undefined;
    const onKey = (e) => {
      if (e.key !== "Escape" || e.defaultPrevented || hasOpenLayer(document)) return;
      setSheet(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [sheetOpen]);
  // The dialog stays open (Apply saying "Saving…") until the server has it;
  // a refusal shows in the dialog, with everything as it was typed.
  // A cost typed for a new task goes on the task the decision made (where the Maintenance
  // tab and the RCM's worth-doing test read it).
  const saveDecision = async ({ cost, ...answer }) => {
    const before = [...(deciding.ref.tasks || []), ...(deciding.ref.decision?.tasks || [])].map((t) => t.id);
    const out = await ops.decide(deciding, answer);
    const made = cost != null ? madeTask(before, out, answer.decision?.task) : null;
    if (made) await ops.editTask(made.id, { cost });
    setDeciding(null);
    say(cost != null && !made ? "Saved the decision. No task was made, so the cost wasn't kept." : "Saved the decision.");
  };
  const loadDecisionTasks = useCallback(() => (deciding ? ops.modeTasks(deciding) : Promise.resolve({ available: [] })), [deciding]); // eslint-disable-line react-hooks/exhaustive-deps

  const toggle = (key, force) => {
    setLevelBy((l) => ({ ...l, [mode]: null }));
    const next = new Set(open);
    const want = force ?? !next.has(key);
    if (want) next.add(key);
    else next.delete(key);
    setOpenSet(next);
  };

  // A level chosen in the ⋯ menu stays chosen until a row is opened or closed by hand
  // (levelBy is null then): rows that arrive after it was chosen (the RCM read after the
  // tree, a read again after a write) open to it too (keepLevel), nothing is closed.
  const chosenLevel = Object.prototype.hasOwnProperty.call(levelBy, mode) ? levelBy[mode] : null;
  useEffect(() => {
    if (filter || typeof chosenLevel !== "number" || !(chosenLevel > 0)) return;
    setOpenBy((o) => {
      const cur = o[mode] || defaultOpen;
      const next = keepLevel(display, cur, chosenLevel);
      return next === cur ? o : { ...o, [mode]: next };
    });
  }, [display, chosenLevel, filter, mode]); // eslint-disable-line react-hooks/exhaustive-deps

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
    pending.current = keep;
    // A tab only a class has would stay behind off Classes; Condition monitoring is a position's
    // too, so it comes along (explorerTabs.js tabForArrangement).
    const nextTab = tabForArrangement(tab, m);
    if (root) {
      // One tree on show: its own address, the arrangement in it (a product's page
      // says only Locations: Positions is how it opens).
      const q = scopedArrangeQuery(params, m, { ownPage: !!rootProp });
      if (nextTab !== tab) q.delete(tabKey);
      navigate(`${location.pathname}?${q}${location.hash}`, { replace: true, state: location.state });
      return;
    }
    // Classes covers one asset, the one the picked row is in (Derryn, 11 Nov 2026: "an asset
    // should be self contained"). Only the positions at no place (?place=none) get here unrooted.
    const asset = m === "classes" ? assetOf(data, focus != null ? display.rows.get(focus) : null) : null;
    if (asset) {
      navigate(explorerPath(m, { root: asset, sel: keep, tab: nextTab === "summary" ? null : nextTab }));
      return;
    }
    latest.current = { ...latest.current, mode: m, selected: nextSelected };
    saveTreeState(workspace, latest.current);
    // The tab comes along.
    navigate(explorerPath(m, { tab: nextTab === "summary" ? null : nextTab }),
             { state: keep ? { treeReveal: keep } : undefined });
  };

  // What isn't as usual in the tree's ⋯ menu, and putting it back: the usual
  // level, no Show only filters, no pinned branch (the search box and the
  // Positions / Locations switch are on show, so they stay as they are).
  const level = levelShown(levelBy, mode);
  const chipsOn = CHIPS.filter((c) => chips.includes(c.id) && (!c.rcmOnly || tableOn));
  // A pin on the whole tree's one top row shows everything: not a change.
  const changed = changedFromUsual({
    level, chips: chipsOn, pinned: !!pinKey && !pinCoversAll(whole, pinKey),
  });
  const resetView = () => {
    setChips([]);
    if (pinKey || (level !== DEFAULT_LEVEL && typeof level === "number")) {
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
      if (typeof level === "number" && !levelMatches(display, next, level)) setLevelBy((l) => ({ ...l, [mode]: null }));
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
    setNewAt(null);
    pending.current = id;
    load();
  };
  const closeModal = () => {
    setModal(null);
    setNewParent(null);
    setNewAt(null);
  };
  // The FME(C)A print view; its "Back" returns here (a product's structure
  // tab included: a design isn't in the Explorer's own tree).
  const openPrint = (id) => navigate(`/asset-register/positions/${id}/fmea`,
    { state: { back: `${location.pathname}${location.search}` } });
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
  // After a failure report is filed (the row menu's Add failure report…, or
  // the Failure reports tab's button): the tree read again (its roll-up), the
  // report open in the Failure reports tab under the row it was filed from
  // (?tab=reports&sel=&report=), and a few words to say so. On a phone the
  // panel is its own screen, opened on that row.
  // The product row's menu's Build an item…: the product read, then the same
  // dialog as its Summary's; once built, the tree read again and a few words.
  const buildFrom = (id) => {
    getProduct(id).then(setBuildFor, (e) => say(`The product didn't load: ${e.message}`, "error"));
  };
  const built = (out) => {
    setBuildFor(null);
    load();
    say(`Built ${out.name}: ${out.counts.positions} positions, with the item (serial ${out.serial}) fitted at the top.`, "ok");
  };
  // An event logged: the tree read again (its work), and what it raised said.
  const eventLogged = (out) => {
    setEventFor(null);
    load();
    const raised = out.work_orders_raised || [];
    say(raised.length
      ? `Logged ${out.event.event_type}: raised ${raised.map((w) => `#${w.number}`).join(", ")}.`
      : `Logged ${out.event.event_type}. No task here is waiting for it, or its work order is open already.`, "ok", { fade: !raised.length });
  };
  const reportFiled = (view) => {
    const select = reportFor?.select || view.position?.id;
    setReportFor(null);
    if (select != null) pending.current = select;
    load();
    const q = new URLSearchParams(params);
    q.set(tabKey, "reports");
    if (select != null) q.set("sel", select);
    q.set("report", view.id);
    navigate(`${location.pathname}?${q}${location.hash}`, { replace: true, state: phone ? { treeDetail: select } : location.state });
    say(`Reported ${view.label}.`, "ok", { fade: true });
  };
  // Where a row can move to: its kind's tree, without it and what's inside it.
  const targetsFor = (row) => moveTargets(row.type === "loc" ? data?.locations : data?.positions, row.key);

  const nothing = data && (mode === "locations" ? !data.locations.length && !data.positions.length : !data.positions.length);
  const EMPTY = {
    locations: ["No locations yet", "Add the places you look after (a site, a house), the areas and rooms inside them, and the stores."],
  };
  const emptyDetail = error?.gone ? (
    <div className="card empty">
      <h2>That asset isn&apos;t here</h2>
      <p>It may have been deleted, or the link is an old one.</p>
      <p><Link to={ASSETS_LIST_PATH}>See the assets</Link></p>
    </div>
  ) : error?.notAllowed ? (
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
        || "Add the first position, or bring your hierarchy in from Excel."}</p>
      <div className="section-empty-action">
        {mode === "locations" ? (
          <button type="button" onClick={() => setModal("location")}><PlusIcon /> New location</button>
        ) : (
          <>
            <button type="button" onClick={() => setModal("position")}><PlusIcon /> New position</button>
            <button type="button" className="secondary" onClick={() => openSheet("import")}>Import from Excel</button>
          </>
        )}
      </div>
      <p className="section-empty-more">
        <ShowMe help={HELP_TREE}>How to build your asset tree</ShowMe>
        {" · "}
        <ShowMe help={HELP}>How to build RCM on your asset tree</ShowMe>
        {" · "}
        <ShowMe help={HELP_FMEA}>How to score an FME(C)A on your asset tree</ShowMe>
      </p>
    </div>
  ) : (
    <div className="card empty">Pick a row in the tree to see it here.</div>
  );

  const paneEmpty = !data ? (error?.gone ? "That asset isn't here." : error?.notAllowed ? "Not on for this account." : error ? "Couldn't load the tree." : "Loading the tree…")
    : filter && notPlaced && !query.trim() && !chips.length ? "Every position is at a location."
    : filter ? (
      <>Nothing matches{query.trim() ? ` “${query.trim()}”` : ""}. <button type="button" className="link" onClick={() => { setQuery(""); setChips([]); }}>Clear the filter</button></>
    ) : nothing ? `${EMPTY[mode]?.[0] || "No positions yet"}.` : "Nothing here.";

  const n = (count, one, many = `${one}s`) => `${count.toLocaleString("en-AU")} ${count === 1 ? one : many}`;
  const what = fmeaOn ? "FME(C)A" : "RCM";
  // The line under the tree's title shows only what needs saying: that the
  // RCM didn't load, or how many rows match the filter. No counts otherwise.
  const statusText = !data ? "" : measOn && !filter ? (meas.error ? `The measurements didn't load: ${meas.error}` : "")
    : modelsOn && !filter ? (pmodels.error ? `The models didn't load: ${pmodels.error}` : "")
    : missionsOn && !filter ? (pmissions.error ? `The missions didn't load: ${pmissions.error}` : "")
    : rcmOn && !filter
    ? (rcmError ? `The ${what} didn't load: ${rcmError}` : "")
    : filter
    ? [`${n(filter.match.size, "match", "matches")}, shown with what they're inside`, showingOnly(chipsOn.map((c) => c.label))].filter(Boolean).join(" · ")
    : "";

  // The Explorer is always one asset (?root=), so there's nothing to say about that; only the
  // positions at no place (?place=none) say what they are, with the way back to the assets.
  const notice = !root && notPlaced && (
    <p className="tp-notice">
      <span className="maint-badge">Not at a location yet</span>{" "}
      <Link to={ASSETS_LIST_PATH}>Back to the assets</Link>
    </p>
  );

  // The panel shows the row from the whole tree, so its way up is the whole path.
  const row = (phone ? detailKey : focus) != null ? whole.rows.get(phone ? detailKey : focus) ?? null : null;
  const posRow = selPos != null ? display.rows.get(selPos) : null;
  // ?fit_prior=<library record> (the Library page's Use as a prior…): the fit opens in the table
  // area on the position picked with that record as the prior; with none picked, the tab says to pick one.
  const fitPrior = params.get("fit_prior");
  useEffect(() => {
    if (!fitPrior || !data || !modelsOn) return;
    if (posRow?.type !== "pos") { say("Pick the position to fit, then Life model › Fit a life model… (the record is chosen for you).", "ok"); return; }
    // ?fit_prior_cov=<JSON>: the record's covariates given on the Library page.
    let covariates = {};
    try { covariates = JSON.parse(params.get("fit_prior_cov") || "{}") || {}; } catch { covariates = {}; }
    openFit({ id: posRow.key, name: posRow.ref.name || "(no name)", position_class: posRow.ref.position_class || "" },
      { start: { method: "bayes", priorKind: "library", recordId: fitPrior, covariates },
        query: (q) => { q.delete("fit_prior"); q.delete("fit_prior_cov"); } });
  }, [fitPrior, data, modelsOn, posRow?.key]); // eslint-disable-line react-hooks/exhaustive-deps
  // The heading's Full screen: the tree pane's 30 × 30 icon button (its name
  // and the F key in the tooltip), on a phone too (no key there).
  const fullButton = (
    <FullScreenButton ref={fullBtn} full={full} onClick={toggleFull} base="tp-icon-btn"
                      shortcut={phone ? "" : "F"} shortcutNote={phone ? "" : "also in the tree"} />
  );

  // The RCM tab: the table's columns beside the tree, the heading over them,
  // and the details of the function, failure or mode picked.
  // The Evidence check column only once evidence is linked somewhere (or as
  // chosen in the Columns menu). A window under 1400 px: fewer usual columns
  // (no Interval, folded into the Task cell, nor Evidence check), so the table
  // fits beside the tree; its columns narrow to fit too (TreePane).
  // The FME(C)A tab: the worksheet's columns (fmeaWorksheet.js), remembered apart from the RCM's.
  const shownCols = fmeaOn ? fmeaTableCols(fprefs, { narrow, wide }) : tableCols(rprefs, linkedEvidence, { narrow });
  const colMap = fmeaOn ? FMEA_COLUMN : COLUMN;
  const prefsW = fmeaOn ? fprefs.widths : rprefs.widths;
  // The details expanded (a wide screen, the details shown): only the tree column beside them.
  // The fit or the prediction open (a wide screen): the same, it in the table's room.
  const paneWide = !!panePosition && !phone;
  const wideDetails = wideOn || paneWide;
  const cols = wideDetails ? [] : shownCols.map((id) => colMap[id]).filter(Boolean);
  const widths = {};
  for (const c of cols) widths[c.id] = prefsW[c.id] ?? c.width;
  // The Measurements tab's table: the tree, then Kind, Latest, State, Trend,
  // Next due and Record; a position's roll-up across them.
  const mcols = wideDetails ? [] : MEAS_TABLE_COLS.filter((c) => measCols.includes(c.id));
  const mwidths = Object.fromEntries(mcols.map((c) => [c.id, c.width]));
  const measTable = {
    cols: mcols, widths: mwidths, treeW: shownWidth, total: shownWidth + mcols.reduce((t, c) => t + c.width, 0), expanded: wideDetails,
    tab: "measurements", what: "measurements", treeHead: MEAS_TREE_HEAD, readOnly: true,
    canEditName: () => false, onEdit: () => {}, onCommit: () => {}, onCancel: () => {}, onGoto: (key) => reveal(key),
    renderCell: (r, c) => (isMeasRow(r) ? <MeasCell r={r} col={c} onSaved={meas.patch} /> : null),
    onOpen: (key) => (isMeasRow(display.rows.get(key)) ? openMeas(key) : undefined),
    rollupOf: (r, isOpen) => (r.type === "pos" ? measRollup(r, isOpen) : null),
    phoneRow: (r, isOpen) => measPhoneRow(r, r.type === "pos" ? measRollup(r, isOpen) : ""),
    hint: null, drag: null,
  };
  // The Modelling tab's table: the tree, then Kind, Source, Headline, Mean life (or B10),
  // Confidence and Used by; a position's roll-up across them.
  const lcols = wideDetails ? [] : MODEL_COLUMNS.filter((c) => modelCols.includes(c.id));
  const lwidths = Object.fromEntries(lcols.map((c) => [c.id, c.width]));
  const modelTable = {
    cols: lcols, widths: lwidths, treeW: shownWidth, total: shownWidth + lcols.reduce((t, c) => t + c.width, 0), expanded: wideDetails,
    tab: "models", what: "life models", treeHead: MODEL_TREE_HEAD, readOnly: true,
    canEditName: () => false, onEdit: () => {}, onCommit: () => {}, onCancel: () => {}, onGoto: (key) => reveal(key),
    renderCell: (r, c) => (isModelRow(r) ? <ModelCell r={r} col={c} /> : null),
    onOpen: (key) => (isModelRow(display.rows.get(key)) ? openModel(key) : undefined),
    rollupOf: (r, isOpen) => (r.type === "pos" ? modelRollup(r, isOpen) || (r.lall?.n ? "" : classModelHint(r, pmodels.classModels, { short: true })) : null),
    phoneRow: (r, isOpen) => modelPhoneRow(r, r.type === "pos" ? modelRollup(r, isOpen) : ""),
    hint: null, drag: null,
  };
  // The Missions tab's table: the tree, then Phases, Length, Completes and RBD.
  const mscols = wideDetails ? [] : MISSION_COLUMNS;
  const missionTable = {
    cols: mscols, widths: Object.fromEntries(mscols.map((c) => [c.id, c.width])), treeW: shownWidth,
    total: shownWidth + mscols.reduce((t, c) => t + c.width, 0), expanded: wideDetails,
    tab: "missions", what: "missions", treeHead: MISSION_TREE_HEAD, readOnly: true,
    canEditName: () => false, onEdit: () => {}, onCommit: () => {}, onCancel: () => {}, onGoto: (key) => reveal(key),
    renderCell: (r, c) => (isMissionRow(r) ? <MissionCell r={r} col={c} /> : null),
    onOpen: (key) => {
      const r = display.rows.get(key);
      return isMissionRow(r) ? openMissionRow(r) : undefined;
    },
    rollupOf: (r, isOpen) => (r.type === "pos"
      ? <MissionRollup text={missionRollup(r, isOpen)} onAdd={viewOnly ? null : () => addMission(r.key, r.ref.name || "(no name)")} /> : null),
    phoneRow: (r, isOpen) => missionPhoneRow(r, r.type === "pos" ? missionRollup(r, isOpen) : ""),
    hint: null, drag: null,
  };
  const table = measOn ? measTable : modelsOn ? modelTable : missionsOn ? missionTable : rcmOn ? {
    cols, widths, treeW: shownWidth, total: shownWidth + cols.reduce((t, c) => t + widths[c.id], 0), expanded: wideDetails,
    foldInterval: !fmeaOn && !shownCols.includes("interval"),
    intervalW: rprefs.widths.interval ?? COLUMN.interval.width,
    // Which tab's table this is: its chips, its tree column's heading, its
    // name for screen readers, the phone's second line, and the column sorted by.
    tab, fmea: fmeaOn, what, treeHead: fmeaOn ? FMEA_TREE_HEAD : null,
    phoneLine: fmeaOn ? fmeaPhoneLine : null,
    // The FME(C)A tab: a function's or position's "3 of 5 scored" across its
    // text columns (a wide screen), not under Cause.
    rollup: fmeaOn ? { ids: FMEA_ROLLUP_COLS, text: (cr) => scoredWords(cr.sum) } : null,
    sort: fmeaOn ? fsort : null, onSort: fmeaOn ? (col) => setFsort((s) => nextSort(s, col)) : null,
    editing, readOnly: false,
    canEditName: (r) => EDITABLE.has(r.type),
    onEdit: (key, col) => { setRcmFocus(key); setEditing({ key, col }); },
    onCommit: commit, onCancel: () => setEditing(null), onDecision: (r) => setDeciding(r),
    // A double-click on a function, standard, failure or mode (on its name, not on a cell edited in place): its details, expanded.
    onOpen: openItem,
    // A decision's linked notes (evidence "working") in the table: the function is picked and its
    // details open with its notes and rationale in full.
    onNotes: (r) => openNotes(r.type === "std" ? r.ref.function_id : r.key),
    onGoto: (key) => reveal(key),
    // The position picked, when it has no functions yet: its row says how to start.
    hint: !wideDetails && rcm?.positions && posRow?.type === "pos" && !posRow.rcmKids ? posRow.key : null,
    // Drag and drop (a wide screen): which rows move, the mark on the row
    // under the pointer, the failure modes picked to move together.
    drag: rcm && !phone && !fmeaOn ? {
      begin: beginDrag,
      canDrag: (r) => !!dragSource(whole, r.key),
      block: (r) => dragBlock(r),
      taskOf: (r) => tasksOf(r.ref).find((t) => t.id) || null,
      picked,
      onPickMany: pickMany,
      over: drag?.key ? { key: drag.key, zone: drag.zone, state: drag.verdict?.state, copy: drag.src.kind === "copy" } : null,
      // A copy leaves its row where it is: never shown as moving.
      dragging: drag ? new Set(drag.src.kind === "task" || drag.src.kind === "copy" ? [] : drag.src.keys) : null,
    } : null,
  } : null;
  const msg = message && <p className={"tt-msg " + message.tone} role="status" title={message.text}>{message.text}</p>;
  // The panel's heading and tabs, in the two slim rows over the tree on both
  // tabs (a wide screen): the same elements on each, so nothing in them is
  // drawn afresh and the focus stays on the tab picked.
  const summaryRow = !tableOn && data && !nothing ? row : null;
  // The RCM and FME(C)A tabs' "…": the worksheet in and out, the column
  // chooser (it hangs under the heading's controls), and the FME(C)A's print
  // view and guide. Adding a function is the position's row menu (and the RCM
  // position panel's button).
  const rcmMenu = rcmOn && posRow?.type === "pos" ? [
    { id: "import-sheet", label: "Import worksheet…", onSelect: () => setSheetFor({ id: posRow.key, name: posRow.ref.name }) },
    { id: "export-csv", label: "Export CSV", onSelect: () => exportRcm(posRow) },
    fmeaOn && excel && { id: "export-excel", label: "Export Excel", onSelect: () => exportExcel(posRow) },
    !phone && { id: "columns", label: "Columns…", onSelect: () => setColsOpen(true) },
    fmeaOn && { id: "print", label: "Print view", onSelect: () => openPrint(posRow.key) },
    fmeaOn && { id: "guide", label: "Show me how", onSelect: () => openGuide(HELP_FMEA.guide) },
  ].filter(Boolean) : [];
  const moreButton = () => frame.current?.querySelector(".tt-headslot .ovm-trigger");
  const columns = colsOpen && !phone && (fmeaOn ? (
    <ColumnChooser open cols={shownCols} usual={fmeaUsualCols({ narrow, wide })} columns={FMEA_COLUMNS}
                   onCols={(next, o) => setFprefs((p) => withFmeaCols(p, next, o))}
                   onClose={() => setColsOpen(false)} returnFocus={moreButton} />
  ) : (
    <ColumnChooser open cols={shownCols} usual={usualCols({ narrow })}
                   onCols={(next, o) => setRprefs((p) => withTableCols(p, next, shownCols, o))}
                   onClose={() => setColsOpen(false)} returnFocus={moreButton} />
  ));
  // Another tab or position: the chooser closes (it was for that table).
  useEffect(() => setColsOpen(false), [tab, selPos, phone]);
  // The Measurements tab's "…": add one of each kind on the position picked,
  // the columns, the CSV of everything under it; and the row picked's own
  // (Add reading…, Edit limits…, Move…, from its details).
  const exportMeas = (r) => {
    const out = [];
    const walk = (k) => {
      const x = whole.rows.get(k);
      if (!x) return;
      if (isMeasRow(x)) out.push(x.ref.row);
      for (const c of x.kids) walk(c);
    };
    walk(r.key);
    saveText(measurementsCsv(out), exportFilename(r.ref.name, { what: "measurements" }));
    say("Downloaded the measurements as CSV.", "ok", { fade: true });
  };
  // The adds are the ones a position row's menu starts with (one list: measAddActions).
  const measMenu = measOn && posRow?.type === "pos" ? [
    ...measAddActions(posRow, { viewOnly }).map((a) => ({ ...a, title: a.reason, onSelect: () => measAdd(posRow, a.id.slice(5)) })),
    !phone && { id: "m-columns", label: "Columns…", onSelect: () => setColsOpen(true) },
    { id: "m-csv", label: "Export CSV", onSelect: () => exportMeas(posRow) },
    ...(isMeasRow(focusRow) && panel ? tabMenu || [] : []),
  ].filter(Boolean) : [];
  const measColumns = measOn && colsOpen && !phone && (
    <ColumnChooser open cols={measCols} usual={MEAS_TABLE_COLS.map((c) => c.id)} columns={MEAS_TABLE_COLS}
                   onCols={(next) => setMeasCols(next)} onClose={() => setColsOpen(false)} returnFocus={moreButton} />
  );
  // The Modelling tab's "…": attach a model to the position picked (fit from its history, a
  // saved one, its class's), the columns; and the row picked's own (from its details).
  const modelPosition = posRow?.type === "pos" ? { id: posRow.key, name: posRow.ref.name || "(no name)" } : null;
  // The heading's "…": the same three groups (two levels), a line, Columns… and the row picked's own.
  const modelMenu = modelsOn && modelPosition ? [
    ...modelGroups(modelPosition.id, posRow.ref.position_class).map((g) => ({
      ...g, items: g.items.map((it) => ({ ...it, title: it.reason, onSelect: () => attachAt(modelPosition.id, it.id) })),
    })),
    { separator: true },
    !phone && { id: "l-columns", label: "Columns…", onSelect: () => setColsOpen(true) },
    ...(isModelRow(focusRow) && panel ? tabMenu || [] : []),
  ].filter(Boolean) : [];
  const modelColumns = modelsOn && colsOpen && !phone && (
    <ColumnChooser open cols={modelCols} usual={MODEL_USUAL} columns={MODEL_COLUMNS}
                   onCols={(next) => setModelCols(next)} onClose={() => setColsOpen(false)} returnFocus={moreButton} />
  );
  // The Missions tab's "…": add a mission to the position's RBD (or build one), open the RBD.
  const missionMenu = missionsOn && posRow?.type === "pos"
    ? positionMissionActions(display.rows.get(posRow.key) || posRow, { viewOnly }).map((it) => ({
      ...it, title: it.reason || it.title, onSelect: () => missionAction(display.rows.get(posRow.key) || posRow, it.id) }))
    : [];
  const head = phone ? null : missionsOn ? posRow && posRow.type === "pos" && (
    <SlimHeader display={whole} row={posRow} onSelect={reveal} onCrumb={(k) => crumbGo(k, reveal)} above={above}
                headingRef={headingRef} fullScreenButton={fullButton} message={msg} heading={heading}
                meta={pmissions.links ? (
                  <span className="tt-rollup mt-rollup">
                    <MissionRollup text={missionRollup(display.rows.get(posRow.key) || posRow, true)}
                                   onAdd={viewOnly ? null : () => addMission(posRow.key, posRow.ref.name || "(no name)")} />
                  </span>
                ) : null}
                menu={missionMenu} />
  ) : modelsOn ? posRow && posRow.type === "pos" && (
    <SlimHeader display={whole} row={posRow} onSelect={reveal} onCrumb={(k) => crumbGo(k, reveal)} above={above}
                headingRef={headingRef} fullScreenButton={fullButton} message={msg} heading={heading}
                meta={pmodels.links ? <span className="tt-rollup mt-rollup">{modelRollup(posRow, false) || classModelHint(display.rows.get(posRow.key) || posRow, pmodels.classModels) || "No models here yet"}</span> : null}
                menu={modelMenu} popover={modelColumns} />
  ) : measOn ? posRow && posRow.type === "pos" && (
    <SlimHeader display={whole} row={posRow} onSelect={reveal} onCrumb={(k) => crumbGo(k, reveal)} above={above}
                headingRef={headingRef} fullScreenButton={fullButton} message={msg} heading={heading}
                meta={meas.data ? <span className="tt-rollup mt-rollup">{measRollup(posRow, false) || "Nothing measured here yet"}</span> : null}
                menu={measMenu} popover={measColumns} />
  ) : rcmOn ? posRow && posRow.type === "pos" && (
    <SlimHeader display={whole} row={posRow} onSelect={reveal} onCrumb={(k) => crumbGo(k, reveal)} above={above}
                headingRef={headingRef} fullScreenButton={fullButton} message={msg} heading={heading}
                meta={rcm?.positions ? <span className="tt-rollup"><RollupBadges rollup={rollupOf(rcm, posRow.key, whole)} /></span> : null}
                menu={rcmMenu} popover={columns} />
  ) : summaryRow && (
    <SlimHeader display={whole} row={summaryRow} onSelect={reveal} onCrumb={(k) => crumbGo(k, reveal)} above={above}
                headingRef={headingRef} fullScreenButton={fullButton} heading={heading} menu={tabMenu || []}
                meta={rowKind(summaryRow) ? <span className="tt-kind">{rowKind(summaryRow)}</span> : null}
                message={message?.fade ? msg : null} />
  );
  const tabsRow = tableOn ? (posRow?.type === "pos" ? posRow : null) : summaryRow;
  const headTabs = !phone && tabsRow && <HeaderTabs row={tabsRow} tab={tab} onTab={setTab} />;
  const detailsRow = rcmOn && panel && isRcmRow(focusRow) && focusRow.type !== "cause" && focusRow.type !== "nofail" ? cellRow(focusRow) : null;
  // The FME(C)A tab with a position picked: its criticality matrix beside the table.
  const fmeaPosRow = fmeaOn && panel && !detailsRow && focusRow?.type === "pos" ? focusRow : null;
  // The RCM tab with a position picked: its operating context and functions beside the table.
  const rcmPosRow = rcmOn && !fmeaOn && panel && !detailsRow && focusRow?.type === "pos" ? focusRow : null;
  const rcmPosition = usePosition(rcmPosRow ? rcmPosRow.key : null, version);
  const rcmPosFns = useMemo(() => (rcmPosRow ? functionSummary(whole, rcmPosRow) : []), [rcmPosRow, whole]);
  const fmeaPos = useMemo(() => (fmeaPosRow ? positionSummary(whole, fmeaPosRow.key, fopts) : null), [fmeaPosRow, whole, fopts]);
  // A failure mode moved under another functional failure from the panel: a
  // refusal is said in the heading, in plain words.
  // A function's notes and rationale opened (a decision's linked notes): the function picked, its
  // details shown with the notes in full.
  const openNotes = (fnKey) => {
    pick(fnKey, { go: true });
    setNotesAt({ key: fnKey, at: Date.now() });
  };
  const panelOps = {
    ...ops,
    create: (kind, where, text) => ops.create(kind, where, text).then((id) => { openNew.current = id; setNewTick((t) => t + 1); return id; }),
    notesView: { token: (r) => (notesAt?.key === r.key ? notesAt.at : null) },
    assign: (r, ffId, fnId = null) => ops.assign(r, ffId, fnId).catch((e) => say(saveErrorText(e, { offline: navigator.onLine === false }), "error")),
  };
  // The FME(C)A's groups in a failure mode's details (both tabs; first on
  // the FME(C)A tab), with the action priority table and the RCM read for the
  // "Under" choice.
  const fmeaPanel = rcm ? { on: fmeaOn, opts: fopts, rcm } : null;
  const closeDetails = () => {
    setPanel(false);
    document.getElementById(`tp-${focus}`)?.focus({ preventScroll: true });
  };
  const rcmSide = detailsRow ? (
    <div className="rw tt-side">
      {phone && <div className="rw-scrim" onClick={() => setPanel(false)} aria-hidden="true" />}
      <Details r={detailsRow} display={display} whole={whole} readOnly={false} phone={phone} headingRef={detailsHeading} ops={panelOps}
               links={{ onLink: openLink, onUnlink: unlinkPair }}
               onCommit={commit} onAdd={addInside} onDelete={removeRow} onDecision={(r) => setDeciding(r)}
               expanded={wideDetails} onExpand={expandDetails} onCollapse={collapseDetails}
               addStart={addStart} onSaid={say}
               onMove={fmeaOn ? null : (r, { task = false } = {}) => (task ? setMoving({ taskFrom: r.key }) : setMoving({ src: dragSource(whole, r.key) }))}
               onClose={closeDetails} fmea={fmeaPanel}
               options={options} workings={detailsRow.type === "mode" ? workingsFor(rcm, detailsRow.ref.id) : []}
               onSelect={(k, o) => (o?.notes ? openNotes(k) : reveal(k))} />
    </div>
  ) : fmeaPosRow && fmeaPos ? (
    // The FME(C)A tab with a position picked: its criticality matrix, Cr and
    // the modes ranked by Cm (a sheet on a phone).
    <div className="rw tt-side">
      {phone && <div className="rw-scrim" onClick={() => setPanel(false)} aria-hidden="true" />}
      <FmeaPositionPanel row={fmeaPosRow} summary={fmeaPos} phone={phone} headingRef={detailsHeading} onClose={closeDetails}
                         expanded={wideDetails} onExpand={expandDetails} onCollapse={collapseDetails}
                         onSelect={(k) => { reveal(k); setPanel(true); }} />
    </div>
  ) : rcmPosRow ? (
    <div className="rw tt-side">
      {phone && <div className="rw-scrim" onClick={() => setPanel(false)} aria-hidden="true" />}
      <RcmPositionPanel row={rcmPosRow} kind={rowKind(rcmPosRow) || "Position"} functions={rcmPosFns} position={rcmPosition}
                        phone={phone} headingRef={detailsHeading} onClose={closeDetails}
                        expanded={wideDetails} onExpand={expandDetails} onCollapse={collapseDetails}
                        onSelect={(k) => { reveal(k); setPanel(true); }}
                        onAdd={() => runAdd({ ref: { add: "fn", position_id: rcmPosRow.key } })}
                        onContextSaved={(text) => rememberChange(rcmPosRow.key, version, { operating_context: text })} />
    </div>
  ) : wideDetails && (
    // Expanded with a position picked: the room says what to pick (the tree beside it).
    <div className="rw tt-side">
      <aside className="rw-panel rw-panel-empty is-expanded" aria-label="Details"
             onKeyDown={(e) => { if (e.key === "Escape") { e.stopPropagation(); collapseDetails(); } }}>
        <div className="rw-panel-head">
          <div className="rw-panel-kind">Details</div>
          <div className="rw-panel-btns">
            <button type="button" className="ghost sm rw-x" onClick={collapseDetails} aria-label="Back to table" title="Back to table (Esc)"><ShrinkIcon /></button>
          </div>
        </div>
        <p className="rw-inside">{fmeaOn ? "Pick a function or failure mode in the tree to see it here." : "Pick a function, performance standard, functional failure or failure mode in the tree to see it here."}</p>
      </aside>
    </div>
  );
  // On a phone the tabs over the tree say which row they're for (the row
  // picked), so they don't read as tabs for the tree itself.
  const phoneTabs = phone && posRow && tabsFor(posRow).length > 1 && (
    <div className="tp-tabs-wrap">
      <p className="tp-tabs-for">For <strong>{posRow.ref.name || "(no name)"}</strong></p>
      <Tabs tabs={tabsFor(posRow)} value={shownTab(tab, posRow)} onChange={setTab} label={`What to show for ${posRow.ref.name || "this row"}`} className="tp-tabs" wholeTabs />
    </div>
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
  // The Failure reports tab (in the same panel): the report open (?report=),
  // opening one, filing one at a position (from the tab's button: shown under
  // the row picked once filed), and the tree read again when one opens or closes.
  const reportsApi = {
    id: params.get("report"),
    open: (id) => setQuery_((q) => (id ? q.set("report", id) : q.delete("report"))),
    onNew: (id, name) => setReportFor({ id, name, select: row?.key ?? id }),
    onChanged: load,
    viewOnly,
  };
  // The Summary tab's page about the row picked: beside the tree in the pane
  // (a wide screen, its heading and tabs over it in the slim rows), or its own
  // screen on a phone.
  // The row's own changes (the tree's row menu, less Pin and Isolate), for
  // the Summary's add row and footer.
  const summaryActionsOf = (r) => (r ? designActions(summaryActions(r, { mode, viewOnly, kidsOf: (k) => kids.get(k) || 0 }), designScope, { row: r, viewOnly })
    .map((a) => ({ ...a, onSelect: () => rowMenu.onAction(r, a.id) })) : []);
  const summary = !tableOn && (
    <section className="tx-detail" aria-label="Details"
             onKeyDown={(e) => {
               if (e.key === "Escape" && !phone && focus) document.getElementById(`tp-${focus}`)?.focus();
             }}>
      {(!phone || detailKey) && (
        <TreeDetail ref={headingRef} display={whole} row={data && !nothing ? row : null} today={data?.today || ""}
                    onSelect={selectFromPanel} onCrumb={(k) => crumbGo(k, selectFromPanel)} above={above}
                    back={back} version={version} empty={emptyDetail} headless={!phone} heading={heading}
                    tab={tab} onTab={setTab} fullScreenButton={fullButton} reports={reportsApi} within={root} structure={structure}
                    menu={tabMenu || []} onMenu={setTabMenu}
                    actions={summaryActionsOf(data && !nothing ? row : null)} />
      )}
    </section>
  );
  // The Measurements tab with a row picked: its details beside the table (a sheet on a phone).
  const measRow = measOn && panel && isMeasRow(focusRow) ? focusRow : null;
  const measSide = measRow ? (
    <div className="rw tt-side">
      {phone && <div className="rw-scrim" onClick={() => setPanel(false)} aria-hidden="true" />}
      <MeasSide r={measRow} phone={phone} expanded={wideDetails} onExpand={expandDetails} onCollapse={collapseDetails}
                onClose={closeDetails} headingRef={detailsHeading} onMenu={setTabMenu} onChanged={() => meas.load()}
                today={data?.today} />
    </div>
  ) : null;
  // The Modelling tab with a model row picked: its details beside the table (a sheet on a phone).
  const modelRow = modelsOn && panel && isModelRow(focusRow) ? focusRow : null;
  const modelSide = modelRow ? (
    <div className="rw tt-side">
      {phone && <div className="rw-scrim" onClick={() => setPanel(false)} aria-hidden="true" />}
      <ModelSide r={modelRow} phone={phone} expanded={wideDetails} onExpand={expandDetails} onCollapse={collapseDetails}
                 onClose={closeDetails} headingRef={detailsHeading} onMenu={setTabMenu} onAction={modelAction} />
    </div>
  ) : null;
  // The fit or the prediction in the table area (a wide screen), or the whole screen with Back (a
  // phone). A reloaded "Refresh the prediction…" (no seed) refreshes the position's prediction
  // rather than adding a second one.
  const seed = panePosition && paneSeed?.id === panePosition.id && paneSeed.kind === paneKind ? paneSeed : null;
  const paneProps = panePosition ? {
    position: panePosition, phone, headingRef: paneHeading, onClose: () => closePane(),
    onDirty: (d) => { paneDirty.current = d; }, onSaving: (b) => { paneSaving.current = b; },
    onDone: (made, text) => {
      closePane({ focusRow: false });
      say(text);
      // The new row picked and brought into view once the models are read again.
      if (made?.id) pending.current = modelKey(made.id);
      pmodels.load();
    },
  } : null;
  const predictLink = seed ? seed.link : panePosition ? predictionOf(panePosition.id) : null;
  const fitAt = panePosition ? fitPreset(seed, paneAt.from, pmodels.links) : null;
  const paneSide = !panePosition ? null : paneKind === "rbd" ? (
    <div className="rw tt-side">
      <RbdPane key={`${paneAt.rbd}:${seed?.n || 0}`} rbdId={paneAt.rbd} position={panePosition} built={seed?.built || null}
               onRebuild={seed?.start?.rebuild && seed.link && !viewOnly ? () => buildRbd(panePosition, seed.link) : null}
               phone={phone} headingRef={paneHeading} onClose={closeRbd}
               onDirty={(d) => { paneDirty.current = d; }}
               onSaved={(id) => {
                 pmodels.load();
                 if (missionsOn) pmissions.load();
                 // Save as new: the copy is what's open now, as on the RBD's page.
                 if (id && id !== paneAt.rbd) setQuery_((q) => { setPaneQuery(q, "rbd", panePosition.id, { rbd: id }); });
               }}
               onOpenFull={(e, path) => {
                 if (!paneDirty.current) return;
                 e.preventDefault();
                 leavePane().then((ok) => ok && navigate(path));
               }} />
    </div>
  ) : paneKind === "mission" && paneAt.mission === NEW_MISSION ? (
    <div className="rw tt-side">
      <NewMissionPane position={panePosition} phone={phone} headingRef={paneHeading}
                      taken={(display.rows.get(panePosition.id)?.kids || []).map((k) => display.rows.get(k))
                        .filter((x) => x?.type === "mission").map((x) => x.ref.mission?.name || "")}
                      onClose={() => closePane()}
                      onCreate={(name) => createMission(panePosition.id, panePosition.name, name)} />
    </div>
  ) : paneKind === "mission" && parseMissionParam(paneAt.mission) ? (
    <div className="rw tt-side">
      <MissionPane key={`${paneAt.mission}:${seed?.n || 0}`} rbdId={parseMissionParam(paneAt.mission).rbdId}
                   missionId={parseMissionParam(paneAt.mission).missionId} position={panePosition} phone={phone}
                   phase={seed?.start?.phase ?? null}
                   headingRef={paneHeading} onClose={() => leavePane().then((ok) => ok && closePane())}
                   onDirty={(d) => { paneDirty.current = d; }}
                   onSaved={(text) => { if (text) say(text); pmissions.load(); }}
                   onOpenRbd={() => openRbd(panePosition, parseMissionParam(paneAt.mission).rbdId)}
                   onDelete={() => {
                     const { rbdId, missionId } = parseMissionParam(paneAt.mission);
                     const ref = whole.rows.get(missionKey(rbdId, missionId))?.ref;
                     const m = ref?.mission || { id: missionId, name: "this mission" };
                     removeMission(panePosition.id, rbdId, m, !!ref?.rbd?.mission_rbd).then((gone) => gone && closePane());
                   }} />
    </div>
  ) : paneKind === "redundancy" ? (
    <div className="rw tt-side">
      <RedundancyPane key={`${panePosition.id}:${seed?.n || 0}`} position={panePosition} phone={phone} headingRef={paneHeading}
                      readOnly={viewOnly || null} onClose={() => leavePane().then((ok) => ok && closePane())}
                      onDirty={(d) => { paneDirty.current = d; }}
                      onChanged={(text) => { say(text); load(); }}
                      onRebuild={builtRbdLink(pmodels.links, panePosition.id) && !viewOnly
                        ? () => askRebuild(panePosition, builtRbdLink(pmodels.links, panePosition.id)) : null} />
    </div>
  ) : paneKind === "plan" ? (
    <div className="rw tt-side">
      <OperatingPlanPane key={`${panePosition.id}:${seed?.n || 0}`} position={panePosition} root={root || null} phone={phone}
                         headingRef={paneHeading} readOnly={viewOnly || null}
                         onClose={() => leavePane().then((ok) => ok && closePane())}
                         onDirty={(d) => { paneDirty.current = d; }}
                         onChanged={(text) => { say(text); setVersion((v) => v + 1); }} />
    </div>
  ) : paneKind === "bind" && bindingFromParam(paneAt.bind) ? (
    <div className="rw tt-side">
      <CovariateBindPane key={`${paneAt.bind}:${seed?.n || 0}`} binding={bindingFromParam(paneAt.bind)}
                         name={seed?.start?.name || ""} link={seed?.link || null} {...paneProps} />
    </div>
  ) : paneKind === "predict" ? (
    // Waits for the models, so a reload knows whether it refreshes one.
    seed || pmodels.links ? (
      <div className="rw tt-side">
        <PredictionPane key={`${panePosition.id}:${seed?.n || 0}:${predictLink?.id || ""}`} link={predictLink} {...paneProps} />
      </div>
    ) : null
  ) : fitAt ? (
    <div className="rw tt-side">
      <FitPane key={`${panePosition.id}:${seed?.n || 0}`} {...fitAt} {...paneProps} />
    </div>
  ) : null;
  // Excel import and export: in the panel's place (Summary tab), its own screen on a phone.
  // One asset open: its branches only, never the whole register's tree.
  const assetTree = !!root && !rootProp && data?.scope?.kind !== "design";
  const unitBranch = root && data?.scope?.kind === "unit" ? { id: root, name: data.scope.name || "(no name)" } : null;
  const sheetSide = sheet && !tableOn ? (
    <TreeSheetPane key={sheet.n} start={sheet.start} branch={sheet.branch} whole={!root} phone={phone} headingRef={sheetHeading}
                   readOnly={viewOnly || null} onClose={() => setSheet(null)}
                   onChanged={(text) => { say(text, "ok", { fade: true }); load(); }} />
  ) : null;
  const side = sheetSide && !phone ? sheetSide : rcmOn ? rcmSide : measOn ? paneSide || measSide : modelsOn ? paneSide || modelSide
    : missionsOn ? paneSide : paneSide || (phone ? null : summary);

  // The tree's quiet last row: a new position (or location) at the top level.
  // Inside a pinned branch, or one tree on show (a product's structure, an
  // item's tree), it goes inside that branch's top instead.
  const addRow = (() => {
    if (!data || nothing || !showsAddRow(tab)) return null; // the Summary tab only, as New … inside in a row's menu
    if (mode === "classes") return null; // a class's rows come from what's fitted: positions are added by Positions
    const kind = mode === "locations" ? "location" : "position";
    const top = pinKey || root;
    let parent = TOP;
    let label = `New ${kind}`;
    if (!pinKey && kind === "location" && data.scope?.kind === "design") {
      // A product's page, by Locations: a new location at the top of its layout.
      label = `New location inside ${data.scope.name || "(no name)"}`;
    } else if (root && !pinKey && kind === "location" && data.scope?.kind !== "place") {
      return null; // an item's tree: its locations come from its product (add inside one of them)
    } else if (!pinKey && kind === "position" && data.scope?.kind === "place") {
      // One place open on its own: a new top position is at that place (so it's in this asset).
      return {
        label: `New position at ${data.scope.name || "(no name)"}`, disabled: !!viewOnly, reason: viewOnly,
        onAdd: () => { setNewParent(TOP); setNewAt(data.scope.id); setModal("position"); },
      };
    } else if (top) {
      const r = whole.rows.get(top);
      if (!r || r.type !== (kind === "location" ? "loc" : "pos")) return null;
      parent = top;
      label = `New ${kind} inside ${r.ref.name || "(no name)"}`;
    }
    return {
      label, disabled: !!viewOnly, reason: viewOnly,
      onAdd: () => { setNewParent(parent); setModal(kind); },
    };
  })();

  return (
    <div ref={frame} className={"tx" + (phone ? " phone" : "") + (phone && (detailKey || sheetSide) && !tableOn ? " show-detail" : "")
      + (full ? " is-full" : "") + (tableOn ? " tx-table" : "")}>
      <TreePane
        title={title}
        // On a phone the tree is the page until a row's details take its place: its title is
        // the page's h1 then (on a wide screen the picked row's name in the panel is).
        titleLevel={phone && heading === 1 && !(detailKey && !tableOn) ? 1 : 2}
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
        design={designScope}
        mode={mode}
        onMode={onMode}
        focus={focus}
        onPick={pickRow}
        onToggle={toggle}
        onLevel={setLevel}
        onCloseAll={() => {
          setLevelBy((l) => ({ ...l, [mode]: 0 }));
          setOpenSet(new Set());
        }}
        phone={phone}
        width={shownWidth}
        onWidth={onWidth}
        collapsed={collapsed}
        onCollapse={setCollapsed}
        addRow={addRow}
        canArrange={!root || !!data?.scope}
        // One tree on show: an asset's has all three; a product's design, Positions and Locations.
        arrangements={root ? scopedArrangements(scopedClasses) : null}
        level={level}
        changed={changed}
        onReset={resetView}
        // Excel in and out: the asset opened (never a product's design). An asset that's a
        // position exports as its branch; one that's a place exports a branch from a row's ⋯ menu.
        menuActions={[...(data && (!root || assetTree) && mode !== "locations" ? [
          { id: "tree-import", label: "Import from Excel…", onSelect: () => openSheet("import") },
          ...(!root || unitBranch ? [{ id: "tree-export", label: "Export to Excel…", onSelect: () => openSheet("export", unitBranch) }] : []),
          { id: "import", label: "Import a fitment history…", onSelect: () => setModal("import") },
        ] : []), ]}
        notice={notice}
        statusText={statusText}
        empty={phone && (error || nothing) ? emptyDetail : paneEmpty}
        scrollTo={scrollTo}
        onEnter={(key) => {
          const r = display.rows.get(key);
          if (isMeasRow(r)) return openMeas(key);
          if (isModelRow(r)) return openModel(key);
          if (isMissionRow(r)) return openMissionRow(r);
          if (isRcmRow(r)) {
            setPanel(true);
            return setTimeout(() => detailsHeading.current?.focus(), 0);
          }
          return phone ? pick(key, { go: true }) : headingRef.current?.focus();
        }}
        // The ○ "not analysed" markers are the RCM's: on its tab (or with the
        // Not analysed chip on), never beside the FME(C)A's scores.
        rcmMarks={tab === "rcm" || chips.includes("unanalysed")}
        table={table}
        rowMenu={rowMenu}
        fullScreenKey={!phone}
        head={head}
        headTabs={headTabs}
        side={side}
        phoneTabs={phoneTabs}
        // The row picked stays where it is on screen when the tab changes, and
        // when the RCM's rows first arrive.
        layoutKey={`${tab}:${rcmOn && rcm ? "rcm" : measOn && meas.data ? "meas" : modelsOn && pmodels.links ? "models" : missionsOn && pmissions.links ? "missions" : ""}`}
        anchorKey={selPos}
        branch={pinKey ? {
          key: pinKey, name: whole.rows.get(pinKey).ref.name || "(no name)", path: pinPath(whole, pinKey), onUnpin: () => unpin(),
        } : null}
        branchNote={pinNote}
        arrangeLocked={measOn ? "Measurements hang under their positions, so the Measurements tab shows the positions tree"
          : modelsOn ? "Models hang under their positions, so the Modelling tab shows the positions tree"
          : missionsOn ? "Missions belong to positions, so the Missions tab shows the positions tree"
          : rcmOn ? `${what} is by position, so the ${what} tab shows the positions tree` : null}
      />
      {phone && (sheetSide || (paneSide ? null : summary))}
      <div className="sr-only" role="status" aria-live="polite">{spoken}</div>
      {drag && (
        <div className={"rcm-ghost" + (drag.verdict ? ` is-${drag.verdict.state}` : "")} aria-hidden="true"
             style={{ left: Math.min(drag.x + 16, window.innerWidth - 320), top: drag.y + 18 }}>
          <span className="rcm-ghost-what">
            {drag.src.kind === "modes" && drag.src.keys.length > 1 && <span className="rcm-ghost-n">{drag.src.keys.length}</span>}
            {/* A task's row is copied (linked to another failure mode too): a + badge, and "Link here". */}
            {drag.src.kind === "copy" && <span className="rcm-ghost-n rcm-ghost-plus" aria-hidden="true">+</span>}
            {/* "The performance standard “…” and its 3 functional failures": a label, so a capital first. */}
            {String(drag.words || "").replace(/^\p{Ll}/u, (c) => c.toUpperCase())}
          </span>
          {drag.verdict && (
            <span className="rcm-ghost-say">
              {drag.verdict.state === "no" ? `Can't go here: ${drag.verdict.text}` : String(drag.verdict.text || "").replace(/\.?$/, ".")}
              {drag.verdict.state === "checking" ? " Checking…" : ""}
              {drag.verdict.notes?.length ? ` ${drag.verdict.notes.join(" ")}` : ""}
            </span>
          )}
        </div>
      )}
      {toast && (
        <div className={"rcm-toast" + (toast.tone === "error" ? " error" : "")}>
          <span>{toast.text}</span>
          {(toast.undo?.length > 0 || (toast.restore && !toast.undo)) && (
            <button type="button" className="secondary sm" onClick={undoMove} disabled={toast.busy}
                    title="Undo (Ctrl+Z or Cmd+Z)">{toast.busy ? "Undoing…" : "Undo"}</button>
          )}
          <button type="button" className="rcm-toast-x" onClick={() => setToast(null)} aria-label="Dismiss">✕</button>
        </div>
      )}
      {modelModal?.kind === "library" && (
        <LibraryAttachModal position={modelModal.position} onClose={() => setModelModal(null)}
                            onDone={(made, text) => { setModelModal(null); say(text); pmodels.load(); }}
                            onBind={(rec) => {
                              // A record with covariates (NSWC-11's conditions, a pipe's length, the clock,
                              // the demands a year, a handbook part's environment...): which are fixed
                              // here, in the table area; the rest are set in the RBD.
                              const p = modelModal.position;
                              setModelModal(null);
                              openBind(p, bindingForRecord(rec), { name: rec.label });
                            }} />
      )}
      {modelModal?.kind === "to-library" && modelModal.link && (
        <AddToLibraryDialog modelId={modelModal.link.model_id} modelName={modelModal.link.model?.name || modelModal.link.name || "this model"}
                            onClose={() => setModelModal(null)} />
      )}
      {modelModal?.kind === "params" && (
        <ParamsModal position={modelModal.position} link={modelModal.link || null} onClose={() => setModelModal(null)}
                     onDone={(made, text) => { setModelModal(null); say(text); pmodels.load(); }} />
      )}
      {modelModal?.kind === "rbd-link" && (
        <RbdLinkModal position={modelModal.position} onClose={() => setModelModal(null)}
                      onDone={(made, text) => {
                        const position = modelModal.position;
                        setModelModal(null);
                        say(text);
                        pmodels.load();
                        // Linked: it opens in the table area.
                        openRbd(position, made.model_id);
                      }} />
      )}
      {modelModal?.kind === "rbd-new" && (
        <NewRbdModal position={modelModal.position} hasInside={modelModal.hasInside} hasModel={modelModal.hasModel}
                     onClose={() => setModelModal(null)}
                     onDone={(made, text) => {
                       const position = modelModal.position;
                       setModelModal(null);
                       say(text);
                       pmodels.load();
                       openRbd(position, made.model_id);
                     }} />
      )}
      <ModelDialogs modal={["rbd-link", "rbd-new", "params", "library", "to-library"].includes(modelModal?.kind) ? null : modelModal} onClose={() => setModelModal(null)}
                    onDone={(made, text) => { setModelModal(null); say(text); pmodels.load(); }} />
      <MeasDialogs modal={measModal} onClose={() => setMeasModal(null)} onSaid={(text) => say(text)}
                   onDone={() => { setMeasModal(null); meas.load(); }} />
      {moving && (moving.src || moving.taskFrom) && (
        <RcmMoveModal whole={whole} src={moving.src || null} taskFrom={moving.taskFrom || null} check={checkMove}
                      onApply={applyMove} onClose={() => setMoving(null)} />
      )}
      {measuring && <MeasurementMoveModal key={`${measuring.need.op_index}:${(measuring.need.tasks || []).map((t) => t.task_id).join(",")}`} need={measuring.need} onChoose={measuring.choose} onCancel={measuring.cancel} />}

      {modal === "position" && (
        <NewPositionModal positions={pickerList(data)}
                          parentId={newParent === TOP ? null : newParent ?? (selPos && display.rows.get(selPos)?.type === "pos" ? selPos : null)}
                          locations={data?.scope?.kind === "design" ? null : data?.locations || null}
                          locationId={newAt ?? (newParent == null && mode === "locations" && display.rows.get(selPos)?.type === "loc" ? selPos
                            // One place open on its own: a new position with no parent is at that place (else it'd be in no asset on show).
                            : (newParent == null || newParent === TOP) && data?.scope?.kind === "place" ? data.scope.id : null)}
                          onClose={closeModal} onCreated={(p) => created(p.id)} />
      )}
      {modal === "location" && (
        <NewLocationModal
          designOf={data?.scope?.kind === "design" ? data.scope.id : null} layoutName={data?.scope?.name}
          locations={(data?.locations || []).map((l) => ({ ...l, parent: l.parent_id ? { name: data.locations.find((x) => x.id === l.parent_id)?.name } : null }))}
          parentId={newParent === TOP ? (data?.scope?.kind === "place" ? data.scope.id : null)
            : newParent ?? (focus && display.rows.get(focus)?.type === "loc" ? focus : data?.scope?.kind === "place" ? data.scope.id : null)}
          onClose={closeModal} onDone={(l) => created(l.id)} />
      )}
      {modal === "import" && <ImportModal onClose={() => setModal(null)} onDone={() => { setModal(null); load(); }} />}
      {rowModal?.kind === "rename" && (
        <RenameModal row={rowModal.row} onClose={() => setRowModal(null)}
                     onDone={(name) => rowChanged(rowModal.row, { text: `Renamed it “${name}”.` })} />
      )}
      {rowModal?.kind === "move" && (
        <MoveModal row={rowModal.row} targets={targetsFor(rowModal.row)} parentId={rowModal.row.ref.parent_id || null}
                   topLabel={rowModal.row.type === "loc" && data?.scope ? `Top of ${data.scope.name || "its"} layout` : null}
                   onClose={() => setRowModal(null)}
                   onDone={(to) => rowChanged(rowModal.row, { text: to ? `Moved it inside “${to}”.` : "Moved it to the top level." })} />
      )}
      {rowModal?.kind === "delete" && (
        <DeleteTreeModal kind={DELETE_KIND[rowModal.row.type]} id={rowModal.row.key} name={rowModal.row.ref.name}
                         onClose={() => setRowModal(null)}
                         onDone={(answer, done) => {
                           // The tree read again, the row it was inside picked, and the toast with Undo.
                           const row = rowModal.row;
                           setRowModal(null);
                           // The tree's own top (a product's design, or a tree opened on its own): nothing left
                           // to show here, so Products (or the Assets list) shows the toast.
                           if (root && row.key === root) {
                             navigate(rootProp ? PRODUCTS_PATH : ASSETS_LIST_PATH, { state: { deleted: done } });
                             return;
                           }
                           const up = row.ref.parent_id && display.rows.has(row.ref.parent_id) ? row.ref.parent_id : null;
                           if (up != null) pending.current = up;
                           if (rcmOn) loadRcm();
                           load();
                           setToast({ text: done.text, restore: { kind: done.kind, id: done.id, name: done.name }, at: Date.now() });
                           announce(`${done.text} Press Control Z to undo.`);
                           if (up != null) setTimeout(() => document.getElementById(`tp-${up}`)?.focus({ preventScroll: true }), 300);
                         }} />
      )}
      {rowModal?.kind === "rcm-delete" && (
        <DeleteRcmModal kind={RCM_DELETE_KIND[rowModal.row.type]} id={rcmDeleteId(rowModal.row)}
                        name={rowModal.row.ref.text} onClose={() => setRowModal(null)}
                        onDone={(answer, done) => {
                          // The RCM and the tree read again, the row it was under picked, and the toast with Undo.
                          const row = rowModal.row;
                          setRowModal(null);
                          setRcmFocus(isRcmRow(display.rows.get(row.parent)) ? row.parent : null);
                          Promise.resolve(loadRcm()).then(() => load());
                          setToast({ text: done.text, restore: { rcm: true, id: done.id, name: done.name, focus: row.key }, at: Date.now() });
                          announce(`${done.text} Press Control Z to undo.`);
                        }} />
      )}
      {reportFor && (
        <NewFailureReportModal positionId={reportFor.id} positionName={reportFor.name} today={data?.today || ""}
                               onClose={() => setReportFor(null)} onDone={reportFiled} />
      )}
      {eventFor && (
        <LogEventModal positionId={eventFor.id} positionName={eventFor.name} today={data?.today || ""}
                       onClose={() => setEventFor(null)} onDone={eventLogged} />
      )}
      {buildFor && <BuildItemModal product={buildFor} onClose={() => setBuildFor(null)} onDone={built} />}
      {sheetFor && <RcmImportModal position={sheetFor} onClose={() => setSheetFor(null)} onImported={sheetImported} />}
      {assigning && (
        // A "No functional failure yet" row's modes, under one of the function's functional failures.
        <AssignFailureModal row={assigning} failures={fmeaFailuresOn(rcm, assigning.ref.position_id).filter((f) => f.function_id === assigning.ref.function_id)}
                            onClose={() => setAssigning(null)}
                            onAssign={async (ffId) => {
                              const ids = assigning.ref.mode_ids || [];
                              await ops.assignMany(ids, ffId);
                              setAssigning(null);
                              setRcmFocus(ffId);
                              say(`Assigned ${ids.length === 1 ? "the failure mode" : `${ids.length} failure modes`} to the functional failure.`);
                            }} />
      )}
      {linking && (
        <LinkFailurePicker direction={linking.direction} row={linking.row} whole={whole} onLink={ops.linkMany}
                           onClose={(n) => {
                             setLinking(null);
                             if (n) say(`Linked ${n} ${linking.direction === "cause" ? (n === 1 ? "cause" : "causes") : (n === 1 ? "effect" : "effects")}.`);
                           }} />
      )}
      {deciding && options && (
        <DecisionModal options={options} mode={deciding.ref} onSave={saveDecision} onClose={() => setDeciding(null)} limits
                       workings={workingsFor(rcm, deciding.ref.id)} loadTasks={loadDecisionTasks} />
      )}
    </div>
  );
}

// A position's own evidence checks, for its heading on the RCM tab.
// The position's evidence counts for the header: the server's rollup (it and what's inside
// it), else (a position with no RCM of its own, so not in the read) its row's in the tree.
function rollupOf(rcm, positionId, whole = null) {
  const server = (rcm.positions || []).find((p) => p.id === positionId)?.rollup;
  if (server) return server;
  const s = whole?.rows?.get(positionId)?.rsum;
  return s ? { supported: s.supported || 0, contradicted: s.contradicted || 0, inconclusive: s.unsure || 0, stale: s.stale || 0 } : null;
}

// Is the window narrower than NARROW_TABLE (fewer usual columns in the RCM
// table)? Follows the window as it changes.
const NARROW_QUERY = `(max-width: ${NARROW_TABLE - 1}px)`;
function useNarrowTable() {
  const [narrow, setNarrow] = useState(() => window.matchMedia(NARROW_QUERY).matches);
  useEffect(() => {
    const mq = window.matchMedia(NARROW_QUERY);
    const onChange = () => setNarrow(mq.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);
  return narrow;
}

// Is the window at least WIDE_TABLE (the FME(C)A's whole preset of usual
// columns fits beside the tree)? Follows the window as it changes.
const WIDE_QUERY = `(min-width: ${WIDE_TABLE}px)`;
function useWideTable() {
  const [wide, setWide] = useState(() => window.matchMedia(WIDE_QUERY).matches);
  useEffect(() => {
    const mq = window.matchMedia(WIDE_QUERY);
    const onChange = () => setWide(mq.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);
  return wide;
}
