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
        <code>reliafy-client</code> turns a fit you did in a notebook into a
        Reliafy model with one call — you keep the full probability plot and
        confidence bounds, and it stays editable, citable as RCM evidence, and
        usable in RBDs and fleet forecasts. Pure standard library; you bring{" "}
        <a className="evidence-link" href="https://github.com/derrynknife/SurPyval" target="_blank" rel="noreferrer">SurPyval</a>{" "}
        to do the fit.
      </p>

      <h3>Install</h3>
      <Code>{`pip install reliafy-client   # installed as reliafy-client, imported as \`reliafy\``}</Code>

      <h3>Authenticate</h3>
      <p className="muted-line">
        Create a personal token under <b>Settings → API access</b> (Pro on
        Reliafy Cloud). Configure it once per session, or set{" "}
        <code>RELIAFY_TOKEN</code> in the environment.
      </p>
      <Code>{`import reliafy

reliafy.configure(token="rlf_...")
# self-hosted instance:
reliafy.configure(token="rlf_...", base_url="${base}")`}</Code>

      <h3>Push a fitted model</h3>
      <p className="muted-line">
        <code>push(model, name, *, data=True, unit=None)</code> uploads a fitted
        SurPyval model and returns the URL to open it. With{" "}
        <code>data=True</code> (default) the fitted observations go up too, so
        Reliafy shows the probability plot and the model stays refittable;{" "}
        <code>data=False</code> uploads parameters only. Offset / limited-failure
        -population / zero-inflated fits are detected and reproduced.
      </p>
      <Code>{`import surpyval as sp
import reliafy

model = sp.Weibull.fit(x=failures, c=censoring_flags)

reliafy.configure(token="rlf_...")
url = reliafy.push(model, name="Pump bearings — 2026 refit", unit="hours")
print(url)                       # open it in Reliafy

reliafy.push(model, name="From a report", data=False)   # params only, no plot`}</Code>

      <h3>Push from parameters</h3>
      <p className="muted-line">
        No SurPyval object — just a distribution id and its parameter values.{" "}
        <code>extras</code> carries <code>gamma</code> / <code>p</code> /{" "}
        <code>f0</code> for offset / LFP / zero-inflated models.
      </p>
      <Code>{`reliafy.push_params("weibull", [1200.0, 2.3], name="Handbook value", unit="hours")
reliafy.push_params("weibull", [1200.0, 2.3], name="With offset", extras={"gamma": 50})`}</Code>

      <h3>Notes</h3>
      <ul className="api-list">
        <li>Supported distributions: Weibull, Exponential, Normal, LogNormal, Gamma, LogLogistic, Exponentiated Weibull, Gumbel, Logistic.</li>
        <li>Errors raise <code>reliafy.ReliafyError</code> (missing token, unreachable host, unsupported distribution, or a server 4xx with its message).</li>
        <li>Under the hood <code>push</code>/<code>push_params</code> call the <code>POST /api/import/models</code> endpoint on the HTTP API tab.</li>
      </ul>
    </div>
  );
}

// ---- Raw HTTP API ----------------------------------------------------------
function HttpDocs({ base }) {
  return (
    <div className="api-section">
      <p className="muted-line">
        Raw endpoints for scripts, cron jobs and CMMS integrations — push meter
        readings, degradation measurements and new failure data straight into
        your Reliafy artifacts. (The <code>reliafy-client</code> package wraps
        the model-import endpoint below.)
      </p>

      <h3>Authentication</h3>
      <p className="muted-line">
        A personal token (<code>rlf_…</code>) from <b>Settings → API access</b>,
        sent as a bearer header. Tokens are <b>write-only</b> — they work on the{" "}
        <code>/api/ingest</code> and <code>/api/import</code> endpoints and
        nothing else.
      </p>
      <Code>{`-H "Authorization: Bearer rlf_your_token_here"`}</Code>

      <h3>Conventions</h3>
      <ul className="api-list">
        <li><b>Body</b>: JSON or a raw CSV (exactly what a CMMS exports) — set <code>Content-Type</code> to <code>application/json</code> or <code>text/csv</code>.</li>
        <li><b>Matching</b>: items match by <code>id</code>, else case-insensitive <code>name</code>.</li>
        <li><b>Atomic</b>: one bad row means a <code>422</code> and no changes applied.</li>
        <li><b>Limits</b>: 120 requests / minute, 5,000 rows / request.</li>
      </ul>

      <h3>Endpoints</h3>

      <Endpoint method="POST" path="/api/ingest/fleets/{fleet_id}/usage">
        <p className="muted-line">
          Update forecast items' current use (and optional rate), then recompute
          the forecast. The id is in the fleet's URL{" "}
          <code>/fleet/forecasts/&lt;id&gt;</code>. Columns:{" "}
          <code>name</code> (or <code>id</code>), <code>current_use</code>,
          optional <code>rate</code>. Returns the recomputed forecast.
        </p>
        <Code>{`curl -X POST ${base}/api/ingest/fleets/FLEET_ID/usage \\
  -H "Authorization: Bearer rlf_..." \\
  -H "Content-Type: text/csv" \\
  --data-binary @meter_readings.csv
# meter_readings.csv:  name,current_use
#                      Truck 01,5230`}</Code>
      </Endpoint>

      <Endpoint method="POST" path="/api/ingest/tracking/{fleet_id}/measurements">
        <p className="muted-line">
          Append <code>(item, time, value)</code> readings to a tracked fleet's
          items and re-predict remaining life. Idempotent — re-sending the same
          export is safe. Id is in <code>/fleet/tracking/&lt;id&gt;</code>.
        </p>
        <Code>{`curl -X POST ${base}/api/ingest/tracking/FLEET_ID/measurements \\
  -H "Authorization: Bearer rlf_..." \\
  -H "Content-Type: application/json" \\
  -d '{"measurements": [{"item": "Pump 7", "time": 5300, "value": 6.1}]}'`}</Code>
      </Endpoint>

      <Endpoint method="POST" path="/api/ingest/datasets/{dataset_id}/lives">
        <p className="muted-line">
          Append failure rows to a dataset (columns must match), then refit every
          model built from it in place — RCM evidence, RBD blocks and forecasts
          update immediately. Add <code>?refit=false</code> to skip refitting.
        </p>
        <Code>{`curl -X POST ${base}/api/ingest/datasets/DATASET_ID/lives \\
  -H "Authorization: Bearer rlf_..." \\
  -H "Content-Type: text/csv" \\
  --data-binary @new_failures.csv`}</Code>
      </Endpoint>

      <Endpoint method="POST" path="/api/import/models">
        <p className="muted-line">
          Create a model from a fit done elsewhere (what <code>reliafy-client</code>{" "}
          wraps). JSON body: <code>name</code>, <code>distribution</code>,
          optional <code>unit</code>; then either <code>data</code> (
          <code>{`{x, c?, n?}`}</code> arrays — refit server-side into a full
          model) or <code>params</code> (<code>{`[{name, value}, …]`}</code>).
          Returns <code>{`{ id, name, distribution, url }`}</code>.
        </p>
        <Code>{`curl -X POST ${base}/api/import/models \\
  -H "Authorization: Bearer rlf_..." \\
  -H "Content-Type: application/json" \\
  -d '{"name": "Pump bearings", "distribution": "weibull",
       "unit": "hours", "data": {"x": [120, 340, 510], "c": [0, 0, 1]}}'`}</Code>
      </Endpoint>

      <h3>Scheduled job (Python)</h3>
      <Code>{`import requests

TOKEN = "rlf_..."          # from Settings → API access
FLEET = "your-fleet-id"

with open("meter_readings.csv", "rb") as f:
    r = requests.post(
        f"${base}/api/ingest/fleets/{FLEET}/usage",
        headers={"Authorization": f"Bearer {TOKEN}",
                 "Content-Type": "text/csv"},
        data=f.read(), timeout=60,
    )
r.raise_for_status()
print(r.json()["forecast"])`}</Code>
    </div>
  );
}

// In-app reference for the ingestion API + the reliafy-client package. Examples
// use the live origin, so self-hosted instances show their own base URL.
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
