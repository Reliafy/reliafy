import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { getMeasurementPoint, listSignalChannels, updateMeasurementPoint } from "../api.js";
import { isNotFound } from "./loadFailed.js";
import Chip from "./ui/Chip.jsx";
import Plot from "./Plot.jsx";
import ReadingsTable from "./ReadingsTable.jsx";
import { Field, FormModal, today as workspaceToday } from "./MaintenanceParts.jsx";
import { editLabel, isSetting, pointMoveItem } from "../measurementsTab.js";
import PointMoveModal from "./PointMoveModal.jsx";
import { ChannelView } from "./SignalsPanel.jsx";
import SignalStorage from "./SignalStorage.jsx";
import { usePanelMenu } from "../panelMenu.js";
import {
  READINGS_INTRO, canEditReadings, chartData, dayText, numberText, pageState, pointDates, pointMeta, rangeFact, readingDate,
  settingChangeRows, settingSummary, trendText,
} from "../measuringPoint.js";
import { ACCENT, DANGER, MUTED } from "../plotTheme.js";
import { PointReadingModal } from "../views/MaintenancePosition.jsx";
import "../views/Maintenance.css";
import "./MeasurementViews.css";

// A measuring point, or a sensor channel, open in full inside the Explorer's
// Measurements tab (?tab=measurements&point=<id> or &channel=<id>): the tree
// stays on the left with its position picked, and the panel shows, under a
// "← Measurements" link back to the list, what used to be the point's own page:
// its latest reading against its limits with one state chip, a chart of its
// readings with the alarm limits, its rate or trend and the dates that follow,
// then every recent reading with a ⋯ menu each (Correct…, Void). Add reading…,
// Edit limits… and Move… are in the panel heading's "…" (`onMenu`), like
// every tab's actions; full screen works as for any tab. A channel shows its
// spectrum, watch bands and settings (SignalsPanel's ChannelView).

// Edit limits… (a condition point) or Edit… (a counter or a setting): what the
// point is (a condition point and a setting swap; a counter no task goes by can
// become either), a condition point's alarm limits and a setting's allowed
// range. Any limit may be left blank (no limit that side). A band or level
// worked out from a signal channel stays a condition point.
export function LimitsModal({ point, onClose, onDone }) {
  const str = (v) => (v == null ? "" : String(v));
  const [kind, setKind] = useState(point.kind || "condition");
  const [above, setAbove] = useState(str(point.alarm_above));
  const [below, setBelow] = useState(str(point.alarm_below));
  const [lo, setLo] = useState(str(point.range_min));
  const [hi, setHi] = useState(str(point.range_max));
  const num = (v) => (v.trim() === "" ? null : Number(v));
  const badAlarm = kind === "condition" && above.trim() !== "" && below.trim() !== "" && Number(below) >= Number(above);
  const badRange = kind === "setting" && lo.trim() !== "" && hi.trim() !== "" && Number(lo) > Number(hi);
  const u = point.unit ? ` (${point.unit})` : "";
  const submit = async () => {
    const body = kind !== point.kind ? { kind } : {};
    if (kind === "condition") Object.assign(body, { alarm_above: num(above), alarm_below: num(below) });
    if (kind === "setting") Object.assign(body, { range_min: num(lo), range_max: num(hi) });
    onDone(await updateMeasurementPoint(point.id, body));
  };
  return (
    <FormModal title={`${kind === "condition" && point.kind === "condition" ? "Limits" : "Edit"}: ${point.name}`} submitLabel="Save"
               canSubmit={!badAlarm && !badRange} onClose={onClose} onSubmit={submit}>
      {!point.derived && (
        <Field label="What it is">
          <select value={kind} onChange={(e) => setKind(e.target.value)} aria-label="Kind">
            {point.kind === "counter" && <option value="counter">Counts use (run hours, cycles, km)</option>}
            <option value="condition">Condition (vibration, temperature, wear)</option>
            <option value="setting">Setting (output %, hours a day, a setpoint)</option>
          </select>
        </Field>
      )}
      {kind === "setting" && (
        <>
          <p className="lib-date">A value someone sets. It holds until the next change: no alarm, never due. The range only catches typing mistakes.</p>
          <Field label={`Lowest allowed${u}`}><input type="number" inputMode="decimal" step="any" value={lo} onChange={(e) => setLo(e.target.value)} /></Field>
          <Field label={`Highest allowed${u}`}><input type="number" inputMode="decimal" step="any" value={hi} onChange={(e) => setHi(e.target.value)} /></Field>
          {badRange && <p className="lib-date" role="alert">The lowest allowed must not be above the highest.</p>}
        </>
      )}
      {kind === "condition" && (
        <>
          <p className="lib-date">An alarm when a reading goes past either limit. Leave one blank for no limit on that side.</p>
          <Field label={`Alarm above${u}`}><input type="number" inputMode="decimal" step="any" autoFocus value={above} onChange={(e) => setAbove(e.target.value)} /></Field>
          <Field label={`Alarm below${u}`}><input type="number" inputMode="decimal" step="any" value={below} onChange={(e) => setBelow(e.target.value)} /></Field>
          {badAlarm && <p className="lib-date" role="alert">The low alarm must be below the high alarm.</p>}
        </>
      )}
      {kind === "counter" && <p className="lib-date">A counter counts use and only goes up. Pick another kind to change it.</p>}
    </FormModal>
  );
}

const Back = ({ onBack }) => (
  <button type="button" className="link mv-back" onClick={onBack}>← Measurements</button>
);

function ReadingsChart({ point }) {
  const { points, limits, step, range } = useMemo(() => chartData(point, workspaceToday()), [point]);
  if (points.length < 2) {
    return (
      <p className="lib-date mp-chart-empty">
        {points.length ? "One reading so far: the chart starts with the second." : "No readings to chart yet."}
      </p>
    );
  }
  const unit = point.unit ? ` ${point.unit}` : "";
  const data = [{
    type: "scatter", mode: "lines+markers", x: points.map((p) => p.x), y: points.map((p) => p.y),
    text: points.map((p) => p.label), name: point.name,
    line: { color: ACCENT, width: 2, ...(step ? { shape: "hv" } : {}) },
    marker: { size: points.map((p) => (p.held ? 0 : 6)), color: ACCENT },
    hovertemplate: `%{text}<br>%{y:.4g}${unit}<extra></extra>`,
  }];
  const lines = [...limits.map((l) => ({ ...l, color: DANGER })), ...range.map((l) => ({ ...l, color: MUTED }))];
  const layout = {
    height: 300,
    showlegend: false,
    margin: { l: 56, r: 16, t: 16, b: 40 },
    xaxis: { type: "date" },
    yaxis: { title: { text: point.unit || "" } },
    shapes: lines.map((l) => ({
      type: "line", xref: "paper", x0: 0, x1: 1, yref: "y", y0: l.value, y1: l.value,
      line: { color: l.color, width: 1.2, dash: "dash" },
    })),
    annotations: lines.map((l) => ({
      xref: "paper", x: 1, xanchor: "right", yref: "y", y: l.value, yanchor: "bottom", showarrow: false,
      text: `${l.label}${unit}`, font: { size: 11, color: l.color },
    })),
  };
  return <Plot data={data} layout={layout} download={`${point.name} readings`} />;
}

// What a point offers in the panel heading's "…".
export function pointViewMenu(point, { onRead, onLimits, onMove }) {
  if (!point) return [];
  const readable = canEditReadings(point) && !point.retired;
  const why = point.derived ? "Worked out from a signal channel" : point.source === "automated"
    ? `Read by a feed${point.tag ? ` (${point.tag})` : ""}` : point.retired ? "This point is retired" : "";
  const move = pointMoveItem(point);
  return [
    { id: "point-read", label: isSetting(point) ? "Record a change…" : "Add reading…", onSelect: onRead, disabled: !readable, title: readable ? "" : why },
    !point.retired && { id: "point-limits", label: editLabel(point), onSelect: onLimits },
    !point.retired && { id: "point-move", label: "Move…", onSelect: onMove, disabled: !!move.disabled, title: move.reason || "" },
  ].filter(Boolean);
}

export function PointView({ id, onBack, onMenu = null, onChanged }) {
  const [point, setPoint] = useState(null);
  const [error, setError] = useState(null);
  const [modal, setModal] = useState(null); // "read" | "limits" | "move"
  const [moved, setMoved] = useState(null); // what the last Move… said
  const load = useCallback(() => {
    setError(null);
    return getMeasurementPoint(id).then(setPoint).catch((e) => setError(e.message));
  }, [id]);
  useEffect(() => { setPoint(null); load(); }, [load]);
  usePanelMenu(onMenu, pointViewMenu(point, {
    onRead: () => setModal("read"), onLimits: () => setModal("limits"), onMove: () => setModal("move"),
  }));

  if (error && !point) {
    return (
      <div className="td-tab-page mv-view">
        <Back onBack={onBack} />
        <div className={"card load-failed" + (isNotFound(error) ? "" : " error")} role={isNotFound(error) ? "status" : "alert"}>
          {isNotFound(error) ? "Measuring point not found. It may have been deleted, or the link may be mistyped." : `Couldn't load the point: ${error}`}
        </div>
      </div>
    );
  }
  if (!point) return <div className="td-tab-page mv-view"><Back onBack={onBack} /><p className="lib-date">Loading…</p></div>;

  const today = workspaceToday();
  const state = pageState(point, today);
  const trend = trendText(point);
  const dates = pointDates(point);
  const readable = canEditReadings(point) && !point.retired;
  const unit = point.unit ? ` ${point.unit}` : "";
  const latestWhen = point.read_at
    ? readingDate({ when: point.read_when, precision: point.read_precision, at: String(point.read_at) })
    : "";
  const done = () => { setModal(null); load(); onChanged?.(); };
  const noLimits = point.alarm_below == null && point.alarm_above == null;

  return (
    <div className="td-tab-page mv-view">
      <Back onBack={onBack} />
      <h3 className="mv-name">{point.name}</h3>
      <p className="lib-date mv-meta">{pointMeta(point)}</p>
      {moved && <p className="lib-date" role="status">{moved}</p>}
      {error && <div className="card error">{error}</div>}

      <div className="mp-facts" role="group" aria-label="Latest reading and limits">
        <div className="mp-fact">
          <span className="mp-fact-label">{isSetting(point) ? "Set to" : "Latest"}</span>
          <span className="mp-fact-value">{point.reading != null ? `${numberText(point.reading)}${unit}` : "No reading yet"}</span>
          {latestWhen && <span className="lib-date">{latestWhen}</span>}
        </div>
        {isSetting(point) && (
          <div className="mp-fact">
            <span className="mp-fact-label">Allowed range</span>
            <span className="mp-fact-value">{rangeFact(point).text}</span>
            <span className="lib-date">{rangeFact(point).detail}</span>
          </div>
        )}
        {point.kind === "condition" && (
          <div className="mp-fact">
            <span className="mp-fact-label">Alarm limits</span>
            <span className="mp-fact-value">
              {noLimits ? "None set" : (
                <>
                  {point.alarm_below != null ? numberText(point.alarm_below) : "—"}
                  <span className="mp-range-sep"> to </span>
                  {point.alarm_above != null ? numberText(point.alarm_above) : "—"}
                  {unit}
                </>
              )}
            </span>
            <span className="lib-date">
              {noLimits ? "Set limits to be warned"
                : [point.alarm_below != null && "low", point.alarm_above != null && "high"].filter(Boolean).join(" and ") + " alarm"}
            </span>
          </div>
        )}
        <div className="mp-fact">
          <span className="mp-fact-label">State</span>
          <span className="mp-fact-value"><Chip tone={state.tone}>{state.label}</Chip></span>
          <span className="lib-date">{state.title}</span>
        </div>
        {trend && (
          <div className="mp-fact">
            <span className="mp-fact-label">{trend.label}</span>
            <span className="mp-fact-value">{trend.text}</span>
            <span className="lib-date">{trend.detail}</span>
          </div>
        )}
        {dates.reachesLimit && (
          <div className="mp-fact">
            <span className="mp-fact-label">Reaches its limit</span>
            <span className="mp-fact-value">about {dayText(dates.reachesLimit)}</span>
            <span className="lib-date">at its current trend</span>
          </div>
        )}
        {dates.nextReading && (
          <div className="mp-fact">
            <span className="mp-fact-label">Next reading due</span>
            <span className="mp-fact-value">{dayText(dates.nextReading)}</span>
            <span className="lib-date">by its usual round</span>
          </div>
        )}
        {point.alarm_work_order && (
          <div className="mp-fact">
            <span className="mp-fact-label">Alarm work order</span>
            <span className="mp-fact-value">
              <Link to={`/maintenance/work-orders/${point.alarm_work_order.id}`}>#{point.alarm_work_order.number}</Link>
            </span>
            <span className="lib-date">open</span>
          </div>
        )}
      </div>

      <section className="mv-section" aria-label={isSetting(point) ? "What it's been over time" : "Readings over time"}>
        <h4>{isSetting(point) ? "What it's been over time" : "Readings over time"}</h4>
        {isSetting(point) && settingSummary(point) && <p className="mv-summary">{settingSummary(point)}</p>}
        <ReadingsChart point={point} />
      </section>

      {isSetting(point) && (
        <section className="mv-section" aria-label="Changes">
          <h4>Changes</h4>
          {point.changes?.length ? (
            <ul className="mv-changes">
              {settingChangeRows(point, today).map((c) => (
                <li key={c.key}>
                  <span className="mv-change-text">{c.text}</span>
                  {c.workOrder
                    ? <> · <Link to={`/maintenance/work-orders/${c.workOrder.id}`}>WO {c.workOrder.number}</Link>{c.task && <span className="lib-date"> · {c.task.name}</span>}</>
                    : <span className="lib-date"> · by hand</span>}
                  {c.held && <span className="lib-date mv-held"> · {c.held}</span>}
                </li>
              ))}
            </ul>
          ) : (
            <p className="lib-date">
              Not set yet. {readable ? <button type="button" className="crumb-link" onClick={() => setModal("read")}>Record the value it&apos;s set to</button> : "Record the value it's set to"}, or record it from the work order that sets it.
            </p>
          )}
        </section>
      )}

      <section className="mv-section" aria-label="Readings">
        <h4>{isSetting(point) ? "Every recorded value" : "Readings"}</h4>
        {point.readings?.length ? (
          <>
            <p className="lib-date mp-intro">
              {isSetting(point) ? "Each value as recorded, newest first. Correct or void one from its ⋯; a voided value stays listed, struck out."
                : canEditReadings(point) ? READINGS_INTRO : "The latest readings from its feed, newest first."}
            </p>
            <ReadingsTable point={point} onChanged={(p) => { setPoint(p); onChanged?.(); }} />
          </>
        ) : (
          <div className="card empty mp-empty">
            {readable
              ? <>No readings yet. <button type="button" className="crumb-link" onClick={() => setModal("read")}>Add the first one.</button></>
              : point.source === "automated" ? `No readings yet: they arrive from its feed${point.tag ? ` (${point.tag})` : ""}.`
                : "No readings yet."}
          </div>
        )}
      </section>

      {modal === "read" && <PointReadingModal point={point} onClose={() => setModal(null)} onDone={done} />}
      {modal === "limits" && <LimitsModal point={point} onClose={() => setModal(null)} onDone={done} />}
      {modal === "move" && (
        <PointMoveModal point={point} onClose={() => setModal(null)}
                        onDone={(r) => {
                          setMoved(`Moved to ${r.position?.name || "its new position"}.${r.note ? ` ${r.note}` : ""}`);
                          done();
                        }} />
      )}
    </div>
  );
}

// A sensor channel in full: its spectrum and player, watch bands and levels
// (#bands: a row's "Edit bands…"), level over time, and settings.
export function ChannelPane({ id, onBack, onMenu = null }) {
  const { hash } = useLocation();
  const [all, setAll] = useState(null);
  const [error, setError] = useState(null);
  const [tick, setTick] = useState(0);
  const load = useCallback(() => listSignalChannels()
    .then((d) => { setAll(d.channels || []); setError(null); })
    .catch((e) => setError(e.message)), []);
  useEffect(() => { load(); }, [load]);
  usePanelMenu(onMenu, []);
  const ch = all?.find((c) => c.id === id);
  if ((error && !all) || (all && !ch)) {
    return (
      <div className="td-tab-page mv-view">
        <Back onBack={onBack} />
        <div className={"card load-failed" + (error ? " error" : "")} role={error ? "alert" : "status"}>
          {error ? `Couldn't load the channel: ${error}` : "Sensor channel not found. It may have been deleted, or the link may be mistyped."}
        </div>
      </div>
    );
  }
  if (!ch) return <div className="td-tab-page mv-view"><Back onBack={onBack} /><p className="lib-date">Loading…</p></div>;
  const meta = ["Sensor channel", ch.unit, ch.tag && `tag ${ch.tag}`, ch.axes?.length > 1 && `axes ${ch.axes.join(", ")}`]
    .filter(Boolean).join(" · ");
  return (
    <div className="td-tab-page mv-view">
      <Back onBack={onBack} />
      <h3 className="mv-name">{ch.name}</h3>
      <p className="lib-date mv-meta">{meta}</p>
      <div className="sg">
        <SignalStorage refresh={tick} />
        <ChannelView key={ch.id} summary={ch} all={all} focusBands={hash === "#bands"}
                     onChanged={() => { setTick((t) => t + 1); return load(); }} />
      </div>
    </div>
  );
}
