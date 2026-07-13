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

// In-app reference for the ingestion API. Examples use the live origin, so
// self-hosted instances show their own base URL.
export default function ApiReference() {
  const base = (typeof window !== "undefined" && window.location.origin) || "https://reliafy.com";

  return (
    <div className="card api-ref" style={{ marginTop: "1rem" }}>
      <h2>Using the API</h2>
      <p className="muted-line">
        Push meter readings, degradation measurements, and new failure data from
        your own scripts and cron jobs. Full reference:{" "}
        <a className="evidence-link" href="https://github.com/Reliafy/reliafy/blob/main/docs/api.md" target="_blank" rel="noreferrer">
          docs/api.md
        </a>.
      </p>

      <h3>Authentication</h3>
      <p className="muted-line">
        Send your token as a bearer header. Tokens are write-only — they work on
        the <code>/api/ingest</code> endpoints and nothing else.
      </p>
      <Code>{`-H "Authorization: Bearer rlf_your_token_here"`}</Code>

      <h3>Request bodies</h3>
      <p className="muted-line">
        Every endpoint accepts JSON or a raw CSV body (exactly what a CMMS
        exports). Items match by <code>id</code>, else case-insensitive
        <code> name</code>. A bad row means a 422 and no changes. Limits: 120
        requests/minute, 5,000 rows/request.
      </p>

      <h3>Endpoints</h3>

      <Endpoint method="POST" path="/api/ingest/fleets/{fleet_id}/usage">
        <p className="muted-line">
          Update forecast items' current use (and optional rate), then recompute
          the forecast. The id is in the fleet's URL: <code>/fleet/forecasts/&lt;id&gt;</code>.
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
          Append <code>(time, value)</code> readings to a tracked fleet's items
          and re-predict remaining life. Idempotent — re-sending the same export
          is safe. Id is in <code>/fleet/tracking/&lt;id&gt;</code>.
        </p>
        <Code>{`curl -X POST ${base}/api/ingest/tracking/FLEET_ID/measurements \\
  -H "Authorization: Bearer rlf_..." \\
  -H "Content-Type: application/json" \\
  -d '{"measurements": [{"item": "Pump 7", "time": 5300, "value": 6.1}]}'`}</Code>
      </Endpoint>

      <Endpoint method="POST" path="/api/ingest/datasets/{dataset_id}/lives">
        <p className="muted-line">
          Append failure rows to a dataset (columns must match), then refit every
          model built from it in place — RCM evidence, RBD blocks, and forecasts
          update immediately. Add <code>?refit=false</code> to skip refitting.
        </p>
        <Code>{`curl -X POST ${base}/api/ingest/datasets/DATASET_ID/lives \\
  -H "Authorization: Bearer rlf_..." \\
  -H "Content-Type: text/csv" \\
  --data-binary @new_failures.csv`}</Code>
      </Endpoint>

      <h3>Python (scheduled job)</h3>
      <Code>{`import requests

TOKEN = "rlf_..."          # from this page
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
