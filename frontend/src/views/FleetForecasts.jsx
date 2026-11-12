import { useCallback, useEffect, useState } from "react";
import { useNavigate, useLocation, Link } from "react-router-dom";
import Modal from "../components/Modal.jsx";
import Select from "../components/Select.jsx";
import { listFleets, createFleet, deleteFleet, getFleet, listModels, listAltModels, listRecurrentModels } from "../api.js";
import { CardHeader } from "../components/ui/Card.jsx";
import ScrollCue from "../components/ui/ScrollCue.jsx";
import { MAX_COMPARE, compareRows } from "../fleetCompare.js";
import { workspaceCurrency } from "../money.js";
import { relativeTime } from "../instrument.js";
import Chip from "../components/ui/Chip.jsx";
import { SectionHeader, SectionList } from "../components/SectionPage.jsx";
import { PlusIcon, RowActions, RowLink, itemName, rowOpen } from "../components/LibRows.jsx";
import { formatNumber } from "../format.js";
import { modelFromSearch, plainName } from "../modelNext.js";
import ClassForecastList from "../components/ClassForecastList.jsx";
import { useRoles } from "../RolesProvider.jsx";
import { useConfirm } from "../components/ConfirmProvider.jsx";
import { deleteOrRemoveConfirm } from "../confirm.js";

// A forecast's row figure: "≈ 40.3 in 12 months", or why there isn't one.
function expectedCell(f) {
  if (!f.n_items) return <span className="lib-date">No items yet</span>;
  if (f.forecast_status !== "ok") return <span className="lib-date">{f.headline}</span>;
  // Items with no usage don't age: the forecast's 0 isn't an answer.
  if (!f.expected && !(Number(f.settings?.default_rate) > 0)) {
    return <span className="lib-date">Usage not set</span>;
  }
  const periods = f.settings?.periods ?? 12;
  const label = String(f.settings?.period_label || "months");
  const word = Number(periods) === 1 ? label.replace(/s$/i, "") : label;
  return `≈ ${formatNumber(f.expected)} in ${periods} ${word}`;
}

const HELP = { walkthrough: "fleet", guide: "forecast-fleet-failures-and-spares" };

// 2–4 ticked forecasts side by side (a pane above the list, not a dialog):
// failures, the spares answer and cost, each as its forecast page shows it.
function FleetCompare({ ids, onClear }) {
  const [loaded, setLoaded] = useState({});
  const [error, setError] = useState(null);
  useEffect(() => {
    let live = true;
    ids.filter((id) => !loaded[id]).forEach((id) => {
      getFleet(id).then((f) => live && setLoaded((m) => ({ ...m, [id]: f })))
        .catch((e) => live && setError(e.message));
    });
    return () => { live = false; };
    // loaded is read to skip ones already fetched
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ids.join(",")]);
  const fleets = ids.map((id) => loaded[id]).filter(Boolean);
  const { columns, rows } = compareRows(fleets, workspaceCurrency());
  return (
    <div className="card fleet-compare" data-testid="fleet-compare">
      <CardHeader
        title={`Comparing ${ids.length} forecasts`}
        subtitle="Each as saved, from its own model, items and settings. Ranges are 90%."
        actions={<button className="secondary sm" onClick={onClear}>Close</button>}
      />
      {error && <div className="card error">{error}</div>}
      {fleets.length < ids.length ? <p className="muted-line">Loading…</p> : (
        <ScrollCue className="table-scroll">
          <table className="mini-table">
            <thead>
              <tr>
                <th><span className="sr-only">Figure</span></th>
                {columns.map((c, j) => <th key={ids[j]} className="num"><Link to={`/forecasts/${ids[j]}`}>{c}</Link></th>)}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.label}>
                  <th scope="row">{r.label}</th>
                  {r.values.map((v, j) => <td key={ids[j]} className="num">{v}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </ScrollCue>
      )}
    </div>
  );
}

// Decisions › Forecasts: the failure forecasts, one row per fleet with its live
// expected-failure headline, then (with Reliafy Maintenance) the position
// classes' forecasts from their own pooled history.
export default function FleetForecasts() {
  const navigate = useNavigate();
  const { has } = useRoles();
  const [fleets, setFleets] = useState(null);
  const [error, setError] = useState(null);
  const [capHit, setCapHit] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [name, setName] = useState("");
  const [modelId, setModelId] = useState("");
  const [models, setModels] = useState([]);
  // "life": first failures / with replacement; "recurrent": repairable items,
  // every failure counted (#235).
  const [modelKind, setModelKind] = useState("life");
  const [recurrentModels, setRecurrentModels] = useState([]);
  const [hiddenCovariate, setHiddenCovariate] = useState(0);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState(null);
  // Forecasts ticked to compare (ids, in the order ticked), and whether the pane is open.
  const [ticked, setTicked] = useState([]);
  const [comparing, setComparing] = useState(false);
  const tick = (id) => {
    setTicked((cur) => (cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id].slice(-MAX_COMPARE)));
  };

  const refresh = useCallback(() => {
    listFleets()
      .then((d) => setFleets(d.fleets || []))
      .catch((e) => setError(e.message));
  }, []);
  useEffect(() => refresh(), [refresh]);

  // ``preset`` (a model's "Forecast a fleet", #294): that model chosen and
  // the forecast named after it.
  const openCreate = async (preset = null) => {
    setCreateError(null);
    setModalOpen(true);
    if (preset) {
      setModelKind("life");
      setModelId("");
    }
    // Replaceable equipment: life distributions, regression models and ALT
    // models (#234) — a regression or ALT fleet forecasts each item at its own
    // covariates or stress; picker values carry the kind, "alt:<id>" for an
    // ALT model. Repairable equipment: recurrent-event models (#235).
    const [life, alt, rec] = await Promise.all([
      listModels().then((d) => d.models || []).catch(() => []),
      listAltModels().then((d) => d.models || []).catch(() => []),
      listRecurrentModels().then((d) => d.models || []).catch(() => []),
    ]);
    const plain = life.filter((m) => m.kind === "distribution" && m.distribution);
    const regression = life.filter((m) => m.kind === "regression");
    const asOpt = (m, value, hint) => ({ value, label: m.name, hint });
    setModels([
      ...(plain.length ? [{ heading: "Life distributions" }] : []),
      ...plain.map((m) => asOpt(m, m.id, m.distribution)),
      ...(regression.length ? [{ heading: "Regression models — each item at its own covariates" }] : []),
      ...regression.map((m) => asOpt(m, m.id, m.distribution)),
      ...(alt.length ? [{ heading: "ALT models — each item at its own stress" }] : []),
      ...alt.map((m) => asOpt(m, `alt:${m.id}`, [m.distribution, m.life_model].filter(Boolean).join(" · "))),
    ]);
    // Covariate (proportional intensity) models can't drive a forecast yet: the
    // items carry no covariate values. They're left out, and the dialog says why.
    setRecurrentModels(rec.filter((m) => m.family !== "regression").map((m) => asOpt(m, m.id, m.model)));
    setHiddenCovariate(rec.filter((m) => m.family === "regression").length);
    const chosen = preset && [...plain, ...regression].find((m) => m.id === preset);
    if (chosen) {
      setModelId(chosen.id);
      setName((n) => n || `${plainName(chosen.name)} fleet`);
    }
  };

  // Opened as /forecasts?new=1&model=<id>: the new-forecast dialog, with the
  // model chosen. The query is dropped so a reload doesn't reopen it.
  const { search } = useLocation();
  useEffect(() => {
    const wanted = modelFromSearch(search);
    if (!wanted || new URLSearchParams(search).get("new") !== "1") return;
    navigate("/forecasts", { replace: true });
    openCreate(wanted);
    // openCreate is this render's; it runs once per link.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search]);

  const onCreate = async () => {
    if (!name.trim() || !modelId) return;
    setCreating(true);
    setCreateError(null);
    try {
      const alt = modelKind !== "recurrent" && modelId.startsWith("alt:");
      const fleet = await createFleet(
        name.trim(), alt ? modelId.slice(4) : modelId, modelKind === "recurrent" ? "recurrent" : alt ? "alt" : "life");
      navigate(`/forecasts/${fleet.id}`);
    } catch (err) {
      if (err.code === "cap") {
        setModalOpen(false);
        setCapHit(true);
      } else {
        setCreateError(err.message);
      }
    } finally {
      setCreating(false);
    }
  };

  const confirm = useConfirm();
  const onDelete = async (f) => {
    if (!(await confirm(deleteOrRemoveConfirm(f, "fleet", { name: itemName(f) })))) return;
    try {
      await deleteFleet(f.id);
      refresh();
    } catch (err) {
      setError(err.message);
    }
  };

  const pathOf = (id) => `/forecasts/${id}`;
  const newForecast = <button onClick={() => openCreate()}><PlusIcon /> New forecast</button>;

  return (
    <div className="app">
      <SectionHeader
        title="Forecasts"
        purpose={has.maintenance
          ? "How many failures (or warranty returns) to expect: fleets from your fitted models, position classes from their own history."
          : "How many failures (or warranty returns) a fleet will see over a horizon, from your fitted models."}
        help={HELP}
        primary={newForecast}
      />

      {error && <div className="card error">{error}</div>}
      {capHit && (
        <div className="card upgrade-nudge">
          <p>
            You've reached the free-plan limit of 1 failure forecast.{" "}
            <Link to="/billing">Upgrade to Pro</Link> for unlimited fleets.
          </p>
        </div>
      )}

      {has.maintenance && <div className="recent-models-head home-card"><h2>Fleets</h2></div>}
      {ticked.length > 0 && !comparing && (
        <div className="fleet-bulk-bar" data-testid="fleet-compare-bar">
          <b>{ticked.length} ticked</b>
          <span className="muted-line" style={{ margin: 0 }}>
            {ticked.length < 2 ? "Tick another forecast to compare them." : `Compare up to ${MAX_COMPARE} side by side.`}
          </span>
          <button className="sm" disabled={ticked.length < 2} onClick={() => setComparing(true)}>
            Compare {ticked.length}
          </button>
          <button className="secondary sm" onClick={() => setTicked([])}>Clear</button>
        </div>
      )}
      {comparing && ticked.length >= 2 && (
        <FleetCompare ids={ticked} onClear={() => { setComparing(false); setTicked([]); }} />
      )}
      <SectionList
        rows={fleets}
        noun={["forecast", "forecasts"]}
        help={HELP}
        empty={{
          title: "No failure forecasts yet",
          body: "Create one from a saved non-repairable model and list the items you have in service.",
          action: newForecast,
        }}
        head={[
          <th key="c" style={{ width: 36 }}><span className="sr-only">Compare</span></th>,
          <th key="f" style={{ width: "34%" }}>Forecast</th>,
          <th key="i" className="lib-opt" style={{ width: 80 }}>Items</th>,
          <th key="e">Expected failures</th>,
          <th key="u" className="lib-opt">Updated</th>,
          <th key="a"><span className="sr-only">Actions</span></th>,
        ]}
        render={(f) => (
          <tr key={f.id} className="lib-row" onClick={rowOpen(navigate, pathOf(f.id))}>
            <td className="fleet-items-sel" onClick={(e) => e.stopPropagation()}>
              <input type="checkbox" checked={ticked.includes(f.id)} onChange={() => { tick(f.id); setComparing(false); }}
                     aria-label={`Compare ${itemName(f)}`} title="Tick 2–4 forecasts to compare them" />
            </td>
            <td>
              <div className="lib-name">
                <RowLink to={pathOf(f.id)}>{itemName(f)}</RowLink>
                {f.shared_by && <Chip title={`Shared by ${f.shared_by}`}>Shared</Chip>}
              </div>
            </td>
            <td className="lib-n lib-opt">{f.n_items}</td>
            <td className="lib-n">{expectedCell(f)}</td>
            <td className="lib-date lib-opt">{relativeTime(f.updated_at || f.created_at)}</td>
            <RowActions item={f} to={pathOf(f.id)} onDelete={() => onDelete(f)} />
          </tr>
        )}
      />

      <ClassForecastList />

      {modalOpen && (
        <Modal
          title="New failure forecast"
          locked={creating}
          onClose={() => setModalOpen(false)}
          footer={
            <>
              <button className="secondary" onClick={() => setModalOpen(false)} disabled={creating}>
                Cancel
              </button>
              <button onClick={onCreate} disabled={creating || !name.trim() || !modelId}>
                {creating ? "Creating…" : "Create forecast"}
              </button>
            </>
          }
        >
          {createError && <div className="card error">{createError}</div>}
          <div className="rcm-form">
            <label className="login-field">
              <span>Name</span>
              <input
                type="text"
                autoFocus
                value={name}
                placeholder="e.g. Delivery trucks — bearings, next 12 months"
                onChange={(e) => setName(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && onCreate()}
              />
            </label>
            <label className="login-field">
              <span>Equipment</span>
              <Select
                value={modelKind}
                onChange={(v) => { setModelKind(v); setModelId(""); }}
                options={[
                  { value: "life", label: "Replaceable — a life, regression or ALT model",
                    hint: "Failures until each item is replaced (first failures, or with replacement)." },
                  { value: "recurrent", label: "Repairable — a model of repeat failures",
                    hint: "Each item is repaired and fails again: every repeat failure counted." },
                ]}
              />
            </label>
            <label className="login-field">
              <span>{modelKind === "recurrent" ? "Repairable model" : "Model"}</span>
              <Select
                value={modelId}
                onChange={setModelId}
                placeholder="Choose a saved model…"
                options={modelKind === "recurrent" ? recurrentModels : models}
              />
            </label>
            <p className="muted-line">
              {modelKind === "recurrent"
                ? `The forecast counts each item's repeat failures from its age (time since new) under this model — fit one under Modelling › Models › Repairable first if you don't have one yet.${hiddenCovariate ? ` ${hiddenCovariate} covariate model${hiddenCovariate === 1 ? " isn't" : "s aren't"} listed: a forecast can't use one yet, as items carry no covariate values.` : ""} Name items as the model's systems to use each one's own history.`
                : "The forecast evaluates this model at each item's age (and, for a regression or ALT model, at each item's own conditions) — fit one under Models first if you don't have one yet."}
            </p>
          </div>
        </Modal>
      )}
    </div>
  );
}
