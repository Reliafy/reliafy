import { formatNumber } from "../format.js";
import { ciText, paramLabel } from "../recurrentResults.js";

const sig = (v, n = 4) => formatNumber(v, { sig: n });
const pText = (p) => (p < 0.001 ? "p < 0.001" : `p = ${formatNumber(p, { sig: 2 })}`);

// A recurrent model's fit statistics, in the dialog the side panel's "Fit
// statistics" row opens (#65): every parameter with its interval, the
// likelihood criteria, the Cramér-von Mises goodness-of-fit test, both trend
// tests, and each system against the model. What the "Trend & fit" tab
// showed, plus the parameters the panel leaves out.
export default function RecurrentStats({ r }) {
  const params = r.params || [];
  const coefs = (r.coefficients || []).filter((c) => c.coef != null);
  const tests = r.trend_tests || (r.trend ? [r.trend] : []);
  const cvm = r.gof_test;
  const systems = r.system_residuals || [];
  const rt = r.repair_test;
  return (
    <div className="rec-stats">
      {(params.length > 0 || coefs.length > 0) && (
        <section>
          <h3 className="rec-stats-h">Parameters</h3>
          <div className="rs-table-wrap">
            <table className="mini-table rec-stats-table">
              <thead><tr><th>Parameter</th><th>Estimate</th><th>95% interval</th></tr></thead>
              <tbody>
                {params.map((p) => (
                  <tr key={p.name}><td>{paramLabel(r, p.name)}</td><td>{sig(p.value)}</td><td>{ciText(p.ci) || "—"}</td></tr>
                ))}
                {coefs.map((c) => (
                  <tr key={c.name}>
                    <td>{c.name} <span className="gof-sub">coefficient</span></td>
                    <td>{sig(c.coef)}</td>
                    <td>{ciText(c.coef_ci) || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {r.baseline && r.family === "regression" && (
            <p className="rs-note">
              The baseline ({r.baseline.name}) is a system with every covariate at 0 and each text covariate at its
              reference level; a coefficient is the log of its rate ratio.
            </p>
          )}
        </section>
      )}

      {((r.gof || []).length > 0 || cvm) && (
        <section>
          <h3 className="rec-stats-h">Goodness of fit</h3>
          <dl className="rec-stats-dl">
            {(r.gof || []).map((g) => (
              <div key={g.id}><dt>{g.label}</dt><dd>{formatNumber(g.value, { sig: 6 })}</dd></div>
            ))}
            {cvm && (
              <div>
                <dt>Cramér-von Mises</dt>
                <dd>
                  {cvm.p_value != null
                    ? <>{cvm.adequate ? "fits" : "poor fit"} · {pText(cvm.p_value)} · {cvm.n_boot} bootstrap samples</>
                    : cvm.reason || "—"}
                </dd>
              </div>
            )}
          </dl>
          {cvm && cvm.p_value != null && (
            <p className="rs-note">
              {cvm.adequate
                ? "No evidence against the fitted model (p ≥ 0.05)."
                : "The failure times don't follow the fitted model (p < 0.05): try another model."}
            </p>
          )}
        </section>
      )}

      {rt && (
        <section>
          <h3 className="rec-stats-h">Repair test</h3>
          <dl className="rec-stats-dl">
            {[rt.perfect, rt.minimal].filter(Boolean).map((h) => (
              <div key={h.hypothesis}>
                <dt>{h.hypothesis[0].toUpperCase() + h.hypothesis.slice(1)}</dt>
                <dd>{h.rejected ? "ruled out" : "can't be ruled out"} · {pText(h.p_value)}</dd>
              </div>
            ))}
          </dl>
          <p className="rs-note">
            Likelihood-ratio tests of the fit against each kind of repair, at 5%.{" "}
            {rt.conclusion ? `${rt.conclusion[0].toUpperCase()}${rt.conclusion.slice(1)}.` : ""}
          </p>
        </section>
      )}

      <section>
        <h3 className="rec-stats-h">Trend tests</h3>
        {tests.length > 0 ? (
          <>
            <dl className="rec-stats-dl">
              {tests.map((t) => (
                <div key={t.id || t.test}>
                  <dt>{t.test}</dt>
                  <dd>
                    {t.significant && t.trend !== "no trend" ? t.trend : "no trend"} · {pText(t.p_value)} · statistic{" "}
                    {formatNumber(t.statistic, { sig: 3 })}{t.dof != null ? ` (${t.dof} dof)` : ""}
                  </dd>
                </div>
              ))}
            </dl>
            <p className="rs-note">
              Null hypothesis: a constant failure rate (HPP). A trend is named at p &lt; 0.05; each system is tested
              over its own observation window.
            </p>
          </>
        ) : (
          <p className="rs-note">Not available for a model built from parameters: the trend tests need event data.</p>
        )}
      </section>

      {(r.mtbf != null || r.rocof != null) && (
        <section>
          <h3 className="rec-stats-h">
            Rates at {formatNumber(r.end_of_observation ?? r.horizon)}{r.unit ? ` ${String(r.unit).toLowerCase()}` : ""}
            {r.rates_at ? `, ${r.rates_at}` : ""}
          </h3>
          <dl className="rec-stats-dl">
            <div><dt>MTBF now</dt><dd>{sig(r.mtbf)}{r.mtbf_ci ? ` · 95% ${ciText(r.mtbf_ci)}` : ""}</dd></div>
            {r.demonstrated_mtbf?.lower != null && (
              <div>
                <dt>Demonstrated MTBF</dt>
                <dd>
                  ≥ {sig(r.demonstrated_mtbf.lower)} at {Math.round((r.demonstrated_mtbf.confidence || 0.9) * 100)}%
                  (one-sided, {r.demonstrated_mtbf.method === "crow" ? "Crow exact, MIL-HDBK-189C" : "Wald"})
                </dd>
              </div>
            )}
            <div><dt>Failure rate (ROCOF)</dt><dd>{sig(r.rocof)}{r.rocof_ci ? ` · 95% ${ciText(r.rocof_ci)}` : ""}</dd></div>
          </dl>
          {r.bounds_method && (
            <p className="rs-note">
              {r.bounds_method === "crow"
                ? "Rate bounds: Crow's exact bounds (a time-terminated test, or one system run to its last failure)."
                : "Rate bounds: Wald (delta method). Crow's exact bounds need a Crow-AMSAA fit to a time-terminated test."}
            </p>
          )}
        </section>
      )}

      {systems.length > 1 && (
        <section>
          <h3 className="rec-stats-h">Systems against the model</h3>
          <div className="rs-table-wrap rec-stats-scroll">
            <table className="mini-table rec-stats-table">
              <thead><tr><th>System</th><th>Failures</th><th>Expected</th><th>Excess</th></tr></thead>
              <tbody>
                {systems.map((s) => (
                  <tr key={s.system}>
                    <td>{s.system}</td>
                    <td>{formatNumber(s.failures)}</td>
                    <td>{formatNumber(s.expected, { sig: 3 })}</td>
                    <td>{s.excess >= 0 ? "+" : "−"}{formatNumber(Math.abs(s.excess), { sig: 2 })}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="rs-note">
            Most excess failures first: each system's failures against what the model expects over its own window.
          </p>
        </section>
      )}
    </div>
  );
}
