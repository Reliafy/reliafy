import { Fragment, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  getMaintenanceAccess,
  getMaintenanceOverview,
  getWorkspaceChanges,
  getWorkspaceRcm,
  listDatasets,
  listFleets,
  listRbds,
  listStrategyAnalyses,
  listTrackedFleets,
} from "../api.js";
import { SAMPLE_MODEL, useFirstRun } from "../firstRun.js";
import { TYPE_LABEL, loadAllModels } from "../allModels.js";
import {
  ATTENTION_ROWS, RECENT_ROWS, attentionReady, attentionRest, attentionRows, dueRows, fleetRows, otherRecent,
  recentFor, recentRows, sparesRows, startersPlace, waitingFigures, workTodayRows,
} from "../home.js";
import { RBDS_LABEL, RBDS_PATH, homeCards } from "../navigation.js";
import { useAppConfig } from "../ConfigProvider.jsx";
import { useRoles } from "../RolesProvider.jsx";
import { SectionHeader } from "../components/SectionPage.jsx";
import { RolesCard } from "../components/RolePicker.jsx";
import { StartHere, StartHereCompact, useActivation } from "../components/FirstRun.jsx";
import WhatChangedPanel, { ChangeList } from "../components/WhatChanged.jsx";
import UnsavedFitReminder from "../components/UnsavedFitReminder.jsx";
import PlaceholderRows from "../components/PlaceholderRows.jsx";
import { partsPath } from "../redirects.js";
import { ORDERS_PATH, ordersPath } from "../maintenanceOrders.js";

// A list that can't be read counts as empty: Home is a summary, and each
// section's own page reports its errors.
const quiet = (p, key) => p.then((d) => (key ? d[key] : d) || []).catch(() => []);

const CARD_ROWS = 5;

// What a Maintenance card says when its work couldn't be read: not "nothing
// due", which would be a guess.
const NO_OVERVIEW = <>Couldn't load the maintenance work. <Link to={ORDERS_PATH}>Open Maintenance</Link> to see it.</>;

// One of Home's lists: a heading (with a link to the whole list, or a note),
// then rows in the "What changed" style, or `empty` when there are none.
// While `loading`, placeholder rows: the empty sentence is only for an answer
// that has arrived.
function HomeList({ id, title, note, all, rows, empty, loading = false, children }) {
  return (
    <section className="wc-panel home-list" aria-labelledby={id} data-card={id}>
      <div className="recent-models-head">
        <h2 id={id}>{title}</h2>
        {note && <span className="home-note">{note}</span>}
        {all && <Link to={all.to}>{all.label} →</Link>}
      </div>
      <div className="wc-card">
        {children}
        {loading ? <PlaceholderRows label={`Loading ${title}…`} />
          : rows.length > 0 ? <ChangeList rows={rows} /> : empty && <p className="home-none">{empty}</p>}
      </div>
    </section>
  );
}

// Home before its lists are in: it doesn't yet know which sections it will
// have, so grey cards with no headings.
function HomeWaiting() {
  return (
    <div className="view-loading" role="status">
      <span className="sr-only">Loading…</span>
      {[4, 6].map((rows) => (
        <section className="wc-panel home-list" key={rows} aria-hidden="true">
          <div className="recent-models-head"><span className="wait-bar home-wait-title" /></div>
          <div className="wc-card"><PlaceholderRows rows={rows} label={null} /></div>
        </section>
      ))}
    </div>
  );
}

// "6 of 35", then where the other rows are listed.
function AttentionNote({ rows }) {
  const pages = attentionRest(rows);
  return (
    <>
      {ATTENTION_ROWS} of {rows.length}
      {pages.length > 0 && " · the rest are in "}
      {pages.map((p, i) => (
        <Fragment key={p.to}>
          {i > 0 && (i === pages.length - 1 ? " and " : ", ")}
          <Link to={p.to}>{p.label}</Link>
        </Fragment>
      ))}
    </>
  );
}

// Figures in a row (each { label, n, to, alert }), for the at-a-glance cards.
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

// A role's card (navigation.js ROLES `home`), from what Home loaded. Cards
// that need Reliafy Maintenance draw nothing without it.
function RoleCard({ card, recent, attention, maintenance, rcm, has }) {
  const id = `home-${card}`;
  const first = (rows) => rows.slice(0, CARD_ROWS);
  switch (card) {
    case "recent-models":
      return (
        <HomeList id={id} title="Your recent models" all={{ to: "/models", label: "Models" }}
                  rows={first(recentFor(card, recent))}
                  empty={<>No models of your own yet. <Link to="/models/new">Fit some data</Link>.</>} />
      );
    case "recent-data":
      return (
        <HomeList id={id} title="Your recent data" all={{ to: "/data", label: "Data" }}
                  rows={first(recentFor(card, recent))}
                  empty={<>No datasets of your own yet. <Link to="/data">Upload or paste some</Link>.</>} />
      );
    case "recent-systems":
      return (
        <HomeList id={id} title={`Your recent ${RBDS_LABEL}`} all={{ to: RBDS_PATH, label: RBDS_LABEL }}
                  rows={first(recentFor(card, recent))}
                  empty={<>No block diagrams of your own yet. <Link to="/systems/b">Build one</Link>.</>} />
      );
    case "fleets":
      return (
        <HomeList id={id} title="Your fleets" all={{ to: "/forecasts", label: "Forecasts" }}
                  rows={first(fleetRows(attention, recent))}
                  empty={<>No fleets of your own yet. <Link to="/forecasts?new=1">Forecast one</Link>.</>} />
      );
    case "due": {
      if (!has.maintenance) return null;
      const due = dueRows(maintenance);
      return (
        <HomeList id={id} title="Due and at risk" all={{ to: ordersPath("due"), label: "Maintenance" }}
                  rows={first(due)} loading={maintenance === undefined}
                  empty={maintenance ? "Nothing due in the next 30 days." : NO_OVERVIEW}>
          {maintenance && (
            <Figures items={[
              { label: "overdue", n: (maintenance.due || []).filter((t) => t.overdue).length, to: ordersPath("due"), alert: true },
              { label: "due in 30 days", n: (maintenance.due || []).length, to: ordersPath("due") },
              { label: "critical spares short", n: (maintenance.critical_spares || []).length, to: partsPath(), alert: true },
              { label: "changes proposed", n: (maintenance.proposals || []).length, to: ORDERS_PATH },
            ]} />
          )}
        </HomeList>
      );
    }
    case "work-today": {
      if (!has.maintenance) return null;
      const open = maintenance?.open_work_orders || [];
      return (
        <HomeList id={id} title="Today's work orders"
                  all={{ to: ORDERS_PATH, label: maintenance ? `All ${open.length} open` : "Maintenance" }}
                  rows={first(workTodayRows(maintenance))} loading={maintenance === undefined}
                  empty={!maintenance ? NO_OVERVIEW : open.length ? "Nothing due today." : "No open work orders."} />
      );
    }
    case "spares":
      if (!has.maintenance) return null;
      return (
        <HomeList id={id} title="Critical spares short" all={{ to: partsPath(), label: "Parts and stock" }}
                  rows={first(sparesRows(maintenance))} loading={maintenance === undefined}
                  empty={maintenance ? "Every critical spare is stocked." : NO_OVERVIEW} />
      );
    case "waiting": {
      // The RCM on the asset tree and the maintenance overview: both are
      // Reliafy Maintenance's, so the card draws nothing without it.
      if (!has.maintenance) return null;
      const figures = waitingFigures(rcm, maintenance);
      return (
        <HomeList id={id} title="Targets and what's waiting" all={{ to: "/reports", label: "Reports" }} rows={[]}
                  loading={!figures.length && (rcm === undefined || maintenance === undefined)}
                  empty={figures.length ? null : NO_OVERVIEW}>
          {figures.length > 0 && <Figures items={figures} />}
        </HomeList>
      );
    }
    default:
      return null;
  }
}

// Home: where the app opens. With roles picked (Settings › What do you do?),
// it leads with each role's cards, the primary role's first. Then what
// changed across every section, what needs attention, the rest of the user's
// recent work, and the ways to start (home.js `startersPlace`): large and
// first for a new or near-empty workspace, one compact row otherwise, first
// while there is only a little work and last once there is plenty.
//
// Each section draws placeholder rows until its own answer is in; an empty
// sentence ("Nothing needs you right now.") is only ever an answer.
export default function HomePage() {
  const { roles, offer, has } = useRoles();
  const { maintenance: maintenanceOn, loaded: configLoaded } = useAppConfig();
  const [lists, setLists] = useState(null);
  const [changes, setChanges] = useState(undefined);
  // Whether this viewer has Reliafy Maintenance (the menu's check; the answer
  // is fetched once and shared): undefined until it is known.
  const [access, setAccess] = useState(undefined);
  // The Maintenance overview and the RCM on the asset tree (one rollup of
  // every decision's evidence check): undefined while loading, null when they
  // couldn't be read.
  const [maintenance, setMaintenance] = useState(undefined);
  const [rcm, setRcm] = useState(undefined);

  useEffect(() => {
    let live = true;
    Promise.all([
      loadAllModels().catch(() => []),
      quiet(listDatasets(), "datasets"),
      quiet(listRbds(), "rbds"),
      quiet(listFleets(), "fleets"),
      quiet(listStrategyAnalyses(), "analyses"),
      quiet(listTrackedFleets(), "fleets"),
    ]).then(([models, datasets, rbds, forecasts, analyses, tracked]) => {
      if (live) setLists({ models, datasets, rbds, forecasts, analyses, tracked });
    });
    getWorkspaceChanges().then((d) => live && setChanges(d)).catch(() => live && setChanges(null));
    return () => {
      live = false;
    };
  }, []);

  useEffect(() => {
    if (!configLoaded) return undefined;
    if (!maintenanceOn) {
      setAccess(false);
      return undefined;
    }
    let live = true;
    getMaintenanceAccess().then((a) => live && setAccess(!!a.allowed));
    return () => {
      live = false;
    };
  }, [configLoaded, maintenanceOn]);

  // Maintenance work and the tree's RCM, for Reliafy Maintenance's operators only.
  useEffect(() => {
    if (!access) return undefined;
    let live = true;
    getMaintenanceOverview().then((o) => live && setMaintenance(o)).catch(() => live && setMaintenance(null));
    getWorkspaceRcm().then((d) => live && setRcm(d?.rollup || null)).catch(() => live && setRcm(null));
    return () => {
      live = false;
    };
  }, [access]);

  useActivation(lists?.models);

  const recent = lists
    ? recentRows({ ...lists, models: lists.models.map((m) => ({ ...m, kind: TYPE_LABEL[m.type] })) })
    : [];
  const ownCount = recent.length;
  const firstRun = useFirstRun(lists ? ownCount > 0 : undefined);
  // Where the ways to start go, once the lists say how much work there is.
  const place = lists ? startersPlace(ownCount) : null;
  const lifeSamples = (lists?.models || []).filter((r) => r.is_sample && r.type === "life");
  const sampleModelId = (lifeSamples.find((r) => r.id === SAMPLE_MODEL) || lifeSamples[0])?.id || null;
  const attention = attentionRows({ changes, tracked: lists?.tracked, maintenance });
  const attentionIn = attentionReady({ changes, tracked: lists?.tracked, access, maintenance });

  // The roles' cards, and what they already show (left out of the lists below).
  const cards = homeCards(roles).filter((c) => has.maintenance || !["due", "work-today", "spares", "waiting"].includes(c));
  const cardShows = (r) => (cards.includes("due") && r.key.startsWith("due-"))
    || (cards.includes("fleets") && (r.key.startsWith("alert-") || r.key.startsWith("track-")));
  const needs = attention.filter((r) => !cardShows(r));
  const rest = otherRecent(cards, recent);

  return (
    <div className="app home">
      <SectionHeader
        title="Home"
        purpose={"Turn failure data into reliability models and decisions. Home shows "
          + (cards.length
            ? "what your roles look at first, then what changed and what needs you."
            : "what changed, what needs you and where to start.")}
      />

      {/* A fit left without saving, with its one-click save (#434). */}
      <UnsavedFitReminder />

      {lists === null ? (
        <HomeWaiting />
      ) : (
        <>
          {place === "large" && (firstRun === null
            ? <div className="wc-card home-start-wait"><PlaceholderRows label="Loading the ways to start…" /></div>
            : <StartHere info={firstRun} sampleModelId={sampleModelId} />)}
          {place === "first" && (
            <div className="home-start-first"><StartHereCompact sampleModelId={sampleModelId} /></div>
          )}

          {/* Asked once, of a new user, after the ways to start; Settings
              keeps the picker. */}
          {offer && <RolesCard offer />}

          {cards.map((card) => (
            <div key={card} className="home-slot">
              <RoleCard card={card} recent={recent} attention={attention} maintenance={maintenance}
                        rcm={rcm} has={has} />
            </div>
          ))}

          {/* The panel hides itself for a workspace with nothing of its own,
              so only one with work waits for it. */}
          {changes === undefined
            ? ownCount > 0 && <HomeList id="home-changes" title="What changed" rows={[]} loading />
            : <WhatChangedPanel data={changes} />}

          {/* "Nothing" before every source has answered would be a guess. */}
          <HomeList id="home-attention" title="Needs attention" rows={needs.slice(0, ATTENTION_ROWS)}
                    loading={!attentionIn}
                    note={attentionIn && needs.length > ATTENTION_ROWS ? <AttentionNote rows={needs} /> : null}
                    empty={access && maintenance === null ? NO_OVERVIEW : "Nothing needs you right now."} />

          {rest.length > 0 && (
            <HomeList id="home-recent" title={rest.length < recent.length ? "Other recent work" : "Recent"}
                      rows={rest.slice(0, RECENT_ROWS)}
                      note="Your work, most recently saved or edited first" />
          )}

          {place === "last" && <StartHereCompact sampleModelId={sampleModelId} />}
        </>
      )}
    </div>
  );
}
