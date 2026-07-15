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

function Endpoint({ method, path, children }) {
  return (
    <div className="api-ep">
      <div className="api-ep-head">
        <span className={`api-method ${method.toLowerCase()}`}>{method}</span>
        <code className="api-path">{path}</code>
      </div>
      {children}
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
      <p className="muted-line">
        Create a token under <b>Settings → API access</b> (Pro on Reliafy Cloud).
      </p>

      <h3>Push a fitted model</h3>
      <p className="muted-line">
        <code>push(model, name, *, data=True, unit=None)</code> uploads a SurPyval
        model and returns its URL. <code>data=True</code> (default) sends the
        fitted observations too, so Reliafy shows the probability plot and the
        model stays refittable; <code>data=False</code> is parameters only.
        Offset / LFP / zero-inflated fits are detected and reproduced.
      </p>
      <Code>{`import surpyval as sp, reliafy
model = sp.Weibull.fit(x=failures, c=censoring_flags)
url = reliafy.push(model, name="Pump bearings — 2026", unit="hours")

# no SurPyval object — just numbers:
reliafy.push_params("weibull", [1200.0, 2.3], name="Handbook value", unit="hours")`}</Code>

      <h3>Read your models &amp; reliability</h3>
      <Code>{`reliafy.list_models()                       # [{id, name, distribution, ...}, ...]
m = reliafy.get_model(model_id)             # params (+CIs), metrics, goodness-of-fit

r = reliafy.reliability(model_id, t=1000)   # {"at": {reliability, failure, hazard, ...}}
print(r["at"]["reliability"])               # R(1000)

# proportional-hazards model at a covariate combination:
reliafy.reliability(model_id, t=1000, covariates={"temp_C": 90, "load": 0.8})`}</Code>

      <h3>Create a dataset &amp; fit</h3>
      <Code>{`ds = reliafy.upload_dataset("Bearings", csv="hours,failed\\n120,1\\n340,0\\n510,1")
#   or:  reliafy.upload_dataset("Bearings", data={"hours": [...], "failed": [...]})

model = reliafy.fit(ds["id"], "weibull", "Bearing life",
                    mapping={"x": "hours", "c": "failed"}, unit="hours")
print(model["url"])`}</Code>

      <h3>Fleet &amp; strategy</h3>
      <Code>{`reliafy.fleet_forecast(fleet_id)            # expected failures per period

reliafy.optimal_replacement("weibull", [1435, 2.5],
                            planned_cost=200, unplanned_cost=1500, unit="hours")
reliafy.failure_finding("exponential", [1/8760], target_availability=0.99, unit="hours")`}</Code>

      <h3>Notes</h3>
      <ul className="api-list">
        <li>Supported distributions for <code>push</code>: Weibull, Exponential, Normal, LogNormal, Gamma, LogLogistic, Exponentiated Weibull, Gumbel, Logistic.</li>
        <li>Errors raise <code>reliafy.ReliafyError</code> (missing token, unreachable host, or a server 4xx with its message).</li>
        <li>Every call maps to an endpoint on the HTTP API tab; reads and writes are scoped to your own data.</li>
      </ul>
    </div>
  );
}

// ---- Raw HTTP API ----------------------------------------------------------
function HttpDocs({ base }) {
  return (
    <div className="api-section">
      <p className="muted-line">
        Token-authed endpoints scoped to your own data — read models and
        reliability, create datasets and fit, read fleet forecasts, run strategy
        calculators, and push operational data. The <code>reliafy-client</code>{" "}
        package wraps these.
      </p>

      <h3>Authentication</h3>
      <p className="muted-line">
        A personal token (<code>rlf_…</code>) from <b>Settings → API access</b>,
        sent as a bearer header. Tokens read and write <b>your own</b> data —
        they can't touch the account, billing, tokens, or team artifacts.
      </p>
      <Code>{`-H "Authorization: Bearer rlf_your_token_here"`}</Code>

      <h3>Conventions</h3>
      <ul className="api-list">
        <li><b>Bodies</b> are JSON; the data-push endpoints also accept raw CSV (<code>Content-Type: text/csv</code>) as a CMMS exports it.</li>
        <li><b>Scope</b>: reads see your models/datasets/fleets (plus shared samples); writes create under your account.</li>
        <li><b>Errors</b>: a bad request is a <code>422</code> with a message; unknown/foreign ids are <code>404</code>.</li>
        <li><b>Limits</b>: 120 requests / minute per user.</li>
      </ul>

      <h3>Models &amp; reliability</h3>
      <Endpoint method="GET" path="/api/v1/models">
        <p className="muted-line">List your saved models.</p>
      </Endpoint>
      <Endpoint method="GET" path="/api/v1/models/{id}">
        <p className="muted-line">
          A model's fit: <code>params</code> (with 95% CIs),{" "}
          <code>coefficients</code> (PH), <code>metrics</code>, <code>gof</code>.
        </p>
      </Endpoint>
      <Endpoint method="POST" path="/api/v1/models/{id}/reliability">
        <p className="muted-line">
          Evaluate reliability. Body: optional <code>t</code>, and{" "}
          <code>covariates</code> for a PH model. With <code>t</code> you get{" "}
          <code>{`{ at: { reliability, failure, hazard, cumulative_hazard, density } }`}</code>;
          without it, the full function grid.
        </p>
        <Code>{`curl -X POST ${base}/api/v1/models/MODEL_ID/reliability \\
  -H "Authorization: Bearer rlf_..." -H "Content-Type: application/json" \\
  -d '{"t": 1000}'`}</Code>
      </Endpoint>

      <h3>Datasets &amp; fitting</h3>
      <Endpoint method="POST" path="/api/v1/datasets">
        <p className="muted-line">
          Create a dataset. Body: <code>name</code> plus <code>csv</code> (text)
          or <code>data</code> (column arrays). Returns{" "}
          <code>{`{ id, n_rows, columns, url }`}</code>.
        </p>
        <Code>{`curl -X POST ${base}/api/v1/datasets \\
  -H "Authorization: Bearer rlf_..." -H "Content-Type: application/json" \\
  -d '{"name": "Bearings", "csv": "hours,failed\\n120,1\\n340,0"}'`}</Code>
      </Endpoint>
      <Endpoint method="POST" path="/api/v1/fit">
        <p className="muted-line">
          Fit and save a model from a dataset. Body: <code>name</code>,{" "}
          <code>dataset_id</code>, <code>distribution</code>,{" "}
          <code>mapping</code>, optional <code>unit</code> /{" "}
          <code>covariates</code> / <code>formula</code>.
        </p>
        <Code>{`curl -X POST ${base}/api/v1/fit \\
  -H "Authorization: Bearer rlf_..." -H "Content-Type: application/json" \\
  -d '{"name": "Bearing life", "dataset_id": "DS_ID", "distribution": "weibull",
       "mapping": {"x": "hours", "c": "failed"}, "unit": "hours"}'`}</Code>
      </Endpoint>

      <h3>Fleet forecasts</h3>
      <Endpoint method="GET" path="/api/v1/fleets/{id}/forecast">
        <p className="muted-line">
          The live forecast — expected failures per period, spares demand. Id is
          in <code>/fleet/forecasts/&lt;id&gt;</code>.
        </p>
      </Endpoint>

      <h3>Strategy calculators</h3>
      <Endpoint method="POST" path="/api/v1/strategy/optimal-replacement">
        <p className="muted-line">
          Body: <code>distribution_id</code>, <code>params</code>,{" "}
          <code>planned_cost</code>, <code>unplanned_cost</code>, optional{" "}
          <code>unit</code>. Returns the optimal interval and cost rate.
        </p>
      </Endpoint>
      <Endpoint method="POST" path="/api/v1/strategy/failure-finding">
        <p className="muted-line">
          Body: <code>distribution_id</code>, <code>params</code>,{" "}
          <code>target_availability</code>, optional <code>unit</code>.
        </p>
      </Endpoint>

      <h3>Push operational data (ingest)</h3>
      <p className="muted-line">
        Append data to existing artifacts from cron jobs / CMMS exports — JSON or
        raw CSV, idempotent, atomic (a bad row is a 422 with no changes).
      </p>
      <Endpoint method="POST" path="/api/ingest/fleets/{fleet_id}/usage">
        <p className="muted-line">
          Update forecast items' current use (columns <code>name</code>,{" "}
          <code>current_use</code>, optional <code>rate</code>) and recompute.
        </p>
        <Code>{`curl -X POST ${base}/api/ingest/fleets/FLEET_ID/usage \\
  -H "Authorization: Bearer rlf_..." -H "Content-Type: text/csv" \\
  --data-binary @meter_readings.csv          # name,current_use`}</Code>
      </Endpoint>
      <Endpoint method="POST" path="/api/ingest/tracking/{fleet_id}/measurements">
        <p className="muted-line">
          Append <code>(item, time, value)</code> readings to a tracked fleet and
          re-predict remaining life.
        </p>
      </Endpoint>
      <Endpoint method="POST" path="/api/ingest/datasets/{dataset_id}/lives">
        <p className="muted-line">
          Append failure rows to a dataset and refit its models in place
          (<code>?refit=false</code> to skip).
        </p>
      </Endpoint>

      <h3>Model import</h3>
      <Endpoint method="POST" path="/api/import/models">
        <p className="muted-line">
          Create a model from a fit done elsewhere (what <code>reliafy.push</code>{" "}
          wraps). JSON: <code>name</code>, <code>distribution</code>, optional{" "}
          <code>unit</code>; then <code>data</code> (<code>{`{x, c?, n?}`}</code>)
          or <code>params</code> (<code>{`[{name, value}]`}</code>).
        </p>
      </Endpoint>

      <h3>Scheduled job (Python, no dependencies)</h3>
      <Code>{`import requests

TOKEN = "rlf_..."
with open("meter_readings.csv", "rb") as f:
    r = requests.post(
        "${base}/api/ingest/fleets/FLEET_ID/usage",
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "text/csv"},
        data=f.read(), timeout=60,
    )
r.raise_for_status()`}</Code>
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
