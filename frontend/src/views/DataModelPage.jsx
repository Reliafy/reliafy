import { lazy, Suspense, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { SectionHeader } from "../components/SectionPage.jsx";
import { useAppConfig } from "../ConfigProvider.jsx";
import { getGraphDesign, getGraphSchema, getMaintenanceAccess } from "../api.js";
import {
  combine, connectionsOf, designModel, formatCount, liveModel, liveProblem, PROBLEM_TEXT, searchModel, stateText,
  tableRows, toArrows, VIEWS, WARN,
} from "../dataModel.js";
import "./DataModelPage.css";

// The diagram (and cytoscape.js with it) loads only when it's first shown.
const DataModelDiagram = lazy(() => import("../components/DataModelDiagram.jsx"));

const INTRO = "These are the kinds of things your maintenance graph holds and how they connect. "
  + "The numbers are how many of each you have.";
const NARROW = "(max-width: 600px)";

function download(name, href) {
  const a = document.createElement("a");
  a.href = href;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
}

// The Data model page (/data-model): the maintenance graph's kinds of thing
// and the connections between them, as a diagram or a table, for people with
// graph access. With a stored design, it also shows what's designed, and both
// together so the gaps stand out.
export default function DataModelPage() {
  const { maintenance: maintenanceOn } = useAppConfig();
  const [access, setAccess] = useState(null); // null: asking
  const [live, setLive] = useState({ state: "loading" });
  const [design, setDesign] = useState({ state: "loading" });

  useEffect(() => {
    if (!maintenanceOn) {
      setAccess(false);
      return undefined;
    }
    let alive = true;
    getMaintenanceAccess().then((a) => alive && setAccess(Boolean(a?.allowed && a?.graph)));
    return () => {
      alive = false;
    };
  }, [maintenanceOn]);

  useEffect(() => {
    if (!access) return undefined;
    let alive = true;
    getGraphSchema()
      .then((schema) => alive && setLive({ state: "ready", schema, model: liveModel(schema) }))
      .catch((err) => alive && setLive({ state: "problem", problem: liveProblem(err) }));
    getGraphDesign()
      .then((d) => alive && setDesign(d?.available
        ? { state: "ready", model: designModel(d), updated: d.updated || null }
        : { state: "none", reason: d?.reason || "No design has been stored yet." }))
      .catch(() => alive && setDesign({ state: "none", reason: "The design couldn't be read just now." }));
    return () => {
      alive = false;
    };
  }, [access]);

  const header = <SectionHeader title="Data model" purpose={INTRO} />;

  if (access === null) {
    return <div className="app">{header}<div className="card empty">Loading…</div></div>;
  }
  if (!access) {
    return (
      <div className="app">
        {header}
        <Empty title="Not available for your account">
          {maintenanceOn ? PROBLEM_TEXT["no-access"] : "Reliafy Maintenance isn't switched on here, so there is no maintenance graph to show."}
        </Empty>
      </div>
    );
  }
  if (live.state === "loading" || design.state === "loading") {
    return <div className="app">{header}<div className="card empty">Loading…</div></div>;
  }
  if (live.state !== "ready" && design.state !== "ready") {
    return (
      <div className="app">
        {header}
        <Empty title="Nothing to draw yet">{PROBLEM_TEXT[live.problem] || PROBLEM_TEXT.failed}</Empty>
      </div>
    );
  }
  return <DataModel header={header} live={live} design={design} />;
}

function Empty({ title, children }) {
  return (
    <div className="card empty section-empty dm-empty">
      <h2>{title}</h2>
      <p>{children}</p>
      <p className="section-empty-more"><Link to="/home">Back to Home</Link></p>
    </div>
  );
}

function DataModel({ header, live, design }) {
  const hasLive = live.state === "ready";
  const hasDesign = design.state === "ready";
  const [view, setView] = useState(hasLive ? "built" : "designed");
  const [display, setDisplay] = useState(() =>
    (typeof window !== "undefined" && window.matchMedia?.(NARROW).matches ? "table" : "diagram"));
  const [showCounts, setShowCounts] = useState(true);
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState(null);
  const diagram = useRef(null);

  const model = useMemo(
    () => combine(hasLive ? live.model : null, hasDesign ? design.model : null, view),
    [live, design, view, hasLive, hasDesign],
  );
  useEffect(() => setSelected(null), [view]);
  const highlight = useMemo(() => searchModel(model, query), [model, query]);
  // On a narrow screen the details sit below the diagram or table: bring them into view.
  useEffect(() => {
    if (!selected || !window.matchMedia?.("(max-width: 960px)").matches) return;
    document.querySelector(".dm-details")?.scrollIntoView?.({ behavior: "smooth", block: "nearest" });
  }, [selected]);
  const empty = model.nodes.length === 0;

  const available = (v) => (v === "built" ? hasLive : v === "designed" ? hasDesign : hasLive && hasDesign);
  const why = (v) => {
    if (available(v)) return undefined;
    if (v === "built") return PROBLEM_TEXT[live.problem] || PROBLEM_TEXT.failed;
    return design.reason || "No design has been stored yet.";
  };

  const pickSearch = (e) => {
    if (e.key !== "Enter" || !highlight) return;
    const nodes = [...highlight.nodes];
    if (highlight.edges.size === 1) setSelected({ kind: "edge", id: [...highlight.edges][0] });
    else if (nodes.length) setSelected({ kind: "node", id: nodes[0] });
  };

  const exportArrows = () => {
    const positions = display === "diagram" && diagram.current?.ready() ? diagram.current.positions() : {};
    const json = JSON.stringify(toArrows(model, positions, { showCounts }), null, 2);
    const url = URL.createObjectURL(new Blob([json], { type: "application/json" }));
    download(`data-model-${view}.json`, url);
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  const exportPng = () => {
    const png = diagram.current?.png();
    if (png) download(`data-model-${view}.png`, png);
  };

  const fresh = hasLive ? live.schema?.freshness : null;
  const viewNote = view === "designed" && !hasLive
    ? "Showing the design only: " + (PROBLEM_TEXT[live.problem] || PROBLEM_TEXT.failed).charAt(0).toLowerCase()
      + (PROBLEM_TEXT[live.problem] || PROBLEM_TEXT.failed).slice(1)
    : null;

  return (
    <div className="app dm-page">
      {header}

      <div className="dm-toolbar" role="toolbar" aria-label="Data model view">
        <div className="seg seg-sm" role="group" aria-label="What to show">
          {VIEWS.map((v) => (
            <button key={v.id} type="button" className={"seg-btn" + (view === v.id ? " active" : "")}
              aria-pressed={view === v.id} disabled={!available(v.id)} title={why(v.id)} onClick={() => setView(v.id)}>
              {v.label}
            </button>
          ))}
        </div>
        <div className="seg seg-sm" role="group" aria-label="Show as">
          {[["diagram", "Diagram"], ["table", "Table"]].map(([id, label]) => (
            <button key={id} type="button" className={"seg-btn" + (display === id ? " active" : "")}
              aria-pressed={display === id} onClick={() => setDisplay(id)}>
              {label}
            </button>
          ))}
        </div>
        <label className="dm-search">
          <span className="sr-only">Find a kind or a connection</span>
          <input type="search" value={query} placeholder="Find a kind or connection" onChange={(e) => setQuery(e.target.value)}
            onKeyDown={pickSearch} aria-describedby="dm-search-result" />
        </label>
        <label className="dm-check">
          <input type="checkbox" checked={showCounts} onChange={(e) => setShowCounts(e.target.checked)} /> Show counts
        </label>
      </div>
      <div id="dm-search-result" className="dm-search-result muted" aria-live="polite">
        {highlight && (highlight.nodes.size || highlight.edges.size
          ? `${highlight.nodes.size} ${highlight.nodes.size === 1 ? "kind" : "kinds"} and ${highlight.edges.size} ${highlight.edges.size === 1 ? "connection" : "connections"} match. Press Enter to open the first.`
          : "Nothing matches.")}
      </div>

      {viewNote && <p className="dm-note">{viewNote}</p>}
      {fresh && fresh.up_to_date === false && view !== "designed" && (
        <p className="dm-note">The graph is still catching up with your latest changes, so some numbers may be a little behind.</p>
      )}
      {hasDesign && view !== "built" && design.updated && (
        <p className="muted dm-updated">Design last updated {String(design.updated).slice(0, 10)}.</p>
      )}

      {empty ? (
        <Empty title="Nothing in this view yet">
          {view === "built" ? "The maintenance graph has no records yet. Add positions or items in Assets and they appear here." : "The design has no kinds of thing in it."}
        </Empty>
      ) : (
        <>
          <Legend view={view} />
          <div className={"dm-main" + (display === "table" ? " dm-main-table" : "")}>
            {display === "diagram" && (
              <div className="card dm-diagram-card">
                <div className="dm-diagram-tools">
                  <button type="button" className="secondary" onClick={() => diagram.current?.fit()}>Fit to screen</button>
                  <button type="button" className="secondary" onClick={() => diagram.current?.relayout()}>Re-layout</button>
                  <span className="grow" />
                  <button type="button" className="secondary" onClick={exportPng}>Download as image</button>
                  <button type="button" className="secondary" onClick={exportArrows}
                    title="A JSON file you can open in arrows.app, Neo4j's drawing tool">Download for Arrows</button>
                </div>
                <Suspense fallback={<div className="dm-canvas-wrap"><div className="dm-canvas-note muted">Drawing the diagram…</div></div>}>
                  <DataModelDiagram ref={diagram} model={model} showCounts={showCounts} highlight={highlight}
                    selected={selected} onSelect={setSelected}
                    label={`Diagram of ${model.nodes.length} kinds of thing and ${model.edges.length} connections. The Table view lists the same thing for a keyboard or screen reader.`} />
                </Suspense>
                <p className="muted dm-hint">Drag a circle to move it, scroll to zoom, drag the background to move around. Click a circle or an arrow for its details.</p>
              </div>
            )}
            {display === "table" && (
              <div className="card dm-table-card">
                <div className="dm-diagram-tools">
                  <span className="grow" />
                  <button type="button" className="secondary" onClick={exportArrows}
                    title="A JSON file you can open in arrows.app, Neo4j's drawing tool">Download for Arrows</button>
                </div>
                <DataModelTable model={model} view={view} showCounts={showCounts} highlight={highlight}
                  selected={selected} onSelect={setSelected} />
              </div>
            )}
            <Details model={model} view={view} selected={selected} onSelect={setSelected} />
          </div>
        </>
      )}
    </div>
  );
}

function Legend({ view }) {
  return (
    <ul className="dm-legend" aria-label="Legend">
      <li><span className="dm-key dm-key-node" aria-hidden="true" /> A circle is a kind of thing, coloured by kind; bigger means more of them.</li>
      <li><span className="dm-key dm-key-line" aria-hidden="true" /> An arrow is a connection, named on the line.</li>
      <li><span className="dm-key dm-key-loop" aria-hidden="true" /> A loop connects a kind to itself (for example, one position that is part of another).</li>
      {view === "designed" && <li><span className="dm-key dm-key-dash" aria-hidden="true" /> Dashed: proposed, not yet decided.</li>}
      {view === "both" && (
        <>
          <li><span className="dm-key dm-key-dash" aria-hidden="true" /> Dashed: designed, not built yet.</li>
          <li><span className="dm-key dm-key-warn" aria-hidden="true" style={{ borderColor: WARN }} /> Amber: built, but not in the design.</li>
        </>
      )}
    </ul>
  );
}

const countText = (n) => (Number.isFinite(n) ? formatCount(n) : "—");

function DataModelTable({ model, view, showCounts, highlight, selected, onSelect }) {
  const rows = tableRows(model);
  const showState = view !== "built";
  const nodeById = new Map(model.nodes.map((n) => [n.id, n]));
  return (
    <div className="maint-scroll">
      <table className="dm-table">
        <caption className="sr-only">The data model as a table: each connection from one kind to another.</caption>
        <thead>
          <tr>
            <th scope="col">From</th>
            <th scope="col">Connection</th>
            <th scope="col">To</th>
            {showCounts && <th scope="col" className="num">How many</th>}
            {showState && <th scope="col">{view === "designed" ? "Decided?" : "Built and designed?"}</th>}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const hit = highlight && (r.kind === "edge" ? highlight.edges.has(r.id) : highlight.nodes.has(r.id));
            const isSel = selected && selected.id === r.id;
            const kindCell = (label) => (
              <button type="button" className="link dm-kind" onClick={() => onSelect({ kind: "node", id: label })}>
                <span className="dm-dot" style={{ background: nodeById.get(label)?.colour }} aria-hidden="true" />{label}
              </button>
            );
            return (
              <tr key={r.kind + r.id} className={(hit ? "dm-hit" : "") + (isSel ? " dm-sel" : "")}>
                <td>{kindCell(r.from)}</td>
                <td>{r.type ? (
                  <button type="button" className="link dm-type" onClick={() => onSelect({ kind: "edge", id: r.id })}>{r.type}</button>
                ) : <span className="muted">No connections</span>}</td>
                <td>{r.to ? kindCell(r.to) : ""}</td>
                {showCounts && <td className="num">{countText(r.count)}</td>}
                {showState && <td>{stateText(r, view)}</td>}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function Details({ model, view, selected, onSelect }) {
  if (!selected) {
    return (
      <aside className="card dm-details" aria-label="Details">
        <p className="muted">Pick a kind of thing or a connection to see its details: how many there are, what each records, and what it connects to.</p>
        <p className="muted">{model.nodes.length} {model.nodes.length === 1 ? "kind" : "kinds"} of thing, {model.edges.length} {model.edges.length === 1 ? "connection" : "connections"}.</p>
      </aside>
    );
  }
  if (selected.kind === "edge") {
    const e = model.edges.find((x) => x.id === selected.id);
    if (!e) return null;
    return (
      <aside className="card dm-details" aria-label="Details">
        <p className="dm-details-kind muted">Connection</p>
        <h2 className="dm-mono">{e.type}</h2>
        <p>From <KindLink id={e.from} onSelect={onSelect} /> to <KindLink id={e.to} onSelect={onSelect} />{e.loop && " (a loop: it connects this kind to itself)"}.</p>
        <dl className="dm-dl">
          {e.built && <><dt>How many</dt><dd>{countText(e.count)}</dd></>}
          {stateText(e, view) && <><dt>Status</dt><dd>{stateText(e, view)}{view === "both" && e.status === "proposed" ? " (proposed)" : ""}</dd></>}
          {e.note && <><dt>Note</dt><dd className="dm-text">{e.note}</dd></>}
        </dl>
      </aside>
    );
  }
  const n = model.nodes.find((x) => x.id === selected.id);
  if (!n) return null;
  const { out, in: inn } = connectionsOf(model, n.id);
  return (
    <aside className="card dm-details" aria-label="Details">
      <p className="dm-details-kind muted">
        <span className="dm-dot" style={{ background: n.colour }} aria-hidden="true" />Kind of thing{n.structure ? ` · ${n.structure}` : ""}
      </p>
      <h2>{n.label}</h2>
      {n.definition && <p className="dm-text">{n.definition}</p>}
      <dl className="dm-dl">
        {n.built && <><dt>How many</dt><dd>{countText(n.count)}</dd></>}
        {stateText(n, view) && view === "both" && <><dt>Status</dt><dd>{stateText(n, view)}</dd></>}
      </dl>
      {n.properties.length > 0 && (
        <>
          <h3>What each records</h3>
          <ul className="dm-props">
            {n.properties.map((p) => <li key={p.key}><code>{p.key}</code>{p.type && <span className="muted"> {p.type.toLowerCase()}</span>}</li>)}
          </ul>
        </>
      )}
      <h3>Connections out</h3>
      <EdgeList edges={out} side="to" onSelect={onSelect} />
      <h3>Connections in</h3>
      <EdgeList edges={inn} side="from" onSelect={onSelect} />
    </aside>
  );
}

function KindLink({ id, onSelect }) {
  return <button type="button" className="link" onClick={() => onSelect({ kind: "node", id })}>{id}</button>;
}

function EdgeList({ edges, side, onSelect }) {
  if (!edges.length) return <p className="muted">None.</p>;
  return (
    <ul className="dm-edges">
      {edges.map((e) => (
        <li key={e.id}>
          <button type="button" className="link dm-mono" onClick={() => onSelect({ kind: "edge", id: e.id })}>{e.type}</button>
          {" "}{side === "to" ? "→" : "←"} <KindLink id={e[side]} onSelect={onSelect} />
          {Number.isFinite(e.count) && <span className="muted"> ({formatCount(e.count)})</span>}
        </li>
      ))}
    </ul>
  );
}
