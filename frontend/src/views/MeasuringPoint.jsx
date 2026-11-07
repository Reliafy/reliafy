import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { getMeasurementPoint } from "../api.js";
import LoadFailed from "../components/LoadFailed.jsx";
import PageHeader from "../components/ui/PageHeader.jsx";
import Chip from "../components/ui/Chip.jsx";
import Plot from "../components/Plot.jsx";
import ReadingsTable from "../components/ReadingsTable.jsx";
import { LimitsModal } from "../components/MeasurementsPanel.jsx";
import { today as workspaceToday } from "../components/MaintenanceParts.jsx";
import { PageTitle } from "../components/usePageTitle.js";
import { explorerPath } from "../assetTree.js";
import { pointHref } from "../measurementsTab.js";
import {
  READINGS_INTRO, canEditReadings, chartData, dayText, numberText, pageState, pointDates, pointMeta, readingDate, trendText,
} from "../measuringPoint.js";
import { ACCENT, DANGER } from "../plotTheme.js";
import { PointReadingModal } from "./MaintenancePosition.jsx";
import "./Maintenance.css";
import "./MeasuringPoint.css";

// One measuring point (/asset-register/points/:id): what it is and where
// (the position or item it's on, linked to the Explorer with that row
// picked), its latest reading against its limits with one state chip, a
// chart of its readings with the alarm limits, its rate or trend and the
// dates that follow from them, then every recent reading with a ⋯ menu each
// (Correct…, Void). "Add reading…" is the main action; "Edit limits…" sits
// beside it for a condition point.

const EXPLORER_TAB = "measurements";

// Where the point is in the Explorer: its position's row (or its item's), on the Measurements tab.
function placeCrumb(point) {
  if (point.position?.id) {
    return { label: point.position.name || "Its position", to: explorerPath("positions", { sel: point.position.id, tab: EXPLORER_TAB }) };
  }
  if (point.item?.id) {
    return { label: point.item.name || "Its item", to: explorerPath("locations", { sel: point.item.id, tab: EXPLORER_TAB }) };
  }
  return null;
}

function ReadingsChart({ point }) {
  const { points, limits } = useMemo(() => chartData(point), [point]);
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
    line: { color: ACCENT, width: 2 }, marker: { size: 6, color: ACCENT },
    hovertemplate: `%{text}<br>%{y:.4g}${unit}<extra></extra>`,
  }];
  const layout = {
    height: 320,
    showlegend: false,
    margin: { l: 56, r: 16, t: 16, b: 40 },
    xaxis: { type: "date" },
    yaxis: { title: { text: point.unit || "" } },
    shapes: limits.map((l) => ({
      type: "line", xref: "paper", x0: 0, x1: 1, yref: "y", y0: l.value, y1: l.value,
      line: { color: DANGER, width: 1.2, dash: "dash" },
    })),
    annotations: limits.map((l) => ({
      xref: "paper", x: 1, xanchor: "right", yref: "y", y: l.value, yanchor: "bottom", showarrow: false,
      text: `${l.label}${unit}`, font: { size: 11, color: DANGER },
    })),
  };
  return <Plot data={data} layout={layout} download={`${point.name} readings`} />;
}

export default function MeasuringPoint() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [point, setPoint] = useState(null);
  const [error, setError] = useState(null);
  const [modal, setModal] = useState(null); // "read" | "limits"
  const load = useCallback(() => {
    setError(null);
    return getMeasurementPoint(id).then(setPoint).catch((e) => setError(e.message));
  }, [id]);
  useEffect(() => { setPoint(null); load(); }, [load]);

  if (error && !point) {
    return (
      <div className="app">
        <LoadFailed header error={error} notFound="Measuring point not found." to={explorerPath("positions", { tab: EXPLORER_TAB })}
                    label="Go to the Explorer's measurements" />
      </div>
    );
  }
  if (!point) return <div className="app"><div className="card empty">Loading…</div></div>;

  const today = workspaceToday();
  const state = pageState(point, today);
  const trend = trendText(point);
  const dates = pointDates(point);
  const readable = canEditReadings(point) && !point.retired;
  const unit = point.unit ? ` ${point.unit}` : "";
  const place = placeCrumb(point);
  const home = pointHref(point);
  const latestWhen = point.read_at
    ? readingDate({ when: point.read_when, precision: point.read_precision, at: String(point.read_at) })
    : "";
  const done = () => { setModal(null); load(); };
  const notReadable = point.derived ? "Worked out from a signal channel" : point.source === "automated"
    ? `Read by a feed${point.tag ? ` (${point.tag})` : ""}` : point.retired ? "This point is retired" : "";

  return (
    <div className="app mp-page">
      <PageTitle name={point.name} />
      <PageHeader
        crumbs={[{ label: "Assets", to: "/asset-register" }, { label: "Explorer", to: explorerPath("positions") }, ...(place ? [place] : [])]}
        title={point.name}
        meta={pointMeta(point)}
        id={point.id}
        actions={point.kind !== "counter" && !point.retired
          ? <button className="secondary" onClick={() => setModal("limits")}>Edit limits…</button> : null}
        primary={<button onClick={() => setModal("read")} disabled={!readable} title={readable ? "" : notReadable}>Add reading…</button>}
        menu={home && (
          <button type="button" className="ovm-item" role="menuitem" onClick={() => navigate(home)}>
            {point.position?.id ? "Open the position's page" : "Open the item's page"}
          </button>
        )}
      />
      {error && <div className="card error">{error}</div>}

      <section className="card mp-facts" aria-label="Latest reading and limits">
        <div className="mp-fact">
          <span className="mp-fact-label">Latest</span>
          <span className="mp-fact-value">{point.reading != null ? `${numberText(point.reading)}${unit}` : "No reading yet"}</span>
          {latestWhen && <span className="lib-date">{latestWhen}</span>}
        </div>
        {point.kind !== "counter" && (
          <div className="mp-fact">
            <span className="mp-fact-label">Alarm limits</span>
            <span className="mp-fact-value">
              {point.alarm_below == null && point.alarm_above == null ? "None set" : (
                <>
                  {point.alarm_below != null ? `${numberText(point.alarm_below)}` : "—"}
                  <span className="mp-range-sep"> to </span>
                  {point.alarm_above != null ? `${numberText(point.alarm_above)}` : "—"}
                  {unit}
                </>
              )}
            </span>
            <span className="lib-date">
              {point.alarm_below == null && point.alarm_above == null
                ? "Set limits to be warned"
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
      </section>

      <section className="card">
        <div className="maint-head"><h2>Readings over time</h2></div>
        <ReadingsChart point={point} />
      </section>

      <section className="card">
        <div className="maint-head"><h2>Readings</h2></div>
        {point.readings?.length ? (
          <>
            <p className="lib-date mp-intro">
              {canEditReadings(point) ? READINGS_INTRO : "The latest readings from its feed, newest first."}
            </p>
            <ReadingsTable point={point} onChanged={setPoint} />
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
    </div>
  );
}
