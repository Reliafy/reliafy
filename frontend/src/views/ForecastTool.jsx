import { useEffect, useMemo, useState } from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { getForecastStart, sparesScratchForecast } from "../api.js";
import { SectionHeader } from "../components/SectionPage.jsx";
import Card, { CardHeader } from "../components/ui/Card.jsx";
import Chip from "../components/ui/Chip.jsx";
import ChoiceChips from "../components/ui/ChoiceChips.jsx";
import SegmentedControl from "../components/ui/SegmentedControl.jsx";
import Field from "../components/ui/Field.jsx";
import { TextInput, TextArea } from "../components/ui/Controls.jsx";
import ResultSummary, { ResultDetails } from "../components/ui/ResultSummary.jsx";
import LoadFailed from "../components/LoadFailed.jsx";
import Loading from "../components/ui/Loading.jsx";
import ModelPicker from "../components/ModelPicker.jsx";
import StrategyUnit from "../components/StrategyUnit.jsx";
import { ComputeReason } from "../components/StrategyTool.jsx";
import FleetSparesCard from "../components/FleetSparesCard.jsx";
import Plot from "../components/Plot.jsx";
import { ACCENT, INK } from "../plotTheme.js";
import { formatNumber } from "../format.js";
import { formatCost, workspaceCurrency, costLabel } from "../money.js";
import { downloadCsv } from "../csv.js";
import { unitInText } from "../components/unitText.js";
import { strategyUnit } from "../strategyTools.js";
import {
  BLANK_FORM, HORIZONS, VIEWS, answerText, formFromStart, fromParam, groupsFor, isHours, missing, parseAges, requestOf, rowsOf,
  viewCsv, viewNeeds, viewOf, whenNext, whenText,
} from "../sparesForecast.js";
import "./ForecastTool.css";

// Decisions › Forecasts › Spares forecast, Hours forecast and Cost forecast: one quick forecast tool
// with three views over the same inputs (sparesForecast.js says what each part does). A scratch
// pad: nothing is saved. Switching views keeps the inputs and the answer (one engine call feeds all
// three). Opened from an Explorer node (Open in ›, ?from=), it starts filled in from there and names
// it, with a link back.

const HELP = { guide: "forecast-tools" };
const unitsOf = (fc) => (fc.items || []).reduce((t, it) => t + (Number(it.count) || 1), 0);
const sig3 = (v) => formatNumber(v, { sig: 3 });
const rangeText = (b, fmt = sig3) => (b?.interval ? `${fmt(b.interval[0])}–${fmt(b.interval[1])}` : "—");

function ByPeriod({ fc, view }) {
  const currency = workspaceCurrency();
  const money = (v) => formatCost(v, currency, { sig: 3 });
  const label = String(fc.period_label || "periods").replace(/s$/, "");
  const head = label[0].toUpperCase() + label.slice(1);
  if (view === "hours") {
    const h = fc.views.hours;
    return (
      <div className="maint-scroll">
        <table className="lib-table ft-table">
          <caption className="sr-only">Labour hours by {label}</caption>
          <thead><tr><th scope="col">{head}</th><th scope="col" className="num">Planned</th><th scope="col" className="num">Corrective</th>
            <th scope="col" className="num">Hours</th><th scope="col" className="num">Likely range (90% two-sided)</th></tr></thead>
          <tbody>{h.per_period.map((r) => (
            <tr key={r.period}><td className="num">{r.period}</td><td className="num">{sig3(r.planned)} h</td><td className="num">{sig3(r.corrective)} h</td>
              <td className="num">{sig3(r.hours?.expected)} h</td><td className="num">{rangeText(r.hours)} h</td></tr>
          ))}</tbody>
          <tfoot><tr><td>In all</td><td /><td /><td className="num">{sig3(h.total?.expected)} h</td><td className="num">{rangeText(h.total)} h</td></tr></tfoot>
        </table>
      </div>
    );
  }
  if (view === "costs") {
    const c = fc.views.costs;
    return (
      <div className="maint-scroll">
        <table className="lib-table ft-table">
          <caption className="sr-only">Costs by {label}</caption>
          <thead><tr><th scope="col">{head}</th><th scope="col" className="num">Planned</th><th scope="col" className="num">Corrective</th>
            <th scope="col" className="num">Spares</th><th scope="col" className="num">Cost</th><th scope="col" className="num">Likely range (90% two-sided)</th></tr></thead>
          <tbody>{c.per_period.map((r) => (
            <tr key={r.period}><td className="num">{r.period}</td><td className="num">{money(r.planned)}</td><td className="num">{money(r.corrective)}</td>
              <td className="num">{money(r.spares)}</td><td className="num">{money(r.cost?.expected)}</td><td className="num">{rangeText(r.cost, money)}</td></tr>
          ))}</tbody>
          <tfoot><tr><td>In all</td><td /><td /><td /><td className="num">{money(c.total?.expected)}</td><td className="num">{rangeText(c.total, money)}</td></tr></tfoot>
        </table>
      </div>
    );
  }
  const age = fc.strategy?.kind === "age";
  return (
    <div className="maint-scroll">
      <table className="lib-table ft-table">
        <caption className="sr-only">Spares by {label}</caption>
        <thead><tr><th scope="col">{head}</th><th scope="col" className="num">Failures</th>{age && <th scope="col" className="num">Planned</th>}
          <th scope="col" className="num">Spares</th><th scope="col" className="num">Likely range (90% two-sided)</th></tr></thead>
        <tbody>{rowsOf(fc).map((r) => (
          <tr key={r.period}><td className="num">{r.period}</td><td className="num">{sig3(r.failures?.expected)}</td>
            {age && <td className="num">{sig3(r.planned?.expected)}</td>}
            <td className="num">{sig3(r.parts?.expected ?? r.failures?.expected)}</td><td className="num">{rangeText(r.parts || r.failures)}</td></tr>
        ))}</tbody>
      </table>
    </div>
  );
}

function Chart({ fc, view }) {
  const label = String(fc.period_label || "periods").replace(/s$/, "");
  const series = view === "hours" ? fc.views.hours.per_period.map((r) => r.hours) : view === "costs" ? fc.views.costs.per_period.map((r) => r.cost)
    : rowsOf(fc).map((r) => r.parts || r.failures);
  const y = series.map((b) => b?.expected ?? 0);
  if (!y.some((v) => v > 0)) return null;
  const what = view === "hours" ? "Labour hours" : view === "costs" ? "Cost" : "Spares used";
  return (
    <>
      <Plot
        data={[{
          type: "bar", x: y.map((_, i) => i + 1), y, marker: { color: ACCENT },
          error_y: { type: "data", symmetric: false, color: INK, thickness: 1, width: 3,
            array: series.map((b, i) => Math.max(0, (b?.interval?.[1] ?? y[i]) - y[i])),
            arrayminus: series.map((b, i) => Math.max(0, y[i] - (b?.interval?.[0] ?? y[i]))) },
          hovertemplate: "%{y:.3s}<extra></extra>",
        }]}
        layout={{ height: 240, bargap: 0.35,
          xaxis: { title: { text: label[0].toUpperCase() + label.slice(1) }, tick0: 1, dtick: Math.max(1, Math.ceil(y.length / 12)) },
          yaxis: { title: { text: `${what} a ${label}` }, rangemode: "tozero" } }}
      />
      <p className="rs-note">Whiskers: each {label}’s likely range (90% two-sided).</p>
    </>
  );
}

function Answer({ fc, view, form }) {
  const currency = workspaceCurrency();
  const a = answerText(fc);
  const need = viewNeeds(view, form);
  if (view !== "spares" && (need || !fc.views?.[view])) {
    return <p className="lib-date ft-need" role="status">{need || "Forecast again to see this view."}</p>;
  }
  if (view === "hours") {
    const h = fc.views.hours;
    return (
      <ResultSummary sentence={<>≈ <b>{sig3(h.total.expected)} h</b> of maintenance in the next <b>{a.horizon}</b>.</>}
                     stats={[{ label: "Likely range (90% two-sided)", value: `${rangeText(h.total)} h` },
                       h.planned_hours != null && { label: "Each planned replacement", value: `${sig3(h.planned_hours)} h` },
                       h.corrective_hours != null && { label: "Each failure", value: `${sig3(h.corrective_hours)} h` }]}>
        Planned task hours plus corrective hours: each failure and each planned replacement times its hours.
      </ResultSummary>
    );
  }
  if (view === "costs") {
    const c = fc.views.costs;
    const money = (v) => formatCost(v, currency, { sig: 3 });
    return (
      <ResultSummary sentence={<>≈ <b>{money(c.total.expected)}</b> to maintain them in the next <b>{a.horizon}</b>.</>}
                     stats={[{ label: "Likely range (90% two-sided)", value: rangeText(c.total, money) },
                       { label: "Planned", value: money(c.per_period.reduce((t, r) => t + r.planned, 0)) },
                       { label: "Corrective", value: money(c.per_period.reduce((t, r) => t + r.corrective, 0)) },
                       { label: "Spares", value: money(c.per_period.reduce((t, r) => t + r.spares, 0)) }]}>
        Planned work, corrective work and the spares each uses.
      </ResultSummary>
    );
  }
  const parts = fc.strategy?.total?.parts || { expected: fc.expected, interval: fc.interval };
  return (
    <ResultSummary sentence={<>≈ <b>{a.parts}</b> spares used in the next <b>{a.horizon}</b>{a.planned != null ? <>: <b>{a.failures}</b> failures and <b>{a.planned}</b> planned replacements</> : null}.</>}
                   stats={[{ label: "Likely range (90% two-sided)", value: rangeText(parts) },
                     fc.periods > 1 && { label: `Average a ${String(fc.period_label).replace(/s$/, "")}`, value: `≈ ${formatNumber(parts.expected / fc.periods, { sig: 2 })}` }]}>
      Failed units are replaced, and the replacements can fail again inside the horizon.
    </ResultSummary>
  );
}

function WhenNext({ fc }) {
  const w = whenNext(fc);
  return (
    <section className="ft-next" aria-label="When next">
      <h3 className="ft-h">When next</h3>
      {!w.items.length ? <p className="lib-date">Fewer than one spare is expected in the horizon.</p> : (
        <>
          <ol className="ft-next-list">{w.items.map((x) => <li key={x.n}>{whenText(fc, x)}</li>)}</ol>
          <p className="lib-date">From the expected counts: the {String(fc.period_label).replace(/s$/, "")} by which each spare is likely used.{w.more ? ` ${w.more.toLocaleString("en-GB")} more after these.` : ""}</p>
        </>
      )}
    </section>
  );
}

export default function ForecastTool() {
  const location = useLocation();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const view = viewOf(location.pathname);
  const from = fromParam(params);
  const fromKey = from ? `${from.kind}:${from.id}:${params.get("root") || ""}` : "";
  const [form, setForm] = useState(BLANK_FORM);
  const [model, setModel] = useState(null);
  const [typedUnit, setTypedUnit] = useState("");
  const [start, setStart] = useState({ key: "", data: null, error: null });
  const [run, setRun] = useState({ busy: false, fc: null, error: null, sent: null });
  const set = (k) => (v) => setForm((f) => ({ ...f, [k]: v }));
  const setText = (k) => (e) => set(k)(e.target.value);

  // Filled in from an Explorer node, once per node.
  useEffect(() => {
    if (!fromKey || start.key === fromKey) return undefined;
    let live = true;
    getForecastStart({ kind: from.kind, id: from.id, root: params.get("root") })
      .then((data) => {
        if (!live) return;
        setStart({ key: fromKey, data, error: null });
        setForm((f) => formFromStart(data, f));
      })
      .catch((e) => live && setStart({ key: fromKey, data: null, error: e.message }));
    return () => { live = false; };
  }, [fromKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const unit = strategyUnit(model, typedUnit || start.data?.model?.unit || "");
  const why = missing(form, model, unit);
  const groups = groupsFor(form.horizon);
  const body = useMemo(() => (why ? null : requestOf(form, model, unit)), [why, form, model, unit]);
  const stale = !!run.fc && JSON.stringify(body) !== run.sent;
  const go = () => {
    if (!body) return;
    const sent = JSON.stringify(body);
    setRun((r) => ({ ...r, busy: true, error: null }));
    sparesScratchForecast(body)
      .then((fc) => setRun({ busy: false, fc, error: null, sent }))
      .catch((e) => setRun((r) => ({ ...r, busy: false, error: e.message })));
  };
  const use = isHours(unit) ? "Hours a unit runs a day" : `${unit ? sentenceCase(unitInText(unit)) : "Use"} a unit adds a day`;
  const currency = workspaceCurrency();
  const fc = run.fc?.status === "ok" ? run.fc : null;
  const wanted = start.data?.model?.id || null;

  return (
    <div className="app ft">
      <SectionHeader section="forecasts" title={view.title} purpose={view.purpose} help={HELP}>
        <Chip tone="neutral" className="ft-scratch" title="Nothing here is saved: change anything and forecast again">Scratch pad: not saved</Chip>
      </SectionHeader>
      {from && (
        <p className="ft-from" role="note">
          {start.error ? <>Couldn&apos;t fill it in from the Explorer: {start.error}</>
            : !start.data ? "Filling it in from the Explorer…"
              : <>From: <Link to={start.data.from.link}>{start.data.from.path || start.data.from.name}</Link>
                {start.data.from.kind === "task" ? ` · ${start.data.from.name}` : start.data.from.kind === "package" ? ` · ${start.data.from.name} (package)` : " and everything below it"}</>}
        </p>
      )}
      <SegmentedControl label="Show" className="ft-views" value={view.value}
                        onChange={(v) => navigate(`${VIEWS.find((x) => x.value === v).path}${location.search}`, { replace: true })}
                        options={VIEWS.map((v) => ({ value: v.value, label: v.label }))} />
      <Card className="ft-inputs">
        <CardHeader title="What to forecast" subtitle="The same inputs feed all three views: switch views without losing them." />
        {(start.data?.notes || []).length > 0 && (
          <ul className="ft-notes" aria-label="What the Explorer couldn't fill in">{start.data.notes.map((n) => <li key={n}>{n}</li>)}</ul>
        )}
        <div className="ft-grid">
          <div className="ft-model">
            <ModelPicker key={wanted || "none"} label="Life model (non-repairable)" value={model} onChange={setModel} preferSaved wanted={wanted} />
            <StrategyUnit model={model} unit={typedUnit} onUnit={setTypedUnit} />
          </div>
          <Field label="Units" help="How many of them run. A list of ages counts them for you.">
            <TextInput inputMode="numeric" value={form.units} onChange={setText("units")} disabled={parseAges(form.ages).ages?.length > 1} />
          </Field>
          <Field label={`Age now${unit ? ` (${unitInText(unit)})` : ""}`} help="One age for them all, or one per unit (spaces or new lines between).">
            <TextArea value={form.ages} onChange={setText("ages")} placeholder="e.g. 500, or 120 900 1,450" />
          </Field>
          <Field label={use}>
            <TextInput inputMode="decimal" value={form.perDay} onChange={setText("perDay")} placeholder={isHours(unit) ? "e.g. 16" : ""} />
          </Field>
          <Field label="Days a week it runs" help="7: every day. A duty of 5 days a week: 5.">
            <TextInput inputMode="decimal" value={form.daysWeek} onChange={setText("daysWeek")} />
          </Field>
          <Field label="Replacement" as="fieldset" className="ft-wide">
            <SegmentedControl label="Replacement" value={form.policy} onChange={set("policy")}
                              options={[{ value: "failure", label: "Replace on failure" }, { value: "age", label: "Preventive replacement" }]} />
          </Field>
          {form.policy === "age" && (
            <Field label={`Replace at age${unit ? ` (${unitInText(unit)})` : ""}`}>
              <TextInput inputMode="decimal" value={form.replaceAt} onChange={setText("replaceAt")} />
            </Field>
          )}
          {form.policy === "age" && (
            <Field label="Hours a planned replacement takes" optional>
              <TextInput inputMode="decimal" value={form.plannedHours} onChange={setText("plannedHours")} />
            </Field>
          )}
          {form.policy === "age" && (
            <Field label={costLabel("Cost of a planned replacement", currency)} optional>
              <TextInput inputMode="decimal" value={form.plannedCost} onChange={setText("plannedCost")} />
            </Field>
          )}
          <Field label="Hours a failure takes to put right" optional>
            <TextInput inputMode="decimal" value={form.correctiveHours} onChange={setText("correctiveHours")} />
          </Field>
          <Field label={costLabel("Cost of a failure", currency)} optional help="Besides the spare: labour, downtime, call-out.">
            <TextInput inputMode="decimal" value={form.failureCost} onChange={setText("failureCost")} />
          </Field>
          <Field label={costLabel("Cost of a spare", currency)} optional>
            <TextInput inputMode="decimal" value={form.spareCost} onChange={setText("spareCost")} />
          </Field>
          <Field label="Horizon" as="fieldset" className="ft-wide">
            <ChoiceChips label="Horizon" value={form.horizon} options={HORIZONS}
                         onChange={(v) => v && setForm((f) => ({ ...f, horizon: v, group: groupsFor(v).some((g) => g.value === f.group) ? f.group : "months" }))} />
          </Field>
          <Field label="Group by" as="fieldset" className="ft-wide">
            <SegmentedControl label="Group by" value={form.group} onChange={set("group")} options={groups} />
          </Field>
        </div>
        <div className="ft-run">
          <button type="button" className="primary" onClick={go} disabled={!body || run.busy} aria-describedby={why ? "ft-why" : undefined}>
            {run.busy ? "Forecasting…" : "Forecast"}
          </button>
          <ComputeReason id="ft-why" reason={why} />
          {stale && !run.busy && <span className="lib-date" role="status">The inputs changed: Forecast to update the answer.</span>}
        </div>
      </Card>
      {run.error && <LoadFailed what="Couldn't work out the forecast." error={run.error} />}
      {run.fc && run.fc.status !== "ok" && <div className="card error" role="alert">{run.fc.reason}</div>}
      {run.busy && !run.fc && <Loading />}
      {fc && (
        <Card className={"ft-result" + (run.busy ? " is-busy" : "")} aria-busy={run.busy || undefined}>
          <CardHeader title={view.title} subtitle={`${fc.model_name} · ${unitInText(fc.unit || unit || "")} · ${unitsOf(fc).toLocaleString("en-GB")} ${unitsOf(fc) === 1 ? "unit" : "units"}`}
                      actions={<button type="button" className="secondary sm" onClick={() => downloadCsv(viewCsv(fc, view.value), `${view.title.toLowerCase().replace(/ /g, "-")}.csv`)}>Export CSV</button>} />
          <Answer fc={fc} view={view.value} form={form} />
          {(view.value === "spares" || fc.views?.[view.value]) && !viewNeeds(view.value, form) && (
            <>
              <Chart fc={fc} view={view.value} />
              <ResultDetails summary={`By ${String(fc.period_label).replace(/s$/, "")}`} open>
                <ByPeriod fc={fc} view={view.value} />
              </ResultDetails>
            </>
          )}
          {view.value === "spares" && <WhenNext fc={fc} />}
        </Card>
      )}
      {fc && view.value === "spares" && (
        <FleetSparesCard fleet={{ name: "Spares forecast" }} settings={{ ...fc.settings, spares: form.spares }} forecast={fc}
                         dirty={stale} runWord="Forecast" onChange={(v) => set("spares")(v || {})} />
      )}
    </div>
  );
}

function sentenceCase(s) {
  const t = String(s || "");
  return t ? t[0].toUpperCase() + t.slice(1) : t;
}

