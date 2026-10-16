import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { StartHere } from "../components/FirstRun.jsx";
import { SAMPLE_MODEL, useFirstRun } from "../firstRun.js";
import { TYPE_LABEL, loadAllModels } from "../allModels.js";
import { getMaintenanceOverview, listDatasets, listRbds, listRcmStudies } from "../api.js";
import { relativeTime } from "../instrument.js";
import { trackEvent } from "../telemetry.js";
import { homeCards } from "../navigation.js";
import { useRoles } from "../RolesProvider.jsx";
import PageHeader from "../components/ui/PageHeader.jsx";
import { RolesCard } from "../components/RolePicker.jsx";
import WhatChangedPanel from "../components/WhatChanged.jsx";
import UnsavedFitReminder from "../components/UnsavedFitReminder.jsx";
import SafetyStarterCard from "../components/RbdSafetyStarter.jsx";
import { PlusIcon, RbdIcon, RcmIcon, UploadIcon } from "../components/icons.jsx";

const ACTIVATED_KEY = "reliafy_activated";
const RECENT = 5;

const fmtDay = (d) => (d ? new Date(`${d}T00:00:00`).toLocaleDateString(undefined, { day: "numeric", month: "short" }) : "");
const plural = (n, one, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;
const own = (rows) => (rows || []).filter((r) => !r.is_sample);
const newest = (rows) => [...rows].sort((a, b) => ((b.updated_at || b.created_at || "") > (a.updated_at || a.created_at || "") ? 1 : -1));

// A Home card: a heading with a link to the whole list, then rows (each a
// link: { key, to, name, kind, when }), or `empty` while there are none.
function HomeList({ id, title, all, rows, empty, children }) {
  return (
    <section className="recent-models home-card" aria-labelledby={`home-${id}`} data-card={id}>
      <div className="recent-models-head">
        <h2 id={`home-${id}`}>{title}</h2>
        {all && <Link to={all.to}>{all.label} →</Link>}
      </div>
      {children}
      {rows === null ? (
        <p className="muted-line home-empty">Loading…</p>
      ) : rows.length === 0 ? (
        <p className="muted-line home-empty">{empty}</p>
      ) : (
        <ul className="recent-models-list">
          {rows.map((r) => (
            <li key={r.key}>
              <Link className="recent-model" to={r.to}>
                <span className="recent-model-name">{r.name}</span>
                {r.kind && <span className="recent-model-kind">{r.kind}</span>}
                {r.when && <span className={"recent-model-when" + (r.late ? " maint-overdue" : "")}>{r.when}</span>}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

// Figures in a row (each { label, n, to }), for the at-a-glance cards.
function Figures({ items }) {
  return (
    <ul className="home-figures">
      {items.map((f) => (
        <li key={f.label}>
          <Link to={f.to} className={"home-figure" + (f.alert && f.n > 0 ? " alert" : "")}>
            <span className="home-figure-n">{f.n}</span>
            <span className="home-figure-label">{f.label}</span>
          </Link>
        </li>
      ))}
    </ul>
  );
}

function RecentModels({ rows }) {
  const list = rows === null ? null : own(rows).slice(0, RECENT).map((r) => ({
    key: r.id, to: r.to, name: r.name, kind: `${TYPE_LABEL[r.type]} · ${r.detail}`, when: relativeTime(r.created_at),
  }));
  return (
    <HomeList id="recent-models" title="Your recent models" all={{ to: "/models", label: "All models" }} rows={list}
              empty={<>No models of your own yet. <Link to="/models/new">Fit some data</Link>.</>} />
  );
}

function RecentData() {
  const [rows, setRows] = useState(null);
  useEffect(() => {
    listDatasets().then((d) => setRows(newest(own(d.datasets)))).catch(() => setRows([]));
  }, []);
  const list = rows && rows.slice(0, RECENT).map((d) => ({
    key: d.id, to: `/data/d/${d.id}`, name: d.name, kind: plural(d.n_rows ?? 0, "row"), when: relativeTime(d.created_at),
  }));
  return (
    <HomeList id="recent-data" title="Your recent data" all={{ to: "/data", label: "All data" }} rows={list}
              empty={<>No datasets of your own yet. <Link to="/data">Upload or paste some</Link>.</>} />
  );
}

function RecentSystems() {
  const [rows, setRows] = useState(null);
  useEffect(() => {
    listRbds().then((d) => setRows(newest(own(d.rbds)))).catch(() => setRows([]));
  }, []);
  const list = rows && rows.slice(0, RECENT).map((r) => ({
    key: r.id, to: `/systems/b/${r.id}`, name: r.name,
    kind: `${plural(r.n_nodes ?? 0, "block")}${r.repairable ? " · repairable" : ""}`,
    when: relativeTime(r.updated_at || r.created_at),
  }));
  return (
    <HomeList id="recent-systems" title="Your recent systems" all={{ to: "/systems", label: "All systems" }} rows={list}
              empty={<>No block diagrams of your own yet. <Link to="/systems/b">Build one</Link>.</>} />
  );
}

// Planner: what's due in the next 30 days and what's at risk.
function DueCard({ overview }) {
  const due = overview?.due || [];
  const list = overview && due.slice(0, RECENT).map((t) => ({
    key: t.id, name: t.name, kind: t.subject?.name, late: t.overdue,
    to: t.open_work_order ? `/maintenance/work-orders/${t.open_work_order.id}` : "/maintenance",
    when: t.overdue ? `overdue · ${fmtDay(t.next_due)}` : fmtDay(t.next_due),
  }));
  return (
    <HomeList id="due" title="Due and at risk" all={{ to: "/maintenance", label: "Due & work orders" }} rows={list}
              empty="Nothing due in the next 30 days.">
      {overview && (
        <Figures items={[
          { label: "overdue", n: due.filter((t) => t.overdue).length, to: "/maintenance", alert: true },
          { label: "due in 30 days", n: due.length, to: "/maintenance" },
          { label: "critical spares short", n: (overview.critical_spares || []).length, to: "/asset-register/parts", alert: true },
          { label: "proposed changes", n: (overview.proposals || []).length, to: "/maintenance" },
        ]} />
      )}
    </HomeList>
  );
}

// Technician: open work orders due today or before.
function WorkTodayCard({ overview }) {
  const open = overview?.open_work_orders || [];
  const today = overview?.today;
  const now = open.filter((w) => w.due && today && w.due <= today).sort((a, b) => (a.due > b.due ? 1 : -1));
  const list = overview && now.slice(0, 8).map((w) => ({
    key: w.id, to: `/maintenance/work-orders/${w.id}`, name: `#${w.number} ${w.title}`,
    kind: [w.subject?.name, w.location?.name].filter(Boolean).join(" · "),
    when: w.due < today ? `overdue · ${fmtDay(w.due)}` : "today", late: w.due < today,
  }));
  return (
    <HomeList id="work-today" title="Today's work orders" all={{ to: "/maintenance", label: `All ${open.length} open` }}
              rows={list} empty={open.length ? "Nothing due today." : "No open work orders."} />
  );
}

// Supportability / logistics: critical spares below what's kept.
function SparesCard({ overview }) {
  const list = overview && (overview.critical_spares || []).slice(0, RECENT).map((v) => ({
    key: v.id, to: v.part.id ? `/asset-register/parts/${v.part.id}` : "/asset-register/parts", name: `${v.part.part_number} ${v.part.name}`,
    kind: v.position?.name, when: `${v.usable_on_hand} usable, keep ${v.min_on_hand}`, late: v.usable_on_hand <= 0,
  }));
  return (
    <HomeList id="spares" title="Critical spares short" all={{ to: "/asset-register/parts", label: "Parts & stock" }}
              rows={list} empty="Every critical spare is stocked." />
  );
}

// Manager: how the RCM decisions stand against their evidence, and what's
// waiting on someone.
function WaitingCard({ overview, maintenance }) {
  const [studies, setStudies] = useState(null);
  useEffect(() => {
    listRcmStudies().then((d) => setStudies(own(d.studies))).catch(() => setStudies([]));
  }, []);
  const sum = (key) => (studies || []).reduce((n, s) => n + (s.rollup?.[key] || 0), 0);
  const items = [
    { label: "RCM decisions supported", n: sum("supported"), to: "/maintenance/rcm" },
    { label: "contradicted by evidence", n: sum("contradicted"), to: "/maintenance/rcm", alert: true },
    { label: "without evidence", n: sum("unevidenced") + sum("inconclusive"), to: "/maintenance/rcm" },
  ];
  if (maintenance && overview) {
    items.push(
      { label: "changes to decide", n: (overview.proposals || []).length, to: "/maintenance", alert: true },
      { label: "tasks overdue", n: (overview.due || []).filter((t) => t.overdue).length, to: "/maintenance", alert: true },
      { label: "open work orders", n: (overview.open_work_orders || []).length, to: "/maintenance" },
    );
  }
  return (
    <section className="recent-models home-card" aria-labelledby="home-waiting" data-card="waiting">
      <div className="recent-models-head">
        <h2 id="home-waiting">Targets and what's waiting</h2>
        <Link to="/reports">Reports →</Link>
      </div>
      {studies === null ? <p className="muted-line home-empty">Loading…</p> : <Figures items={items} />}
    </section>
  );
}

function QuickStarts() {
  const starts = [
    { to: "/models/new", icon: <UploadIcon />, label: "Fit data", sub: "Upload or paste failure times and fit a life model." },
    { to: "/systems/b", icon: <RbdIcon />, label: "Build an RBD", sub: "Draw a system's blocks and work out its reliability." },
    { to: "/maintenance/rcm", icon: <RcmIcon />, label: "Plan maintenance", sub: "An RCM study: failure modes, decisions and their evidence." },
  ];
  return (
    <section className="home-card" aria-labelledby="home-starts" data-card="starts">
      <div className="recent-models-head"><h2 id="home-starts">Start something</h2></div>
      <div className="home-starts">
        {starts.map((s) => (
          <Link key={s.to} to={s.to} className="home-start">
            <span className="home-start-icon">{s.icon}</span>
            <span><b>{s.label}</b><span className="muted-line">{s.sub}</span></span>
            <span className="home-start-plus" aria-hidden="true"><PlusIcon /></span>
          </Link>
        ))}
      </div>
    </section>
  );
}

// Home (#438): what the user's roles lead with, then their recent work, what
// changed, and quick starts. With no roles: due and at risk (with
// Maintenance), recent models, systems and data.
export default function HomePage() {
  const { roles, offer, has } = useRoles();
  const [models, setModels] = useState(null);
  useEffect(() => {
    loadAllModels().then(setModels).catch(() => setModels([]));
  }, []);
  const [overview, setOverview] = useState(null);
  useEffect(() => {
    if (!has.maintenance) return;
    getMaintenanceOverview().then(setOverview).catch(() => setOverview(null));
  }, [has.maintenance]);

  // A workspace with nothing of its own (the first-run rule) gets the first-run starts.
  const ownModels = own(models);
  const firstRun = useFirstRun(models === null ? undefined : ownModels.length > 0);

  // Activation metric: fire once, the moment a workspace gains its first
  // life-data model of its own. localStorage-guarded so it reports a
  // browser's first activation.
  const ownLife = ownModels.some((r) => r.type === "life");
  useEffect(() => {
    if (ownLife && localStorage.getItem(ACTIVATED_KEY) !== "1") {
      localStorage.setItem(ACTIVATED_KEY, "1");
      trackEvent("activated");
    }
  }, [ownLife]);
  const lifeSamples = (models || []).filter((r) => r.is_sample && r.type === "life");
  const sampleModelId = (lifeSamples.find((r) => r.id === SAMPLE_MODEL) || lifeSamples[0])?.id || null;

  const CARDS = {
    "recent-models": () => <RecentModels rows={models} />,
    "recent-data": () => <RecentData />,
    "recent-systems": () => <RecentSystems />,
    due: () => has.maintenance && <DueCard overview={overview} />,
    "work-today": () => has.maintenance && <WorkTodayCard overview={overview} />,
    spares: () => has.maintenance && <SparesCard overview={overview} />,
    waiting: () => <WaitingCard overview={overview} maintenance={has.maintenance} />,
  };

  return (
    <div className="app home">
      <PageHeader title="Home" meta="Your work across Reliafy: what to look at first, and where to start." />

      {/* Asked once, of a new user (#438); Settings keeps the picker. */}
      {offer && <RolesCard offer />}

      {/* A fit left without saving, with its one-click save (#434). */}
      <UnsavedFitReminder />

      {/* An empty workspace starts with the first-run starts (#312); once it
          has work of its own, the role's cards lead and the starts follow. */}
      {firstRun && <StartHere info={firstRun} sampleModelId={sampleModelId} />}

      {homeCards(roles).map((id) => {
        const card = CARDS[id]?.();
        return card ? <div key={id} className="home-slot">{card}</div> : null;
      })}

      {/* What changed in the workspace (#41), once it has work of its own. */}
      <WhatChangedPanel />

      {firstRun === false && <QuickStarts />}
      <SafetyStarterCard />
    </div>
  );
}
