import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { ReactFlowProvider } from "reactflow";
import "reactflow/dist/style.css";
import {
  analyseFaultTree, deleteFaultTree, downloadFaultTreeOpenPsa, faultTreeToRbd, getFaultTree, saveFaultTree,
} from "../api.js";
import PageHeader from "../components/ui/PageHeader.jsx";
import Chip from "../components/ui/Chip.jsx";
import SegmentedControl from "../components/ui/SegmentedControl.jsx";
import ModelPicker from "../components/ModelPicker.jsx";
import Plot from "../components/Plot.jsx";
import LoadFailed from "../components/LoadFailed.jsx";
import { PageTitle } from "../components/usePageTitle.js";
import { CutSetTable, ImportanceTable, TreeCanvas } from "../components/RbdFaultTree.jsx";
import { useAskText, useConfirm } from "../components/ConfirmProvider.jsx";
import { changedText, deleteOrRemoveConfirm, renamePrompt } from "../confirm.js";
import useMenuDismiss from "../components/useMenuDismiss.js";
import { fitLine } from "../plotTheme.js";
import { formatNumber } from "../format.js";
import { itemName } from "../components/LibRows.jsx";
import { FAULT_TREES_PATH, FAULT_TREES_TITLE, RBDS_PATH, SYSTEM_MODELS_LABEL } from "../navigation.js";
import {
  GATE_LABELS, GATE_WORDS, addChild, emptyTree, eventSummary, gateSummary, indentRow, moveRow, nodeOf,
  outdentRow, outlineRows, removeRow, rename, setEventData, setGate, treeIssues,
} from "../faultTree.js";
import "../components/RbdFaultTree.css";
import "./FaultTree.css";

const DotsIcon = () => (
  <svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor" aria-hidden="true">
    <circle cx="5" cy="12" r="1.8" /><circle cx="12" cy="12" r="1.8" /><circle cx="19" cy="12" r="1.8" />
  </svg>
);

// The row's own menu (its ⋯ button, or a right-click on the row).
function RowMenu({ open, onOpen, onClose, label, children }) {
  const ref = useRef(null);
  useMenuDismiss(open, onClose, ref);
  return (
    <div className="ovm ft-row-menu" ref={ref}>
      <button type="button" className="ghost sm ft-row-dots" aria-haspopup="menu" aria-expanded={open}
              aria-label={`Actions for ${label}`} title="Actions" onClick={(e) => { e.stopPropagation(); open ? onClose() : onOpen(); }}>
        <DotsIcon />
      </button>
      <div className="ovm-menu" role="menu" hidden={!open} onClick={(e) => { e.stopPropagation(); onClose(); }}>
        {children}
      </div>
    </div>
  );
}

function GateMark({ node }) {
  const text = node.gate === "vote" ? `${node.k}/${(node.inputs || []).length}` : GATE_LABELS[node.gate];
  return <span className={`ft-mark ft-mark-${node.gate}`} aria-hidden="true">{text}</span>;
}

// One outline row: indent, mark, name, a one-line summary, and its menu.
function OutlineRow({ row, selected, issue, menuOpen, onSelect, onMenu, onCloseMenu, actions }) {
  const { node } = row;
  const gate = node.type === "gate";
  return (
    <li
      className={"ft-row" + (selected ? " selected" : "") + (gate ? " gate" : " event")}
      style={{ "--depth": row.depth }}
      onContextMenu={(e) => { e.preventDefault(); onSelect(); onMenu(); }}
    >
      <button type="button" className="ft-row-main" onClick={onSelect} aria-current={selected ? "true" : undefined}>
        {gate ? <GateMark node={node} /> : <span className="ft-mark ft-mark-event" aria-hidden="true" />}
        <span className="ft-row-text">
          <span className="ft-row-label">{node.label}{row.depth === 0 && <span className="ft-row-top"> · top event</span>}</span>
          <span className="ft-row-sub">
            {gate ? gateSummary(node) : eventSummary(node, actions.unit)}
            {row.repeated && !gate && " · repeated"}
          </span>
        </span>
        {node.placeholder && <Chip title="Guessed data: replace before relying on the results">Placeholder</Chip>}
        {issue && <span className="ft-issue" title={issue}>!</span>}
      </button>
      {!actions.readOnlyRows && (
        <RowMenu open={menuOpen} onOpen={onMenu} onClose={onCloseMenu} label={node.label}>
          {gate && <button className="ovm-item" role="menuitem" onClick={() => actions.add(row, "gate")}>Add gate</button>}
          {gate && <button className="ovm-item" role="menuitem" onClick={() => actions.add(row, "event")}>Add basic event</button>}
          {gate && ["or", "and", "vote"].filter((g) => g !== node.gate).map((g) => (
            <button key={g} className="ovm-item" role="menuitem" onClick={() => actions.gate(row, g)}>
              Change to {GATE_LABELS[g]}
            </button>
          ))}
          <button className="ovm-item" role="menuitem" onClick={() => actions.rename(row)}>Rename</button>
          {row.parent && (
            <>
              <button className="ovm-item" role="menuitem" disabled={row.index === 0} onClick={() => actions.move(row, -1)}>Move up</button>
              <button className="ovm-item" role="menuitem" disabled={row.last} onClick={() => actions.move(row, 1)}>Move down</button>
              <button className="ovm-item" role="menuitem" onClick={() => actions.indent(row)}>Move into the gate above</button>
              <button className="ovm-item" role="menuitem" onClick={() => actions.outdent(row)}>Move out of this gate</button>
              <button className="ovm-item danger" role="menuitem" onClick={() => actions.remove(row)}>Delete</button>
            </>
          )}
        </RowMenu>
      )}
    </li>
  );
}

// The selected gate's or basic event's own fields.
function NodePanel({ tree, node, unit, onChange, onAdd, readOnly }) {
  const [source, setSource] = useState(node.type === "event" ? (node.probability != null ? "fixed" : node.model ? "model" : "none") : null);
  useEffect(() => {
    if (node.type === "event") setSource(node.probability != null ? "fixed" : node.model ? "model" : "none");
    // A new selection starts from its own data; edits to it keep the choice.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [node.id]);
  const [qText, setQText] = useState(node.probability != null ? String(node.probability) : "");
  useEffect(() => setQText(node.probability != null ? String(node.probability) : ""), [node.id, node.probability]);
  const q = Number(qText);
  const qBad = qText !== "" && !(Number.isFinite(q) && q >= 0 && q <= 1);

  if (node.type === "gate") {
    const n = (node.inputs || []).length;
    return (
      <div className="card ft-panel">
        <label className="ft-field">
          <span>Name</span>
          <input value={node.label} disabled={readOnly} maxLength={120}
                 onChange={(e) => onChange(rename(tree, node.id, e.target.value))} />
        </label>
        <div className="ft-field">
          <span>Gate</span>
          <SegmentedControl label="Gate type" size="sm" value={node.gate}
            options={["or", "and", "vote"].map((g) => ({ value: g, label: GATE_LABELS[g], title: GATE_WORDS[g], disabled: readOnly }))}
            onChange={(g) => onChange(setGate(tree, node.id, g, node.k ?? Math.min(2, Math.max(n, 1))))} />
          <p className="hint">{GATE_WORDS[node.gate].replace("k", node.k ?? "k")}.</p>
        </div>
        {node.gate === "vote" && (
          <label className="ft-field ft-k">
            <span>Occurs when at least</span>
            <input type="number" min="1" max={Math.max(n, 1)} step="1" inputMode="numeric" disabled={readOnly}
                   value={node.k ?? ""} onChange={(e) => onChange(setGate(tree, node.id, "vote", e.target.value))} />
            <span>of its {n} input{n === 1 ? "" : "s"} occur</span>
          </label>
        )}
        {!readOnly && (
          <div className="ft-panel-actions">
            <button type="button" className="secondary sm" onClick={() => onAdd(node.id, "gate")}>Add gate</button>
            <button type="button" className="secondary sm" onClick={() => onAdd(node.id, "event")}>Add basic event</button>
          </div>
        )}
      </div>
    );
  }

  const setData = (data) => onChange(setEventData(tree, node.id, { placeholder: node.placeholder, ...data }));
  return (
    <div className="card ft-panel">
      <label className="ft-field">
        <span>Name</span>
        <input value={node.label} disabled={readOnly} maxLength={120}
               onChange={(e) => onChange(rename(tree, node.id, e.target.value))} />
      </label>
      <div className="ft-field">
        <span>Failure data</span>
        <SegmentedControl label="Failure data" size="sm" value={source}
          options={[
            { value: "model", label: "Life model", title: "A saved model, a failure rate or Weibull parameters", disabled: readOnly },
            { value: "fixed", label: "Fixed probability", title: "A probability that doesn't change with time (an unavailability q)", disabled: readOnly },
            { value: "none", label: "Not yet", disabled: readOnly },
          ]}
          onChange={(v) => {
            setSource(v);
            if (v === "none") setData({});
            if (v === "fixed" && qText !== "" && !qBad) setData({ probability: q });
          }} />
      </div>
      {source === "model" && (
        <fieldset disabled={readOnly} className="ft-plain">
          <ModelPicker key={node.id} value={node.model || null} rbdBlock meanEntry="Mean life (MTBF)" unit={unit}
                       onChange={(m) => { if (m) setData({ model: m }); }} />
        </fieldset>
      )}
      {source === "fixed" && (
        <label className="ft-field">
          <span>Probability it has occurred (q, 0 to 1)</span>
          <input type="number" inputMode="decimal" min="0" max="1" step="any" value={qText} disabled={readOnly}
                 aria-invalid={qBad || undefined}
                 onChange={(e) => {
                   setQText(e.target.value);
                   const v = Number(e.target.value);
                   if (e.target.value !== "" && Number.isFinite(v) && v >= 0 && v <= 1) setData({ probability: v });
                 }} />
          {qBad && <span className="field-error" role="alert">Enter a probability between 0 and 1.</span>}
          <span className="hint">The same at every time: a demand failure or an unavailability.</span>
        </label>
      )}
      {source === "none" && <p className="hint">Set its data before analysing: a model, a rate or a probability. A guess is fine if you mark it.</p>}
      {source !== "none" && (
        <label className="ft-check">
          <input type="checkbox" checked={!!node.placeholder} disabled={readOnly}
                 onChange={(e) => onChange(setEventData(tree, node.id, { model: node.model, probability: node.probability, placeholder: e.target.checked }))} />
          <span>This is a guess (placeholder): flag it on every result until it's replaced</span>
        </label>
      )}
    </div>
  );
}

function TopCurve({ result }) {
  const c = result.curve;
  if (!c) return null;
  const u = result.unit ? ` ${result.unit}` : "";
  return (
    <div className="ft-section">
      <div className="rbd-section-head">Top event probability over time</div>
      <Plot
        download="Top event probability"
        data={[fitLine({ x: c.t, y: c.probability, name: "F(t)", hovertemplate: `t = %{x:,.4~g}${u}<br>F(t) = %{y:.3~g}<extra></extra>` })]}
        layout={{
          height: 260, showlegend: false,
          xaxis: { title: { text: `Time${result.unit ? ` (${result.unit})` : ""}` } },
          yaxis: { title: { text: "Probability" }, rangemode: "tozero" },
          shapes: result.t != null ? [{ type: "line", x0: result.t, x1: result.t, yref: "paper", y0: 0, y1: 1, line: { dash: "dot", width: 1 } }] : [],
        }}
      />
    </div>
  );
}

// System models › Fault trees › one tree: the outline editor, the selected
// node's fields, and the analysis (top event, drawn tree, cut sets, importance).
export default function FaultTreeEditor() {
  const { id: routeId } = useParams();
  const isNew = !routeId || routeId === "new";
  const navigate = useNavigate();
  const location = useLocation();
  const imported = isNew ? location.state?.imported : null;
  const confirm = useConfirm();
  const askText = useAskText();

  const [doc, setDoc] = useState(null); // the saved summary: {id, name, updated_at, read_only, is_sample, rbd_id}
  const [name, setName] = useState(imported?.name || "Untitled fault tree");
  const [tree, setTree] = useState(() => imported?.tree || emptyTree());
  const [notes, setNotes] = useState(imported?.notes || []);
  const [dirty, setDirty] = useState(!!imported);
  const [loadError, setLoadError] = useState(null);
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);
  const [selected, setSelected] = useState(null); // a row key
  const [menuKey, setMenuKey] = useState(null);
  const [result, setResult] = useState(null);
  const [analysis, setAnalysis] = useState({ phase: "idle", error: null, sig: null });
  const [tInput, setTInput] = useState("");
  const [rbdNotes, setRbdNotes] = useState(null);

  useEffect(() => {
    if (isNew) return;
    setLoadError(null);
    getFaultTree(routeId)
      .then((d) => {
        setDoc(d);
        setName(d.name);
        setTree(d.tree);
        setDirty(false);
        setNotes([]);
        setSelected(null);
      })
      .catch((e) => setLoadError(e));
  }, [routeId, isNew]);

  const readOnly = !!doc?.read_only; // a sample: edits are kept by "Save a copy"
  const rows = useMemo(() => outlineRows(tree), [tree]);
  const issues = useMemo(() => treeIssues(tree), [tree]);
  const issueOf = useMemo(() => Object.fromEntries(issues.map((i) => [i.id, i.text])), [issues]);
  const selRow = rows.find((r) => r.key === selected) || rows[0];
  const selNode = selRow ? nodeOf(tree, selRow.id) : null;
  const sig = useMemo(() => JSON.stringify(tree), [tree]);

  const edit = (next) => {
    setTree(next);
    setDirty(true);
  };

  // Analyse whenever the tree is complete and has changed (a short pause after typing).
  const runAnalysis = useCallback(async (t) => {
    setAnalysis((a) => ({ ...a, phase: "loading", error: null }));
    try {
      const res = await analyseFaultTree(tree, t === "" || t == null ? null : Number(t));
      setResult(res);
      setAnalysis({ phase: "idle", error: null, sig });
    } catch (err) {
      setResult(null);
      setAnalysis({ phase: "error", error: err.message, sig });
    }
  }, [tree, sig]);
  useEffect(() => {
    if (issues.length || analysis.sig === sig) return undefined;
    const timer = setTimeout(() => runAnalysis(tInput), 500);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sig, issues.length]);

  const actions = {
    unit: tree.unit,
    readOnlyRows: false,
    add: (row, type) => {
      const { tree: next, id } = addChild(tree, row.id, type);
      edit(next);
      setSelected(`${row.key}/${id}`);
    },
    gate: (row, g) => edit(setGate(tree, row.id, g, row.node.k ?? 2)),
    rename: async (row) => {
      const label = changedText(await askText({ title: "Rename", label: "Name", value: row.node.label, confirmLabel: "Rename" }), row.node.label);
      if (label) edit(rename(tree, row.id, label));
    },
    move: (row, dir) => {
      edit(moveRow(tree, row, dir));
      const parentKey = row.key.slice(0, row.key.lastIndexOf("/"));
      setSelected(`${parentKey}/${row.id}`);
    },
    indent: (row) => {
      const next = indentRow(tree, row);
      if (!next) return setError("There's no gate just above it to move it into.");
      setError(null);
      edit(next);
    },
    outdent: (row) => {
      const next = outdentRow(tree, rows, row);
      if (!next) return setError("It's already directly under the top event.");
      setError(null);
      edit(next);
    },
    remove: async (row) => {
      const below = (row.node.inputs || []).length;
      if (below && !(await confirm({
        title: `Delete “${row.node.label}”?`,
        body: "Its whole branch goes with it (a basic event used elsewhere in the tree stays there).",
        confirmLabel: "Delete branch", destructive: true,
      }))) return;
      edit(removeRow(tree, row));
      setSelected(null);
    },
  };

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      const copy = readOnly || !doc;
      const saved = await saveFaultTree(copy && readOnly ? `${itemName(doc)} (copy)` : name, tree,
        copy ? null : doc.id, copy ? null : doc.updated_at);
      setDoc(saved);
      setName(saved.name);
      setTree(saved.tree);
      setDirty(false);
      if (copy) navigate(`${FAULT_TREES_PATH}/${saved.id}`, { replace: !readOnly });
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  };

  const onRename = async () => {
    const next = changedText(await askText(renamePrompt({ kind: "fault tree", name })), name);
    if (next) {
      setName(next);
      setDirty(true);
    }
  };

  const onOpenRbd = async () => {
    setError(null);
    try {
      const made = await faultTreeToRbd(doc.id);
      setRbdNotes(made);
      setDoc((d) => ({ ...d, rbd_id: d.read_only ? d.rbd_id : made.rbd_id }));
    } catch (err) {
      setError(err.message);
    }
  };

  const onDelete = async () => {
    if (!(await confirm(deleteOrRemoveConfirm(doc, "fault tree", { name: itemName(doc) })))) return;
    try {
      await deleteFaultTree(doc.id);
      navigate(FAULT_TREES_PATH);
    } catch (err) {
      setError(err.message);
    }
  };

  const crumbs = [{ label: SYSTEM_MODELS_LABEL, to: RBDS_PATH }, { label: FAULT_TREES_TITLE, to: FAULT_TREES_PATH }];
  if (loadError) {
    return (
      <div className="app">
        <PageHeader crumbs={crumbs} title="Fault tree" />
        <LoadFailed error={loadError} to={FAULT_TREES_PATH} label="See all fault trees" />
      </div>
    );
  }
  if (!isNew && !doc) {
    return (
      <div className="app">
        <PageHeader crumbs={crumbs} title="Fault tree" />
        <div className="card empty">Loading…</div>
      </div>
    );
  }

  const nGates = tree.nodes.filter((n) => n.type === "gate").length;
  const nEvents = tree.nodes.length - nGates;
  const timed = result?.kind === "reliability";
  const stale = result && analysis.sig !== sig;
  const u = result?.unit ? ` ${result.unit}` : "";

  return (
    <div className="app ft-editor">
      <PageTitle name={doc ? itemName(doc) : name} />
      <PageHeader
        crumbs={crumbs}
        title={doc ? itemName({ ...doc, name }) : name}
        id={doc?.id}
        badges={<>
          {doc?.is_sample && <Chip>Sample</Chip>}
          {(dirty || !doc) && <Chip title="Changes not saved yet">Unsaved</Chip>}
        </>}
        meta={`${nGates} gate${nGates === 1 ? "" : "s"} · ${nEvents} basic event${nEvents === 1 ? "" : "s"}${tree.unit ? ` · ${tree.unit}` : ""}`}
        primary={
          <button onClick={save} disabled={saving || (!dirty && !!doc && !readOnly)}>
            {saving ? "Saving…" : readOnly ? "Save a copy" : "Save"}
          </button>
        }
        actions={doc && (
          <button className="secondary" onClick={onOpenRbd} disabled={!!issues.length}
                  title={issues.length ? "Finish the tree first" : "Make an RBD from this tree (OR = series, AND = parallel)"}>
            Open as RBD
          </button>
        )}
        menu={<>
          {!readOnly && <button className="ovm-item" onClick={onRename}>Rename</button>}
          <button className="ovm-item" disabled={!!issues.length}
                  onClick={() => downloadFaultTreeOpenPsa(name, tree, result?.t ?? null).catch((e) => setError(e.message))}>
            Export Open-PSA XML
          </button>
          {doc && <button className="ovm-item danger" onClick={onDelete}>{doc.is_sample ? "Hide this sample" : "Delete"}</button>}
        </>}
      >
        {readOnly && <p className="hint ft-head-note">A shared sample: change anything you like, then <b>Save a copy</b> to keep it.</p>}
      </PageHeader>

      {notes.length > 0 && (
        <div className="card ft-notes">
          <b>Import notes</b>
          <ul>{notes.map((n, i) => <li key={i}>{n}</li>)}</ul>
        </div>
      )}
      {rbdNotes && (
        <div className="card ft-notes">
          <b>RBD saved: </b><a href={`/systems/b/${rbdNotes.rbd_id}`} onClick={(e) => { e.preventDefault(); navigate(`/systems/b/${rbdNotes.rbd_id}`); }}>{rbdNotes.name}</a>
          {rbdNotes.notes?.length > 0 && <ul>{rbdNotes.notes.map((n, i) => <li key={i}>{n}</li>)}</ul>}
        </div>
      )}
      {doc?.rbd_id && !rbdNotes && (
        <p className="hint">An RBD was made from this tree: <a href={`/systems/b/${doc.rbd_id}`} onClick={(e) => { e.preventDefault(); navigate(`/systems/b/${doc.rbd_id}`); }}>open it</a>. It doesn't follow later edits to the tree.</p>
      )}
      {error && <div className="card error" role="alert">{error}</div>}

      <div className="ft-layout">
        <section className="card ft-outline" aria-label="The tree">
          <div className="ft-outline-head">
            <b>The tree</b>
            <label className="ft-unit">
              <span>Time unit</span>
              <input value={tree.unit || ""} maxLength={40} placeholder="e.g. Hours"
                     onChange={(e) => edit({ ...tree, unit: e.target.value })} />
            </label>
          </div>
          <p className="hint">Select a row to edit it; its ⋯ menu (or a right-click) adds, moves and deletes.</p>
          <ul className="ft-rows" role="list">
            {rows.map((row) => (
              <OutlineRow key={row.key} row={row} selected={selRow?.key === row.key} issue={issueOf[row.id]}
                menuOpen={menuKey === row.key} onSelect={() => setSelected(row.key)}
                onMenu={() => setMenuKey(row.key)} onCloseMenu={() => setMenuKey(null)} actions={actions} />
            ))}
          </ul>
        </section>
        {selNode && (
          <section className="ft-side" aria-label="Selected">
            <NodePanel tree={tree} node={selNode} unit={tree.unit} onChange={edit} readOnly={false}
                       onAdd={(gid, type) => actions.add(selRow, type)} />
          </section>
        )}
      </div>

      <section className="ft-results" aria-label="Analysis">
        <h2>Top event</h2>
        {issues.length > 0 ? (
          <div className="card ft-todo">
            <b>To analyse, finish the tree:</b>
            <ul>{issues.slice(0, 8).map((i) => <li key={i.id}>{i.text}</li>)}</ul>
            {issues.length > 8 && <p className="hint">…and {issues.length - 8} more.</p>}
          </div>
        ) : (
          <>
            {analysis.error && <div className="card error">{analysis.error}</div>}
            {analysis.phase === "loading" && !result && <p className="muted-line">Working out the top event…</p>}
            {result && (
              <div className={stale ? "ft-stale" : undefined}>
                <div className="ft-head">
                  {timed && (
                    <form className="ft-controls" onSubmit={(e) => { e.preventDefault(); runAnalysis(tInput); }}>
                      <label className="calc-t">
                        <span>Evaluate at t{result.unit ? ` (${result.unit})` : ""}</span>
                        <input type="number" inputMode="decimal" min="0" step="any" value={tInput}
                               placeholder={result.t_default != null ? Number(result.t_default.toPrecision(4)).toString() : "auto"}
                               onChange={(e) => setTInput(e.target.value)} />
                      </label>
                      <button type="submit" disabled={analysis.phase === "loading"}>
                        {analysis.phase === "loading" ? "Evaluating…" : "Evaluate"}
                      </button>
                    </form>
                  )}
                  <div className="stats ft-stats">
                    <div className="stat">
                      <div className="k">{timed ? `Top event probability by ${formatNumber(result.t)}${u}` : "Top event probability"}</div>
                      <div className="v">{formatNumber(result.top_event_probability)}</div>
                    </div>
                    <div className="stat">
                      <div className="k">{timed ? "Reliability R(t)" : "Probability it doesn't occur"}</div>
                      <div className="v">{formatNumber(result.top_event_probability == null ? null : 1 - result.top_event_probability, { sig: 5 })}</div>
                    </div>
                    <div className="stat">
                      <div className="k">Minimal cut sets</div>
                      <div className="v">{formatNumber(result.cut_sets.count)}</div>
                    </div>
                  </div>
                </div>
                <p className="muted-line ft-note">
                  {timed
                    ? result.t === result.t_default
                      ? "At the time the top event reaches about 10% (system reliability about 90%). "
                      : ""
                    : "Every basic event is a fixed probability, so time doesn't enter. "}
                  Exact, repeated events counted once.
                  {stale && " Updating…"}
                </p>
                {result.notes?.map((n, i) => <p key={i} className="muted-line warn">{n}</p>)}
                <TopCurve result={result} />
                <div className="ft-section">
                  <div className="rbd-section-head">The tree, drawn</div>
                  <ReactFlowProvider>
                    <TreeCanvas key={analysis.sig} result={result} name={name} active />
                  </ReactFlowProvider>
                </div>
                <CutSetTable result={result} />
                <ImportanceTable result={result} />
              </div>
            )}
          </>
        )}
      </section>
    </div>
  );
}
