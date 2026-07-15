import { useState } from "react";

// A copyable code block (monospace, with a copy button).
function Code({ children }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(children);
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    } catch { /* selectable text remains */ }
  };
  return (
    <div className="api-code">
      <button className="api-copy" onClick={copy}>{copied ? "Copied ✓" : "Copy"}</button>
      <pre><code>{children}</code></pre>
    </div>
  );
}

// A request/response field table (name · type · required · description).
function Fields({ title, rows }) {
  if (!rows || !rows.length) return null;
  return (
    <div className="api-fields">
      <div className="api-fields-h">{title}</div>
      <table className="api-params">
        <tbody>
          {rows.map((r) => (
            <tr key={r.name}>
              <td><code>{r.name}</code></td>
              <td className="api-ptype">{r.type}</td>
              <td className={"api-preq " + (r.req ? "yes" : "no")}>{r.req ? "required" : "optional"}</td>
              <td className="api-pdesc">{r.desc}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// One endpoint, OpenAPI-style: method + path, description, request fields, an
// example, and the response shape.
function Endpoint({ method, path, desc, request, example, returns }) {
  return (
    <div className="api-ep">
      <div className="api-ep-head">
        <span className={`api-method ${method.toLowerCase()}`}>{method}</span>
        <code className="api-path">{path}</code>
      </div>
      {desc && <p className="muted-line api-ep-desc">{desc}</p>}
      <Fields title="Request" rows={request} />
      {example && <Code>{example}</Code>}
      {returns && (
        <div className="api-fields">
          <div className="api-fields-h">Response · 200</div>
          <Code>{returns}</Code>
        </div>
      )}
    </div>
  );
}

// ---- reliafy-client (Python package) ---------------------------------------
function ClientDocs({ base }) {
  return (
    <div className="api-section">
      <p className="muted-line">
        <code>reliafy-client</code> is a thin Python wrapper over the HTTP API —
        push SurPyval fits, create datasets, fit models, read reliability, and
        run the strategy calculators, all from a notebook or script. Pure
        standard library; you bring{" "}
        <a className="evidence-link" href="https://github.com/derrynknife/SurPyval" target="_blank" rel="noreferrer">SurPyval</a>.
      </p>

      <h3>Install &amp; authenticate</h3>
      <Code>{`pip install reliafy-client        # installed as reliafy-client, imported as \`reliafy\`

import reliafy
reliafy.configure(token="rlf_...")   # or set RELIAFY_TOKEN; base_url= for self-hosted`}</Code>
      <p className="muted-line">Create a token under <b>Settings → API access</b> (Pro on Reliafy Cloud).</p>

      <h3>Push a fitted model</h3>
      <p className="muted-line">
        <code>push(model, name, *, data=True, unit=None) → url</code>. With{" "}
        <code>data=True</code> (default) the fitted observations go up too (full
        probability plot, refittable); <code>data=False</code> is params only.
      </p>
      <Code>{`import surpyval as sp, reliafy
model = sp.Weibull.fit(x=failures, c=censoring_flags)
url = reliafy.push(model, name="Pump bearings — 2026", unit="hours")

reliafy.push_params("weibull", [1200.0, 2.3], name="Handbook value", unit="hours")`}</Code>

      <h3>Read models &amp; reliability</h3>
      <Code>{`reliafy.list_models()                       # -> [{id, name, distribution, ...}]
reliafy.get_model(model_id)                 # -> params(+CIs), metrics, gof

r = reliafy.reliability(model_id, t=1000)   # -> {"at": {reliability, failure, hazard, ...}}
reliafy.reliability(model_id, t=1000, covariates={"temp_C": 90})   # PH model`}</Code>

      <h3>Create a dataset &amp; fit</h3>
      <Code>{`ds = reliafy.upload_dataset("Bearings", csv="hours,failed\\n120,1\\n340,0\\n510,1")
model = reliafy.fit(ds["id"], "weibull", "Bearing life",
                    mapping={"x": "hours", "c": "failed"}, unit="hours")`}</Code>

      <h3>Fleet &amp; strategy</h3>
      <Code>{`reliafy.fleet_forecast(fleet_id)
reliafy.optimal_replacement("weibull", [1435, 2.5],
                            planned_cost=200, unplanned_cost=1500, unit="hours")
reliafy.failure_finding("exponential", [1/8760], target_availability=0.99, unit="hours")`}</Code>

      <ul className="api-list">
        <li>Full field/response schemas are on the <b>HTTP API</b> tab — each client call maps to one endpoint.</li>
        <li>Errors raise <code>reliafy.ReliafyError</code>; reads/writes are scoped to your own data.</li>
      </ul>
    </div>
  );
}

// ---- Raw HTTP API ----------------------------------------------------------
function HttpDocs({ base }) {
  return (
    <div className="api-section">
      <p className="muted-line">
        Token-authed endpoints scoped to your own data. Base URL{" "}
        <code>{base}</code>. Every request needs the bearer header below.
      </p>

      <h3>Authentication</h3>
      <p className="muted-line">
        A personal token (<code>rlf_…</code>) from <b>Settings → API access</b>.
        Tokens read and write <b>your own</b> data — never the account, billing,
        tokens, or team artifacts.
      </p>
      <Code>{`-H "Authorization: Bearer rlf_your_token_here"`}</Code>
      <ul className="api-list">
        <li>Bodies are JSON; the ingest endpoints also accept raw CSV (<code>Content-Type: text/csv</code>).</li>
        <li>Errors: <code>422</code> (bad input, with a message), <code>404</code> (unknown/foreign id), <code>401</code> (bad token), <code>429</code> (over 120 req/min).</li>
      </ul>

      <h3>Models &amp; reliability</h3>

      <Endpoint
        method="GET"
        path="/api/v1/models"
        desc="List your saved models (life-data and degradation)."
        returns={`{
  "models": [
    { "id": "a1b2…", "name": "Bearing life", "kind": "distribution",
      "distribution": "Weibull", "n": 30, "unit": "hours",
      "created_at": "2026-07-15T02:48:08+00:00", "url": "/modelling/m/a1b2…" }
  ]
}`}
      />

      <Endpoint
        method="GET"
        path="/api/v1/models/{id}"
        desc="A model's fitted parameters, life metrics, and goodness-of-fit."
        request={[{ name: "id", type: "string · path", req: true, desc: "Model id." }]}
        returns={`{
  "id": "a1b2…", "name": "Bearing life", "distribution": "Weibull",
  "kind": "distribution", "unit": "hours", "n": 30,
  "params": [ { "name": "alpha", "value": 1435.1, "se": 108.9, "ci": [1220, 1650] },
              { "name": "beta",  "value": 2.5,    "ci": [1.78, 3.21] } ],
  "coefficients": [],          // populated for proportional-hazards models
  "metrics": null,             // {median, mttf, b10} for discrete / non-parametric
  "gof": [ { "id": "aic", "label": "AIC", "value": 466.3 }, … ]
}`}
      />

      <Endpoint
        method="POST"
        path="/api/v1/models/{id}/reliability"
        desc="Evaluate the reliability functions. With t you get point values; without it, the full grid."
        request={[
          { name: "t", type: "number", req: false, desc: "Time to evaluate at. Omit for the whole curve." },
          { name: "covariates", type: "object", req: false, desc: "Covariate values for a proportional-hazards model, e.g. {\"temp_C\": 90}." },
        ]}
        example={`curl -X POST ${base}/api/v1/models/MODEL_ID/reliability \\
  -H "Authorization: Bearer rlf_..." -H "Content-Type: application/json" \\
  -d '{"t": 1000}'`}
        returns={`{
  "model": "Bearing life", "unit": "hours",
  "at": { "t": 1000, "reliability": 0.666, "failure": 0.334,
          "hazard": 0.00101, "cumulative_hazard": 0.406, "density": 0.000675 }
}
// without "t":  { "model": …, "unit": …, "curves": { "x": [...], "sf": [...], "ff": [...], "hf": [...], "Hf": [...], "df": [...] } }`}
      />

      <h3>Datasets &amp; fitting</h3>

      <Endpoint
        method="POST"
        path="/api/v1/datasets"
        desc="Create a dataset from CSV text or column arrays."
        request={[
          { name: "name", type: "string", req: true, desc: "Dataset name." },
          { name: "csv", type: "string", req: false, desc: "Raw CSV text (with a header row). Provide this or data." },
          { name: "data", type: "object", req: false, desc: "Column arrays, e.g. {\"hours\": [...], \"failed\": [...]}." },
        ]}
        example={`curl -X POST ${base}/api/v1/datasets \\
  -H "Authorization: Bearer rlf_..." -H "Content-Type: application/json" \\
  -d '{"name": "Bearings", "csv": "hours,failed\\n120,1\\n340,0"}'`}
        returns={`{ "id": "d3…", "name": "Bearings", "n_rows": 2,
  "columns": ["hours", "failed"], "url": "/datasets/d/d3…" }`}
      />

      <Endpoint
        method="POST"
        path="/api/v1/fit"
        desc="Fit and save a model from one of your datasets."
        request={[
          { name: "name", type: "string", req: true, desc: "Model name." },
          { name: "dataset_id", type: "string", req: true, desc: "Id of the dataset to fit." },
          { name: "distribution", type: "string", req: true, desc: "e.g. weibull, lognormal, weibull_ph, discrete_weibull, best." },
          { name: "mapping", type: "object", req: true, desc: "Role → column, e.g. {\"x\": \"hours\", \"c\": \"failed\"}." },
          { name: "unit", type: "string", req: false, desc: "Unit of the time axis." },
          { name: "covariates", type: "string[]", req: false, desc: "Covariate columns for a PH model." },
          { name: "formula", type: "string", req: false, desc: "Formulaic covariate formula (alternative to covariates)." },
        ]}
        example={`curl -X POST ${base}/api/v1/fit \\
  -H "Authorization: Bearer rlf_..." -H "Content-Type: application/json" \\
  -d '{"name": "Bearing life", "dataset_id": "d3…", "distribution": "weibull",
       "mapping": {"x": "hours", "c": "failed"}, "unit": "hours"}'`}
        returns={`{ "id": "a1b2…", "name": "Bearing life", "kind": "distribution",
  "distribution": "Weibull", "n": 2, "unit": "hours",
  "created_at": "…", "url": "/modelling/m/a1b2…" }`}
      />

      <h3>Fleet forecasts</h3>
      <Endpoint
        method="GET"
        path="/api/v1/fleets/{id}/forecast"
        desc="The live failure forecast — expected failures per period. Id is in /fleet/forecasts/<id>."
        request={[{ name: "id", type: "string · path", req: true, desc: "Fleet id." }]}
        returns={`{
  "fleet": { "id": "f1…", "name": "Delivery trucks", "model_id": "a1b2…" },
  "forecast": { "status": "ok", "method": "renewals", "periods": 12,
                "period_label": "months", "expected_failures": [0.4, 0.9, …],
                "total_expected": 11.7 }
}`}
      />

      <h3>Strategy calculators</h3>
      <Endpoint
        method="POST"
        path="/api/v1/strategy/optimal-replacement"
        desc="Cost-optimal preventive-replacement interval."
        request={[
          { name: "distribution_id", type: "string", req: true, desc: "e.g. weibull." },
          { name: "params", type: "number[] | {name,value}[]", req: true, desc: "Distribution parameters." },
          { name: "planned_cost", type: "number", req: true, desc: "Cost of a planned replacement." },
          { name: "unplanned_cost", type: "number", req: true, desc: "Cost of a failure." },
          { name: "unit", type: "string", req: false, desc: "Time unit for display." },
        ]}
        returns={`{ "distribution": "Weibull", "unit": "hours", "mttf": 1272.4,
  "beneficial": true, "optimal_time": 580.5, "optimal_cost_rate": 0.51,
  "planned_cost": 200, "unplanned_cost": 1500 }`}
      />
      <Endpoint
        method="POST"
        path="/api/v1/strategy/failure-finding"
        desc="Inspection interval that keeps a hidden (protective) function available."
        request={[
          { name: "distribution_id", type: "string", req: true, desc: "e.g. exponential." },
          { name: "params", type: "number[] | {name,value}[]", req: true, desc: "Distribution parameters." },
          { name: "target_availability", type: "number", req: true, desc: "Target availability in (0,1), e.g. 0.99." },
          { name: "unit", type: "string", req: false, desc: "Time unit for display." },
        ]}
        returns={`{ "distribution": "Exponential", "unit": "hours", "mttf": 8760,
  "target_availability": 0.99, "interval": 176.4, "method": "…", "note": "…" }`}
      />

      <h3>Push operational data (ingest)</h3>
      <p className="muted-line">
        Append data to existing artifacts — JSON or raw CSV, idempotent, atomic
        (a bad row is a 422 with no changes applied).
      </p>
      <Endpoint
        method="POST"
        path="/api/ingest/fleets/{fleet_id}/usage"
        desc="Update forecast items' current use, then recompute the forecast."
        request={[
          { name: "name / id", type: "csv col", req: true, desc: "Item name (or id)." },
          { name: "current_use", type: "csv col", req: true, desc: "Accumulated use so far." },
          { name: "rate", type: "csv col", req: false, desc: "Optional per-period usage rate." },
        ]}
        example={`curl -X POST ${base}/api/ingest/fleets/FLEET_ID/usage \\
  -H "Authorization: Bearer rlf_..." -H "Content-Type: text/csv" \\
  --data-binary @meter_readings.csv          # name,current_use`}
        returns={`{ "updated": 8, "forecast": { … } }`}
      />
      <Endpoint
        method="POST"
        path="/api/ingest/tracking/{fleet_id}/measurements"
        desc="Append (item, time, value) readings to a tracked fleet and re-predict remaining life."
        request={[
          { name: "measurements", type: "object[]", req: true, desc: "[{item, time, value}, …] (JSON), or CSV columns item,time,value." },
        ]}
        example={`-d '{"measurements": [{"item": "Pump 7", "time": 5300, "value": 6.1}]}'`}
        returns={`{ "updated": 1, "items": [ { … } ] }`}
      />
      <Endpoint
        method="POST"
        path="/api/ingest/datasets/{dataset_id}/lives"
        desc="Append failure rows to a dataset and refit its models in place."
        request={[
          { name: "refit", type: "bool · query", req: false, desc: "Default true; ?refit=false to skip refitting." },
          { name: "(rows)", type: "csv / json", req: true, desc: "Rows whose columns match the dataset." },
        ]}
        returns={`{ "appended": 12, "n_rows": 142, "refit": [ { "id": "…", "name": "…" } ] }`}
      />

      <h3>Model import</h3>
      <Endpoint
        method="POST"
        path="/api/import/models"
        desc="Create a model from a fit done elsewhere (what reliafy.push wraps)."
        request={[
          { name: "name", type: "string", req: true, desc: "Model name." },
          { name: "distribution", type: "string", req: true, desc: "SurPyval name or Reliafy id." },
          { name: "unit", type: "string", req: false, desc: "Time unit." },
          { name: "data", type: "object", req: false, desc: "{x, c?, n?} arrays — refit into a full model. Provide this or params." },
          { name: "params", type: "{name,value}[]", req: false, desc: "Parameters for a params-only model." },
          { name: "options / extras", type: "object", req: false, desc: "offset/zi/lfp (data) or gamma/p/f0 (params)." },
        ]}
        returns={`{ "id": "a1b2…", "name": "Pump bearings", "distribution": "Weibull",
  "params_only": false, "url": "/modelling/m/a1b2…" }`}
      />
    </div>
  );
}

// In-app reference for the programmatic API + the reliafy-client package.
// Examples use the live origin, so self-hosted instances show their own base URL.
export default function ApiReference() {
  const base = (typeof window !== "undefined" && window.location.origin) || "https://reliafy.com";
  const [tab, setTab] = useState("client");

  return (
    <div className="card api-ref">
      <div className="tabs">
        <button className={"tab" + (tab === "client" ? " active" : "")} onClick={() => setTab("client")}>
          reliafy-client (Python)
        </button>
        <button className={"tab" + (tab === "http" ? " active" : "")} onClick={() => setTab("http")}>
          HTTP API
        </button>
      </div>
      {tab === "client" ? <ClientDocs base={base} /> : <HttpDocs base={base} />}
    </div>
  );
}
