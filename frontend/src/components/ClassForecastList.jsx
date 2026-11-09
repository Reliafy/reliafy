import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { getClassForecast, getPositionClasses } from "../api.js";
import { useRoles } from "../RolesProvider.jsx";
import { formatNumber } from "../format.js";
import { EXPLORER_PARTS_CLASSES_TABS } from "../explorerTabs.js";

const classPath = (name) => `/asset-register/classes/${encodeURIComponent(name)}`;

// The position classes with a fitted life model, each with its expected
// failures over the next 12 months, under Forecasts. Each opens
// on its class page, where the forecast can be changed. Nothing without
// Reliafy Maintenance. While the Explorer's Classes tab is switched off
// (EXPLORER_PARTS_CLASSES_TABS), a class address lands on an Explorer with no
// Classes tab, so nothing here links to one.
export default function ClassForecastList() {
  const { has } = useRoles();
  const navigate = useNavigate();
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
          getClassForecast(c.position_class)
            .then((f) => alive && setForecasts((s) => ({ ...s, [c.position_class]: f })))
            .catch(() => alive && setForecasts((s) => ({ ...s, [c.position_class]: { error: true } })));
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
    if (f.error) return <span className="lib-date">{linked ? "Open the class to see it" : "Couldn't work it out"}</span>;
    if (!f.n_forecast) return <span className="lib-date">{f.headline}</span>;
    return `≈ ${formatNumber(f.expected)} in 12 months`;
  };

  return (
    <section className="home-card" aria-labelledby="class-forecasts">
      <div className="recent-models-head">
        <h2 id="class-forecasts">Position classes</h2>
        {linked && <Link to="/asset-register/classes">All classes →</Link>}
      </div>
      {classes === null ? (
        <div className="card empty">Loading…</div>
      ) : classes.length === 0 ? (
        <div className="card empty">
          {linked
            ? <p>No class has a fitted life model yet. Fit one from a class's pooled life data on its <Link to="/asset-register/classes">Classes</Link> page.</p>
            : <p>No class has a fitted life model yet. Fit one from a class's pooled life data in the Explorer's Modelling tab.</p>}
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
                <tr key={c.position_class} className={linked ? "lib-row" : undefined}
                    onClick={linked ? () => navigate(classPath(c.position_class)) : undefined}>
                  <td>
                    {linked ? (
                      <Link className="lib-name lib-link" to={classPath(c.position_class)} onClick={(e) => e.stopPropagation()}>
                        {c.position_class}
                      </Link>
                    ) : <span className="lib-name">{c.position_class}</span>}
                  </td>
                  <td className="lib-n lib-opt">{c.positions}</td>
                  <td className="lib-n">{cell(c.position_class)}</td>
                  <td className="lib-date lib-opt">{c.model.distribution || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
