import { Suspense, lazy, useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { getClassForecast, getPositionClasses } from "../api.js";
import { useRoles } from "../RolesProvider.jsx";
import { formatNumber } from "../format.js";
import { EXPLORER_PARTS_CLASSES_TABS, tabPlace } from "../explorerTabs.js";
import { classesPath } from "../redirects.js";
// The class's whole forecast (the class page's own card), read only when a row is opened.
const ForecastCard = lazy(() => import("../views/MaintenanceLists.jsx").then((mod) => ({ default: mod.ForecastCard })));

// The position classes with a fitted life model, each with its expected
// failures over the next 12 months, under Forecasts. A row opens the class's
// whole forecast under the list (?class=<key>: the periods, the positions most at
// risk, the spares and the budget), and the forecast can be changed there; the
// same row again, or Close, puts it away. Nothing without Reliafy Maintenance.
// While the Explorer's Classes tab is switched off (EXPLORER_PARTS_CLASSES_TABS),
// a class address lands on an Explorer with no Classes tab, so nothing here
// links to one.
export default function ClassForecastList() {
  const { has } = useRoles();
  const [params, setParams] = useSearchParams();
  const open = params.get("class") || "";
  const openRef = useRef(null);
  const setOpen = (key) => {
    const next = new URLSearchParams(params);
    if (key && key !== open) next.set("class", key);
    else next.delete("class");
    setParams(next, { replace: true });
  };
  useEffect(() => {
    if (open) openRef.current?.scrollIntoView?.({ block: "nearest" });
  }, [open]);
  const [classes, setClasses] = useState(null);
  const [forecasts, setForecasts] = useState({});
  useEffect(() => {
    if (!has.maintenance) return undefined;
    let alive = true;
    getPositionClasses()
      .then((d) => {
        const fitted = (d.classes || []).filter((c) => c.model);
        if (!alive) return;
        setClasses(fitted);
        for (const c of fitted) {
          // By its key: a design class's label (product › … › position) can change.
          const key = c.class_key || c.position_class;
          getClassForecast(key)
            .then((f) => alive && setForecasts((s) => ({ ...s, [key]: f })))
            .catch(() => alive && setForecasts((s) => ({ ...s, [key]: { error: true } })));
        }
      })
      .catch(() => alive && setClasses([]));
    return () => {
      alive = false;
    };
  }, [has.maintenance]);
  if (!has.maintenance) return null;
  const linked = EXPLORER_PARTS_CLASSES_TABS;

  const cell = (name) => {
    const f = forecasts[name];
    if (!f) return <span className="lib-date">Working it out…</span>;
    if (f.error) return <span className="lib-date">Couldn't work it out: open it to see why</span>;
    if (!f.n_forecast) return <span className="lib-date">{f.headline}</span>;
    return `≈ ${formatNumber(f.expected)} in 12 months`;
  };

  return (
    <section className="home-card" aria-labelledby="class-forecasts">
      <div className="recent-models-head">
        <h2 id="class-forecasts">Position classes</h2>
        {linked && <Link to={classesPath()}>All classes →</Link>}
      </div>
      {classes === null ? (
        <div className="card empty">Loading…</div>
      ) : classes.length === 0 ? (
        <div className="card empty">
          {linked
            ? <p>No class has a fitted life model yet. Fit one from a class's pooled life data on its <Link to={classesPath()}>Classes</Link> page.</p>
            : <p>No class has a fitted life model yet. Fit one from a class's pooled life data in the Explorer's {tabPlace("models")}.</p>}
        </div>
      ) : (
        <div className="lib">
          <table className="lib-table">
            <thead>
              <tr>
                <th style={{ width: "34%" }}>Class</th>
                <th className="lib-opt" style={{ width: 90 }}>Positions</th>
                <th>Expected failures</th>
                <th className="lib-opt">Model</th>
              </tr>
            </thead>
            <tbody>
              {classes.map((c) => (
                <tr key={c.class_key || c.position_class} className="lib-row"
                    aria-current={(c.class_key || c.position_class) === open ? "true" : undefined}
                    onClick={() => setOpen(c.class_key || c.position_class)}>
                  <td>
                    <button type="button" className="link lib-name" aria-expanded={(c.class_key || c.position_class) === open}
                            onClick={(e) => { e.stopPropagation(); setOpen(c.class_key || c.position_class); }}>
                      {c.position_class}
                    </button>
                  </td>
                  <td className="lib-n lib-opt">{c.positions}</td>
                  <td className="lib-n">{cell(c.class_key || c.position_class)}</td>
                  <td className="lib-date lib-opt">{c.model.distribution || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {open && classes?.length > 0 && (
        <div ref={openRef} className="class-forecast-open">
          <div className="maint-row">
            <button type="button" className="secondary sm" onClick={() => setOpen(null)}>
              Close {classes.find((c) => (c.class_key || c.position_class) === open)?.position_class || open}
            </button>
          </div>
          <Suspense fallback={<div className="card empty">Loading…</div>}>
            <ForecastCard key={open} name={open} label={classes.find((c) => (c.class_key || c.position_class) === open)?.position_class || open} />
          </Suspense>
        </div>
      )}
    </section>
  );
}
