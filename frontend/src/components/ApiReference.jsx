import { useEffect, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { useAppConfig } from "../ConfigProvider.jsx";
import { countActions, toolsFromSpec } from "../apiSpec.js";
import { API_DOCS_PAGES, apiDocsNeighbours, apiDocsPath, legacyApiDocsTarget } from "../apiDocsPages.js";
import McpOnRequest from "./McpOnRequest.jsx";
import Tabs from "./ui/Tabs.jsx";

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

// An entry that folds: the head stays in view and the detail opens on a
// click, so a page of many endpoints stays short. The detail is still in the
// page (and the prerendered HTML) for search and find-in-page.
function Fold({ fold, head, children }) {
  if (!fold) {
    return (
      <div className="api-ep">
        {head}
        {children}
      </div>
    );
  }
  return (
    <details className="api-ep api-fold">
      <summary>{head}</summary>
      {children}
    </details>
  );
}

// One endpoint, OpenAPI-style: method + path, description, request fields, an
// example, and the response shape. ``fold``: the description shows; the rest
// opens on a click.
function Endpoint({ method, path, desc, request, example, returns, fold = false }) {
  const head = (
    <div className="api-ep-head">
      <span className={`api-method ${method.toLowerCase()}`}>{method}</span>
      <code className="api-path">{path}</code>
    </div>
  );
  return (
    <Fold fold={fold} head={<>{head}{fold && desc && <p className="muted-line api-ep-desc">{desc}</p>}</>}>
      {!fold && desc && <p className="muted-line api-ep-desc">{desc}</p>}
      <Fields title="Request" rows={request} />
      {example && <Code>{example}</Code>}
      {returns && (
        <div className="api-fields">
          <div className="api-fields-h">Response · 200</div>
          <Code>{returns}</Code>
        </div>
      )}
    </Fold>
  );
}

// One client function, matching the endpoint layout: signature, description,
// a Parameters table, and Returns. ``endpoint`` shows the HTTP call it maps to.
function ClientFn({ sig, endpoint, desc, params, returns, fold = false }) {
  const head = (
    <div className="api-ep-head api-fn-head">
      <code className="api-path api-sig">{sig}</code>
      {endpoint && <span className="api-maps">{endpoint}</span>}
    </div>
  );
  return (
    <Fold fold={fold} head={<>{head}{fold && desc && <p className="muted-line api-ep-desc">{desc}</p>}</>}>
      {!fold && desc && <p className="muted-line api-ep-desc">{desc}</p>}
      <Fields title="Parameters" rows={params} />
      {returns && (
        <div className="api-fields">
          <div className="api-fields-h">Returns</div>
          <Code>{returns}</Code>
        </div>
      )}
    </Fold>
  );
}

// ---- reliafy-client (Python package) ---------------------------------------
function ClientDocs() {
  return (
    <div className="api-section">
      <p className="muted-line">
        <code>reliafy-client</code> is the Python client for the API, and it installs the{" "}
        <code>reliafy</code> command line too. Pure standard library, no dependencies; you bring{" "}
        <a className="evidence-link" href="https://github.com/derrynknife/SurPyval" target="_blank" rel="noreferrer">SurPyval</a>{" "}
        (<a className="evidence-link" href="https://surpyval.readthedocs.io/en/latest/" target="_blank" rel="noreferrer">docs</a>)
        for your own fits.
      </p>

      <h3>Install and sign in</h3>
      <Code>{`pip install reliafy-client        # installed as reliafy-client, imported as \`reliafy\`

from reliafy import Client
rf = Client(token="rlf_...")      # or RELIAFY_TOKEN, or the token saved by \`reliafy login\``}</Code>
      <ul className="api-list">
        <li>
          Version 0.3 needs a Reliafy server with the tools API: reliafy.com has it from this
          release; a self-hosted server needs a build where <code>GET /api/v1/tools</code> answers.
          Against an older server the new calls stop with <code>reliafy.ServerTooOld</code>, and
          everything from 0.2 keeps working.
        </li>
        <li>Self-hosted: <code>Client(base_url="https://reliafy.example.com")</code>. A local server with sign-in off needs no token.</li>
      </ul>

      <h3>Every tool: Client.call</h3>
      <ClientFn
        sig="Client.call(tool, action=None, /, wait=False, **args)"
        endpoint="POST /api/v1/{tool}/{action}"
        desc="Call any tool action with its arguments, exactly as the Claude connector does. Leave out action for a tool without actions. wait=True (or a number of seconds) polls a long-running job until it finishes."
        params={[
          { name: "tool", type: "str", req: true, desc: "The tool, e.g. \"life_data_analysis\"." },
          { name: "action", type: "str", req: false, desc: "The action (or kind), e.g. \"fit\"." },
          { name: "wait", type: "bool | float", req: false, desc: "Wait for a job_id result to finish (True, or at most this many seconds)." },
          { name: "**args", type: "any", req: false, desc: "The action's arguments; None values are left out." },
        ]}
        returns={`{ … }   # the tool's result, the same JSON an AI assistant gets`}
      />
      <Code>{`rf.call("list", "models")
rf.call("life_data_analysis", "fit", distribution="weibull",
        data=[120, 340, 510, 700, 980], censored=[0, 0, 1, 0, 0], unit="hours")
rf.call("guide", topic="life_data")                       # a tool without actions
rf.call("rbd_analysis", "analyze", rbd_id="…", simulate=True, wait=True)

rf.tools()     # the tools and actions you may call (GET /api/v1/tools)
rf.spec()      # the OpenAPI spec`}</Code>
      <ul className="api-list">
        <li>Shortcuts: <code>rf.list(kind)</code>, <code>rf.get(kind, id)</code>, <code>rf.fit(data, distribution=…, censored=…)</code>, <code>rf.reliability(model_id, times)</code>, <code>rf.guide(topic)</code>, <code>rf.wait(job_id)</code>.</li>
        <li><code>reliafy.call(tool, action, **args)</code> does the same with the configured token.</li>
        <li>A refused call raises <code>reliafy.ReliafyError</code> with <code>status</code> (the HTTP status) and <code>detail</code> (what Reliafy said).</li>
      </ul>

      <h3 id="files">Files, photos and data</h3>
      <Code>{`rf.upload_dataset("bearings.xlsx", name="Bearings")     # CSV or .xlsx, as a dataset
rf.import_rbd("plant.xml")                              # BlockSim, Open-PSA, Galileo, RePyability, the Excel template
rf.import_excel("fmea.xlsx", target="rcm", position_id="…")  # dataset, rcm (onto a position) or rbd
rf.add_photo("nameplate.jpg", target_id="…")            # Reliafy Maintenance users
rf.add_document("manual.pdf", target_id="…")             # a PDF on an item or position (at most 20 MB)

rf.push_usage(fleet_id, [{"name": "Truck 01", "current_use": 5230}])
rf.push_measurements(tracked_fleet_id, file="readings.csv")
rf.push_lives(dataset_id, file="new_failures.csv")      # appends, then refits its models`}</Code>
      <p className="muted-line">
        Files are streamed from disk. The ingest helpers take rows, <code>csv=</code> text or{" "}
        <code>file=</code> a path, and are also on the module (<code>reliafy.push_usage(…)</code>).
        Reliafy Maintenance users also have <code>push_readings</code> for meter and condition readings.
      </p>

      <h3>The 0.2 functions (still supported)</h3>
      <p className="muted-line">
        Everything from 0.2 works unchanged, on any server: <code>reliafy.configure(token=…)</code>,
        then the functions below. Each maps to one of the original routes; open one for its
        parameters and what it returns.
      </p>

      <h3>reliafy.models</h3>

      <ClientFn
        fold
        sig="models.push(model, name, *, data=True, unit=None)"
        endpoint="POST /api/import/models"
        desc="Push a fitted SurPyval model and return its URL."
        params={[
          { name: "model", type: "SurPyval model", req: true, desc: "A fitted SurPyval distribution." },
          { name: "name", type: "str", req: true, desc: "Model name." },
          { name: "data", type: "bool", req: false, desc: "Upload the fitted observations too (default True → full plot, refittable). False = params only." },
          { name: "unit", type: "str", req: false, desc: "Unit of the time axis." },
        ]}
        returns={`"https://reliafy.com/models/m/a1b2…"   # str — open in the app`}
      />

      <ClientFn
        fold
        sig="models.push_params(distribution, params, name, *, unit=None, extras=None)"
        endpoint="POST /api/import/models"
        desc="Push a model by distribution + parameter values (no SurPyval object)."
        params={[
          { name: "distribution", type: "str", req: true, desc: "e.g. \"weibull\"." },
          { name: "params", type: "number[] | {name,value}[]", req: true, desc: "Parameter values." },
          { name: "name", type: "str", req: true, desc: "Model name." },
          { name: "unit", type: "str", req: false, desc: "Time unit." },
          { name: "extras", type: "dict", req: false, desc: "gamma / p / f0 for offset / LFP / zero-inflation." },
        ]}
        returns={`"https://reliafy.com/models/m/…"   # str`}
      />

      <ClientFn
        fold
        sig="models.list()"
        endpoint="GET /api/v1/models"
        desc="Your saved models."
        returns={`[ { "id": "a1b2…", "name": "Bearing life", "distribution": "Weibull",
    "kind": "distribution", "n": 30, "unit": "hours", "url": "/models/m/…" }, … ]`}
      />

      <ClientFn
        fold
        sig="models.get(model_id)"
        endpoint="GET /api/v1/models/{id}"
        desc="One model's fit."
        params={[{ name: "model_id", type: "str", req: true, desc: "Model id." }]}
        returns={`{ "id": …, "distribution": "Weibull", "params": [{name, value, se, ci}],
  "coefficients": [], "metrics": null, "gof": [{id, label, value}] }`}
      />

      <ClientFn
        fold
        sig="models.reliability(model_id, t=None, covariates=None)"
        endpoint="POST /api/v1/models/{id}/reliability"
        desc="Evaluate the reliability functions."
        params={[
          { name: "model_id", type: "str", req: true, desc: "Model id." },
          { name: "t", type: "number", req: false, desc: "Time to evaluate at. Omit for the whole curve." },
          { name: "covariates", type: "dict", req: false, desc: "Covariate values for a proportional-hazards model." },
        ]}
        returns={`{ "at": { "reliability": 0.666, "failure": 0.334, "hazard": …,
          "cumulative_hazard": …, "density": … } }   # or {"curves": {...}}`}
      />

      <ClientFn
        fold
        sig="models.fit(dataset_id, distribution, name, *, mapping=None, unit=None, covariates=None, formula=None)"
        endpoint="POST /api/v1/fit"
        desc="Fit and save a model from one of your datasets."
        params={[
          { name: "dataset_id", type: "str", req: true, desc: "Dataset to fit." },
          { name: "distribution", type: "str", req: true, desc: "e.g. weibull, weibull_ph, best." },
          { name: "name", type: "str", req: true, desc: "Model name." },
          { name: "mapping", type: "dict", req: true, desc: "Role → column, e.g. {\"x\": \"hours\", \"c\": \"failed\"}." },
          { name: "unit", type: "str", req: false, desc: "Time unit." },
          { name: "covariates", type: "str[]", req: false, desc: "Covariate columns (PH)." },
          { name: "formula", type: "str", req: false, desc: "Formulaic covariate formula." },
        ]}
        returns={`{ "id": …, "name": "Bearing life", "distribution": "Weibull", "url": "/models/m/…" }`}
      />

      <h3>reliafy.data</h3>
      <ClientFn
        fold
        sig="data.upload(name, *, csv=None, data=None)"
        endpoint="POST /api/v1/datasets"
        desc="Create a dataset from CSV text or column arrays."
        params={[
          { name: "name", type: "str", req: true, desc: "Dataset name." },
          { name: "csv", type: "str", req: false, desc: "Raw CSV text (with a header). Provide this or data." },
          { name: "data", type: "dict", req: false, desc: "Column arrays, e.g. {\"hours\": [...], \"failed\": [...]}." },
        ]}
        returns={`{ "id": "d3…", "name": "Bearings", "n_rows": 8, "columns": ["hours","failed"], "url": "/data/…" }`}
      />

      <h3>reliafy.strategy</h3>
      <ClientFn
        fold
        sig="strategy.optimal_replacement(distribution, params, planned_cost, unplanned_cost, *, unit=None)"
        endpoint="POST /api/v1/strategy/optimal-replacement"
        desc="Cost-optimal preventive-replacement interval."
        params={[
          { name: "distribution", type: "str", req: true, desc: "e.g. weibull." },
          { name: "params", type: "number[]", req: true, desc: "Distribution parameters." },
          { name: "planned_cost", type: "number", req: true, desc: "Cost of a planned replacement." },
          { name: "unplanned_cost", type: "number", req: true, desc: "Cost of a failure." },
          { name: "unit", type: "str", req: false, desc: "Time unit." },
        ]}
        returns={`{ "optimal_time": 580.5, "optimal_cost_rate": 0.51, "beneficial": true, "mttf": 1272.4 }`}
      />
      <ClientFn
        fold
        sig="strategy.failure_finding(distribution, params, target_availability, *, unit=None)"
        endpoint="POST /api/v1/strategy/failure-finding"
        desc="Inspection interval for a hidden (protective) function."
        params={[
          { name: "distribution", type: "str", req: true, desc: "e.g. exponential." },
          { name: "params", type: "number[]", req: true, desc: "Distribution parameters." },
          { name: "target_availability", type: "number", req: true, desc: "Target availability in (0,1), e.g. 0.99." },
          { name: "unit", type: "str", req: false, desc: "Time unit." },
        ]}
        returns={`{ "interval": 176.4, "method": "…", "mttf": 8760, "target_availability": 0.99 }`}
      />
      <ClientFn
        fold
        sig="strategy.demonstration_test(reliability, *, confidence=0.95, mission_time=None, failures=0, test_multiple=1.0, shape=None, units=None, method='attribute', mtbf=None, design_reliability=None, design_mtbf=None, producer_risk=None, unit=None, b_life=None, shape_interval=None)"
        endpoint="POST /api/v1/strategy/demonstration-test"
        desc="Plan a reliability demonstration test: units to test, test time per unit, allowed failures."
        params={[
          { name: "reliability", type: "number", req: true, desc: "Reliability to show over one mission, in (0,1)." },
          { name: "confidence", type: "number", req: false, desc: "Confidence in (0,1), default 0.95." },
          { name: "mission_time", type: "number", req: false, desc: "The mission the reliability is over." },
          { name: "failures", type: "int", req: false, desc: "Failures allowed, default 0 (success run)." },
          { name: "test_multiple / shape", type: "number", req: false, desc: "Test each unit k missions, Weibull shape known." },
          { name: "units", type: "int", req: false, desc: "Units available: solve for test time per unit (needs shape)." },
          { name: "design_reliability / design_mtbf", type: "number", req: false, desc: "A good design's true reliability (or MTBF): its chance of passing." },
          { name: "producer_risk", type: "number", req: false, desc: "With the good design: the most chance of failing it, e.g. 0.2. The plan keeps both risks and chooses the failures allowed." },
          { name: "b_life", type: "number", req: false, desc: "A B-life requirement instead of reliability: 10 for “B10 ≥ mission_time”." },
          { name: "shape_interval", type: "number[2]", req: false, desc: "β’s interval [lower, upper]: adds shape_sensitivity, warning when β is too poorly known for the plan." },
        ]}
        returns={`{ "units": 128, "failures": 8, "consumer_risk": 0.097, "producer_risk": 0.192, "summary": "Test 128 units…", "oc_curve": {…}, "tradeoff": {…} }`}
      />

      <h3>reliafy.fleet</h3>
      <ClientFn
        fold
        sig="fleet.forecast(fleet_id)"
        endpoint="GET /api/v1/fleets/{id}/forecast"
        desc="The live failure forecast for one of your fleets."
        params={[{ name: "fleet_id", type: "str", req: true, desc: "Fleet id (from /forecasts/<id>)." }]}
        returns={`{ "fleet": {id, name, model_id}, "forecast": {status, method, periods, expected_failures, …} }`}
      />

      <ul className="api-list">
        <li>Errors raise <code>reliafy.ReliafyError</code>; reads/writes are scoped to your own data.</li>
        <li>Full request and response field tables are on <Link className="evidence-link" to={apiDocsPath("v1-routes")}>Original routes and ingest</Link>.</li>
      </ul>
    </div>
  );
}

// ---- Raw HTTP API ----------------------------------------------------------
function HttpDocs({ base }) {
  return (
    <div className="api-section">
      <p className="muted-line">
        <b>Still supported.</b> The nine original routes below and the ingest routes keep working
        exactly as before, with the same token and scopes. For anything new, use{" "}
        <Link className="evidence-link" to={apiDocsPath("tools")}>the tools API</Link>: it covers all of these and much more.
      </p>
      <ul className="api-list">
        <li>Bodies are JSON; the ingest routes also take raw CSV (<code>Content-Type: text/csv</code>).</li>
        <li>Open a route for its fields, an example and its response.</li>
        <li>Errors: <code>422</code> (bad input, with a message), <code>404</code> (unknown or someone else’s id), <code>401</code> (bad token), <code>403</code> (the token lacks the scope), <code>429</code> (over 120 requests a minute).</li>
      </ul>

      <h3>Models &amp; reliability</h3>

      <Endpoint
        fold
        method="GET"
        path="/api/v1/models"
        desc="List your saved models (life-data and degradation)."
        returns={`{
  "models": [
    { "id": "a1b2…", "name": "Bearing life", "kind": "distribution",
      "distribution": "Weibull", "n": 30, "unit": "hours",
      "created_at": "2026-07-15T02:48:08+00:00", "url": "/models/m/a1b2…" }
  ]
}`}
      />

      <Endpoint
        fold
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
  "gof": [ { "id": "aic", "label": "AIC", "value": 466.3 }, … ],
  "validation": { … }          // regression models only: how good is this model?
                               // {available, concordance: {value, rating, reading},
                               //  brier: {model, baseline, improvement, from, to, reading},
                               //  auc: [{time, value}], n_units, sampled, note}
                               // or {available: false, reason}
  "diagnostics": { … }         // regression models only: does the model hold?
                               // {ph_test: {available, verdict, title, reading,
                               //            rows: [{covariate, statistic, df, p}],
                               //            global: {statistic, df, p}},
                               //  robust?, ties?, strata?}   (Cox PH adds the last three)
}`}
      />

      <Endpoint
        fold
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
        fold
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
  "columns": ["hours", "failed"], "url": "/data/d3…" }`}
      />

      <Endpoint
        fold
        method="POST"
        path="/api/v1/fit"
        desc="Fit and save a model from one of your datasets."
        request={[
          { name: "name", type: "string", req: true, desc: "Model name." },
          { name: "dataset_id", type: "string", req: true, desc: "Id of the dataset to fit." },
          { name: "distribution", type: "string", req: true, desc: "e.g. weibull, lognormal, weibull_ph, discrete_weibull, best. Every id is listed in the model reference: bounded (beta, uniform), discretized, royston_parmar, the semi-parametric additive_hazards / proportional_odds / buckley_james, and shared frailty (weibull_frailty, cox_frailty, …)." },
          { name: "mapping", type: "object", req: true, desc: "Role → column, e.g. {\"x\": \"hours\", \"c\": \"failed\"}. Covariates that change over time (regression models): add \"i\", the item column, with each row's start and stop as \"xl\" / \"xr\" (or a timeline's times as \"x\"). A shared-frailty model also takes \"group\": the site or batch column." },
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
  "created_at": "…", "url": "/models/m/a1b2…" }`}
      />

      <h3>Fleet forecasts</h3>
      <Endpoint
        fold
        method="GET"
        path="/api/v1/fleets/{id}/forecast"
        desc="The live failure forecast — expected failures per period. Id is in /forecasts/<id>."
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
        fold
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
        fold
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
      <Endpoint
        fold
        method="POST"
        path="/api/v1/strategy/demonstration-test"
        desc="Plan a reliability demonstration test (success run, binomial, Weibayes or MTBF)."
        request={[
          { name: "reliability", type: "number", req: true, desc: "Reliability to show over one mission, in (0,1) (attribute tests)." },
          { name: "confidence", type: "number", req: false, desc: "Confidence in (0,1), default 0.95." },
          { name: "mission_time", type: "number", req: false, desc: "The mission time; omit to plan in missions." },
          { name: "failures", type: "int", req: false, desc: "Failures the test allows, default 0." },
          { name: "test_multiple", type: "number", req: false, desc: "Test length per unit in missions (needs shape when not 1)." },
          { name: "shape", type: "number", req: false, desc: "Weibull shape β of the lifetime, assumed known." },
          { name: "units", type: "int", req: false, desc: "Units available: solve for the test time per unit instead." },
          { name: "method / mtbf", type: "string / number", req: false, desc: "method=\"mtbf\" with an MTBF plans a constant-rate (chi-squared) test." },
          { name: "design_reliability", type: "number", req: false, desc: "A design's true reliability: its chance of passing." },
          { name: "b_life", type: "number", req: false, desc: "A B-life requirement instead of reliability: 10 for “B10 ≥ mission_time”." },
          { name: "shape_interval", type: "number[2]", req: false, desc: "β’s interval [lower, upper] (e.g. a fit’s 95% interval): adds shape_sensitivity, with a warning when β is too poorly known for the plan." },
          { name: "unit", type: "string", req: false, desc: "Time unit for display." },
        ]}
        returns={`{ "method": "attribute", "solve_for": "units", "units": 59,
  "test_time_per_unit": 1000, "total_test_time": 59000, "failures": 0,
  "demonstrated_reliability": 0.9505, "consumer_risk": 0.0485,
  "summary": "Test 59 units for 1,000 hours each with no failures to show …",
  "assumptions": ["…"], "tradeoff": { "failures": [0,1,2,3], "rows": [{ "label": "1,000 hours (1×)", "values": [59,93,124,153] }] } }`}
      />

      <h3>Push operational data (ingest)</h3>
      <p className="muted-line">
        Append data to existing artifacts — JSON or raw CSV, idempotent, atomic
        (a bad row is a 422 with no changes applied).
      </p>
      <Endpoint
        fold
        method="POST"
        path="/api/ingest/fleets/{fleet_id}/usage"
        desc="Update forecast items' current use, then recompute the forecast and check the fleet's alerts."
        request={[
          { name: "name / id", type: "csv col", req: true, desc: "Item name (or id)." },
          { name: "current_use", type: "csv col", req: true, desc: "Accumulated use so far (the meter reading)." },
          { name: "rate", type: "csv col", req: false, desc: "Optional manual per-period usage rate." },
          { name: "read_at", type: "csv col", req: false, desc: "When the meter was read, ISO 8601 (e.g. 2026-09-27T08:00:00+10:00; no offset = UTC). Default: the request time. Readings older than the item's latest are ignored." },
        ]}
        example={`curl -X POST ${base}/api/ingest/fleets/FLEET_ID/usage \\
  -H "Authorization: Bearer rlf_..." -H "Content-Type: text/csv" \\
  --data-binary @meter_readings.csv          # name,current_use,read_at`}
        returns={`{ "fleet": "…", "updated_items": 8, "forecast": { … }, "alerts_fired": 0 }`}
      />
      <ul className="api-list">
        <li>
          <b>Usage-rate estimate.</b> Each reading at least a day after the previous one updates the item's
          estimated usage per period: Δuse ÷ elapsed periods, smoothed (EWMA, α = 0.3). Elapsed time is
          converted with the fleet's period label — days, weeks, months (30.44 d), quarters or years; any other
          label gets no estimate. A reading lower than the last one (meter reset or replaced unit) restarts the
          baseline without estimating.
        </li>
        <li>
          <b><code>rate_source</code></b> (fleet setting, <code>"manual"</code> by default): set it to{" "}
          <code>"estimated"</code> on the fleet page to forecast with each item's estimated rate, falling back
          to its manual rate, then the fleet default. The forecast's <code>per_item</code> rows report{" "}
          <code>rate_used</code> and <code>rate_basis</code>.
        </li>
        <li>
          <b>Alerts.</b> Ingesting usage evaluates the fleet's alert rules (set on the fleet page) against the
          recomputed forecast and emails their owners — one email per crossing. <code>alerts_fired</code> counts
          the rules that fired; an alert problem never fails the ingest.
        </li>
      </ul>
      <Endpoint
        fold
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
        fold
        method="POST"
        path="/api/ingest/datasets/{dataset_id}/lives"
        desc="Append failure rows to a dataset and refit its models in place."
        request={[
          { name: "refit", type: "bool · query", req: false, desc: "Default true; ?refit=false to skip refitting." },
          { name: "(rows)", type: "csv / json", req: true, desc: "Rows whose columns match the dataset." },
        ]}
        returns={`{ "appended": 12, "n_rows": 142, "refit": [ { "id": "…", "name": "…" } ] }`}
      />
      <p className="muted-line">
        Reliafy Maintenance users also have an ingest route for automated meter and condition
        readings; it’s described in the app.
      </p>

      <h3>Model import</h3>
      <Endpoint
        fold
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
  "params_only": false, "url": "/models/m/a1b2…" }`}
      />
    </div>
  );
}
const EXAMPLES = [
  {
    id: "fit",
    label: "Fit a distribution",
    note: "Fit a Weibull to five failure times, one still running (censored 1). Fitting is Pro.",
    curl: (base) => `curl -X POST ${base}/api/v1/life_data_analysis/fit \\
  -H "Authorization: Bearer $RELIAFY_TOKEN" -H "Content-Type: application/json" \\
  -d '{"distribution": "weibull", "data": [120, 340, 510, 700, 980],
       "censored": [0, 0, 1, 0, 0], "unit": "hours"}'`,
    python: `rf.call("life_data_analysis", "fit", distribution="weibull",
        data=[120, 340, 510, 700, 980], censored=[0, 0, 1, 0, 0], unit="hours")`,
  },
  {
    id: "rbd",
    label: "Analyse an RBD",
    note: "System reliability, MTTF and importance for a saved diagram (list rbds gives the ids). With simulate, a long run answers with a job to poll.",
    curl: (base) => `curl -X POST ${base}/api/v1/rbd_analysis/analyze \\
  -H "Authorization: Bearer $RELIAFY_TOKEN" -H "Content-Type: application/json" \\
  -d '{"rbd_id": "RBD_ID", "times": [1000, 8760]}'`,
    python: `rf.call("rbd_analysis", "analyze", rbd_id="RBD_ID", times=[1000, 8760])
rf.call("rbd_analysis", "analyze", rbd_id="RBD_ID", simulate=True, wait=True)  # waits for the job`,
  },
  {
    id: "plan",
    label: "Plan a test",
    note: "How many units to test, and for how long, to show 90% reliability over 1,000 hours with 90% confidence.",
    curl: (base) => `curl -X POST ${base}/api/v1/life_data_analysis/plan_demonstration_test \\
  -H "Authorization: Bearer $RELIAFY_TOKEN" -H "Content-Type: application/json" \\
  -d '{"reliability": 0.9, "confidence": 0.9, "mission_time": 1000, "unit": "hours"}'`,
    python: `rf.call("life_data_analysis", "plan_demonstration_test",
        reliability=0.9, confidence=0.9, mission_time=1000, unit="hours")`,
  },
];

// ---- The live tool list -------------------------------------------------------
// Read once from the live OpenAPI spec and shared by every page that shows it
// (the overview's count, the Tools API page's list). A failed read is retried
// on the next page that asks.
let toolsPromise = null;
function loadTools() {
  if (!toolsPromise) {
    toolsPromise = fetch("/api/v1/openapi.json", { headers: { Accept: "application/json" } })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((spec) => toolsFromSpec(spec))
      .catch((e) => {
        toolsPromise = null;
        throw e;
      });
  }
  return toolsPromise;
}

function useLiveTools() {
  const [state, setState] = useState({ status: "loading", tools: [] });
  useEffect(() => {
    let live = true;
    loadTools()
      .then((tools) => live && setState({ status: tools.length ? "ok" : "error", tools }))
      .catch(() => live && setState({ status: "error", tools: [] }));
    return () => { live = false; };
  }, []);
  return state;
}

// ---- Overview ------------------------------------------------------------------
function Overview({ base }) {
  const { status, tools } = useLiveTools();
  const count = status === "ok" ? `${tools.length} tools, ${countActions(tools)} actions. ` : "";
  return (
    <div className="api-section">
      <h2 id="quick-start">Quick start</h2>
      <p className="muted-line">
        From a script, a scheduled job, the <code>reliafy</code> command line or the Python client.
        On Reliafy Cloud, API tokens are part of <b>Pro</b>; self-hosted servers have no plans and
        allow everything.
      </p>

      <h3>1. Create a token</h3>
      <p className="muted-line">
        Sign in, open <b>Settings → API access</b> and create a personal token (<code>rlf_…</code>).
        Send it on every request. Scopes, limits and errors: <Link className="evidence-link" to={apiDocsPath("authentication")}>Tokens and errors</Link>.
      </p>
      <Code>{`Authorization: Bearer rlf_your_token_here`}</Code>

      <h3>2. Make a call</h3>
      <p className="muted-line">
        Base URL <code>{base}/api/v1</code>. Bodies and answers are JSON.
      </p>
      <Code>{`curl -X POST ${base}/api/v1/list/models \\
  -H "Authorization: Bearer $RELIAFY_TOKEN"`}</Code>

      <h3>3. Or use the command line</h3>
      <Code>{`pip install reliafy-client
reliafy login                     # asks for your token and saves it
reliafy models list`}</Code>

      <h2 id="pages">In these docs</h2>
      <div className="api-docs-cards">
        {API_DOCS_PAGES.filter((p) => p.slug).map((p) => (
          <Link key={p.slug} className="api-docs-card" to={apiDocsPath(p.slug)}>
            <b>{p.label}</b>
            <span>{p.slug === "tools" ? count : ""}{p.blurb}</span>
          </Link>
        ))}
      </div>
    </div>
  );
}

// ---- Tokens, scopes, limits and errors --------------------------------------------
function Authentication({ base }) {
  return (
    <div className="api-section">
      <h2 id="tokens">Tokens and scopes</h2>
      <p className="muted-line">
        Sign in, open <b>Settings → API access</b> and create a personal token (<code>rlf_…</code>).
        Choose its scopes when you create it; revoke it there any time. Send it on every request:
      </p>
      <Code>{`Authorization: Bearer rlf_your_token_here`}</Code>
      <div className="table-scroll">
        <table className="api-params">
          <tbody>
            <tr>
              <td><code>read</code></td>
              <td className="api-pdesc">Reads and calculations: the tools that change nothing (<code>guide</code>, <code>get</code>, <code>list</code>, the analysis tools, <code>strategy</code>, <code>upgrade_link</code>).</td>
            </tr>
            <tr>
              <td><code>write</code></td>
              <td className="api-pdesc">Everything that saves, changes, shares or deletes (<code>models</code>, <code>datasets</code>, <code>rbd</code>, <code>uploads</code>, <code>sharing</code>, <code>fleet</code>), and photo uploads.</td>
            </tr>
            <tr>
              <td><code>ingest</code></td>
              <td className="api-pdesc">Push data only (“Push data” in the app): the ingest routes and model import. An ingest-only token can never read your analyses.</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p className="muted-line">
        No token can reach your account, billing or tokens. Tokens made before scopes existed keep all three.
        The base URL is <code>{base}/api/v1</code>.
      </p>

      <h2 id="limits">Limits and errors</h2>
      <ul className="api-list">
        <li><b>Rate limit:</b> 120 requests a minute per account. Ingest routes take at most 5,000 rows a request.</li>
        <li>Calls are gated exactly as over the Claude connector: Pro accounts get every tool with no monthly allowance, and a few heavy calculations can run at once per account.</li>
        <li>Every refusal is JSON, <code>{`{"detail": "…"}`}</code>, said plainly.</li>
      </ul>
      <div className="table-scroll">
        <table className="api-params">
          <tbody>
            {[
              ["401", "No token, or a wrong, expired or revoked one."],
              ["402", "Needs Pro: a token on an account without Pro, or a Pro-only tool."],
              ["403", "Outside the token’s scopes (for example a write with a read-only token)."],
              ["404", "No such tool, action or item, or one you can’t see."],
              ["422", "The arguments: the detail says which and why."],
              ["429", "The rate limit, the monthly allowance, or too many calculations running at once."],
              ["503", "Busy: try again in a minute."],
              ["504", "The call ran out of time."],
            ].map(([code, text]) => (
              <tr key={code}>
                <td><code>{code}</code></td>
                <td className="api-pdesc">{text}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ---- The tools API ---------------------------------------------------------------
function ToolsApi({ base }) {
  const specUrl = `${base}/api/v1/openapi.json`;
  return (
    <div className="api-section">
      <p className="muted-line">
        Every action of every tool in Reliafy’s Claude connector (MCP) is also a REST call, with
        the same arguments, the same checks and the same result. The REST calls are built from the
        connector’s tools, so a new tool or action is here as soon as it ships.
      </p>
      <Endpoint
        method="POST"
        path="/api/v1/{tool}/{action}"
        desc="A tool with actions (or, for get and list, kinds). The body is a JSON object of the action’s arguments; the action is in the path, not the body."
      />
      <Endpoint
        method="POST"
        path="/api/v1/{tool}"
        desc="A tool without actions, such as guide or upgrade_link."
      />
      <Endpoint
        method="GET"
        path="/api/v1/tools"
        desc="The tools and actions your token may call, each with its path and its required and optional arguments."
      />
      <Endpoint
        method="GET"
        path="/api/v1/openapi.json"
        desc="An OpenAPI 3.1 spec of every tool action with its full argument schema: the complete, always-current reference. Without a token it covers the core tools; with one, everything that account may call. Generate a client from it, or import it into Postman or similar."
      />
      <p className="muted-line">
        <a className="evidence-link" href={specUrl} target="_blank" rel="noreferrer">Open the OpenAPI spec</a>
        {" · "}
        <Link className="evidence-link" to={apiDocsPath("examples")}>Worked examples</Link>
      </p>

      <h3 id="jobs">Long-running calculations</h3>
      <p className="muted-line">
        A long simulation or search answers at once with a <code>job_id</code> and a{" "}
        <code>status</code> of <code>queued</code> or <code>running</code>. Poll it until{" "}
        <code>status</code> is <code>done</code> (with the result) or <code>failed</code>. The Python
        client (<code>wait=True</code>) and the command line wait for you.
      </p>
      <Code>{`curl -X POST ${base}/api/v1/get/job \\
  -H "Authorization: Bearer $RELIAFY_TOKEN" -H "Content-Type: application/json" \\
  -d '{"id": "JOB_ID"}'`}</Code>

      <h3 id="tool-list">Every tool and action</h3>
      <LiveToolList specUrl={specUrl} />
    </div>
  );
}

// The tools and actions, read from the live OpenAPI spec.
function LiveToolList({ specUrl }) {
  const state = useLiveTools();
  const fallback = (
    <p className="muted-line">
      The full list of tools, actions and arguments is in the{" "}
      <a className="evidence-link" href={specUrl} target="_blank" rel="noreferrer">OpenAPI spec</a>,
      and <code>GET /api/v1/tools</code> (or <code>reliafy tools</code>) lists what your token may call.
    </p>
  );
  if (state.status === "loading") {
    return <>{<p className="muted-line">Loading the tool list…</p>}{fallback}</>;
  }
  if (state.status === "error") {
    return <>{<p className="muted-line">The tool list couldn’t be loaded just now.</p>}{fallback}</>;
  }
  const { tools } = state;
  return (
    <div className="api-tools">
      <p className="muted-line">
        {tools.length} tools, {countActions(tools)} actions, read live from the spec. Open a tool for
        its actions and their arguments (<b>bold</b> ones are required); each action is{" "}
        <code>POST /api/v1/{"{tool}"}/{"{action}"}</code>. Reliafy Maintenance users also
        have the Maintenance tools; they show in <code>/api/v1/tools</code> and the spec when you
        call with your token.
      </p>
      {tools.map((t) => (
        <details className="api-tool" key={t.name}>
          <summary>
            <code>{t.name}</code>
            <span className="api-tool-meta">
              {t.actions[0].action ? `${t.actions.length} action${t.actions.length === 1 ? "" : "s"}` : t.actions[0].summary}
              {" · "}{t.scope}
            </span>
          </summary>
          <ul className="api-list">
            {t.actions.map((a) => (
              <li key={a.path}>
                <code className="api-path" title={`POST ${a.path}`}>{a.action ? <b>{a.action}</b> : `POST ${a.path}`}</code>
                {a.pro && <span className="api-tag">Pro</span>}
                {" "}— {a.summary}
                {(a.required.length > 0 || a.optional.length > 0) && (
                  <div className="api-args">
                    {a.required.map((n) => <code key={n}><b>{n}</b></code>)}
                    {a.optional.map((n) => <code key={n}>{n}</code>)}
                  </div>
                )}
              </li>
            ))}
          </ul>
        </details>
      ))}
    </div>
  );
}

// ---- Worked examples -----------------------------------------------------------------
const EXAMPLE_LANGS = [
  { id: "python", label: "Python" },
  { id: "curl", label: "curl" },
];

function Examples({ base }) {
  const [lang, setLang] = useState("python");
  return (
    <div className="api-section">
      <p className="muted-line">
        Three calls from start to finish. Pick a language; every example switches with it.
      </p>
      <Tabs tabs={EXAMPLE_LANGS} value={lang} onChange={setLang} label="Example language" />
      {EXAMPLES.map((ex) => (
        <div className="api-ep" key={ex.id}>
          <div className="api-ep-head"><b>{ex.label}</b></div>
          <p className="muted-line api-ep-desc">{ex.note}</p>
          <Code>{lang === "curl" ? ex.curl(base) : ex.python}</Code>
        </div>
      ))}
      <p className="muted-line">
        The Python lines use <code>rf = Client()</code> from <code>reliafy-client</code> (see{" "}
        <Link className="evidence-link" to={apiDocsPath("python")}>the Python client</Link>). The same calls from{" "}
        <Link className="evidence-link" to={apiDocsPath("cli")}>the command line</Link>:{" "}
        <code>reliafy life_data_analysis fit --distribution weibull …</code>. A long job, such as a
        simulation, is polled as in <Link className="evidence-link" to={`${apiDocsPath("tools")}#jobs`}>long-running calculations</Link>.
      </p>
    </div>
  );
}

// ---- Files and photos ------------------------------------------------------------------
function Files({ base }) {
  return (
    <div className="api-section">
      <p className="muted-line">
        The connector’s tool calls carry JSON, not files. These two take bytes, so they’re on the
        API, the Python client and the command line only:
      </p>
      <Endpoint
        method="PUT"
        path="/api/uploads/{upload_id}?t=…"
        desc="Send a file to the single-use link from uploads create (at most 30 MB; the link’s t is the credential, no other sign-in). Then import it by its upload_id: datasets upload, uploads import_rbd, uploads import_excel or rbd upload_outage_log. Reliafy Maintenance users can also send a PDF (purpose document, at most 20 MB) and keep it on an item or position with maintenance_attachments add_document."
        example={`curl -X POST ${base}/api/v1/uploads/create -H "Authorization: Bearer $RELIAFY_TOKEN" \\
  -H "Content-Type: application/json" -d '{"purpose": "rbd_import", "filename": "plant.xml"}'   # → url, upload_id
curl -X PUT --data-binary @plant.xml "UPLOAD_URL"
curl -X POST ${base}/api/v1/uploads/import_rbd -H "Authorization: Bearer $RELIAFY_TOKEN" \\
  -H "Content-Type: application/json" -d '{"upload_id": "UPLOAD_ID"}'

reliafy import rbd plant.xml          # the same three steps
reliafy upload bearings.xlsx --name Bearings`}
      />
      <ul className="api-list">
        <li><code>PUT /api/uploads/{"{upload_id}"}?t=…</code> (or <code>POST</code> with the raw body) — no sign-in: the link’s token is the credential. It works once and expires after 15 minutes. Answers <code>{`{ upload_id, size, sha256, detected_format }`}</code>.</li>
        <li>Errors: <code>404</code> (no such upload, or a wrong token), <code>409</code> (already used), <code>410</code> (expired), <code>413</code> (over the size limit — 30 MB at most), <code>429</code> (too many attempts).</li>
        <li>Uploads are private to you, are never served back, and are deleted once imported or after an hour.</li>
        <li>The upload URL points straight at Reliafy’s app service, which is fastest. Some sandboxes and corporate proxies refuse that host (for example <code>CONNECT tunnel failed, response 403</code>). For those, <code>uploads create</code> also returns <code>url_fallback</code> (with a ready <code>curl_fallback</code>): the same link on reliafy.com. Send the same PUT there once. It’s slower for large files. A PUT that a proxy refused never reached Reliafy, so the link is still unused.</li>
      </ul>
      <Endpoint
        method="POST"
        path="/api/v1/maintenance/photos?target_id=…&caption=…"
        desc="Reliafy Maintenance users: add a photo to a position, item, location or work order. The body is the image (JPEG, PNG, WebP or HEIC, at most 20 MB), or multipart with a file field. It’s cleaned and stripped of camera and location data, like a photo added in the app. Needs the write scope."
        example={`reliafy photo add IMG_*.jpg --to POSITION_ID --caption "Nameplate"
reliafy photo link PHOTO_ID --to LOCATION_ID     # show it there too
reliafy photo move PHOTO_ID --to POSITION_ID     # only there
reliafy photo unlink PHOTO_ID --from LOCATION_ID`}
      />
      <p className="muted-line">
        From Python: <code>rf.upload_dataset</code>, <code>rf.import_rbd</code>,{" "}
        <code>rf.import_excel</code>, <code>rf.add_photo</code> and <code>rf.add_document</code> (see{" "}
        <Link className="evidence-link" to={`${apiDocsPath("python")}#files`}>the Python client</Link>).
      </p>
    </div>
  );
}

// ---- The command line ------------------------------------------------------------
function CliDocs() {
  return (
    <div className="api-section">
      <p className="muted-line">
        <code>pip install reliafy-client</code> installs the <code>reliafy</code> command. It’s also
        installed as <code>reliafy-client</code>, the same command: if another program called{" "}
        <code>reliafy</code> is already on your path, use <code>reliafy-client</code> instead.
      </p>

      <h3>Sign in</h3>
      <Code>{`pip install reliafy-client
reliafy login                     # asks for your token and saves it
reliafy whoami                    # your account and plan
reliafy logout                    # forget the saved token`}</Code>
      <ul className="api-list">
        <li>
          <code>reliafy login</code> saves the token in <code>~/.config/reliafy/config.json</code>{" "}
          (<code>%APPDATA%\reliafy</code> on Windows; set <code>RELIAFY_CONFIG_DIR</code> to choose),
          readable by you only.
        </li>
        <li>Or set <code>RELIAFY_TOKEN</code> (and <code>RELIAFY_BASE_URL</code> for a self-hosted server), or pass <code>--token</code> and <code>--base-url</code>.</li>
      </ul>

      <h3>Any tool action</h3>
      <Code>{`reliafy tools                                  # every tool and action you may call
reliafy <tool> <action> --arg value …          # any of them
reliafy life_data_analysis fit --help          # one action's arguments
reliafy strategy optimal_replacement --distribution-id weibull \\
    --params '[{"name":"alpha","value":1200},{"name":"beta","value":2.5}]' \\
    --planned-cost 200 --unplanned-cost 1500
reliafy models list
reliafy call get model --args '{"id": "MODEL_ID"}'`}</Code>
      <ul className="api-list">
        <li>Values are read as their argument’s type: text, numbers, <code>true</code>/<code>false</code>, JSON for lists and objects (<code>--times 100,500,1000</code> works too). <code>@file</code> reads a file.</li>
        <li><code>--args '{"{…}"}'</code> gives every argument as one JSON object.</li>
        <li>Long jobs are waited for; <code>--no-wait</code> prints the <code>job_id</code> instead.</li>
        <li>Add <code>--json</code> to any command for JSON instead of the readable summary.</li>
      </ul>

      <h3>Shortcuts</h3>
      <Code>{`reliafy fit failures.csv --dist weibull --censor-column status --save "Pump bearings"
reliafy push model.json                        # {distribution, params | data, name?, unit?}
reliafy upload bearings.xlsx --name Bearings   # CSV or .xlsx as a dataset
reliafy import rbd plant.xml                   # BlockSim, Open-PSA, Galileo, RePyability, Excel
reliafy import excel fmea.xlsx --target rcm --position POSITION_ID
reliafy ingest usage meters.csv --fleet FLEET_ID
reliafy ingest measurements readings.csv --fleet TRACKED_FLEET_ID
reliafy ingest lives new_failures.csv --dataset DATASET_ID
reliafy photo add IMG_*.jpg --to POSITION_ID   # Reliafy Maintenance users`}</Code>
      <ul className="api-list">
        <li><code>reliafy fit</code> never guesses what a flag column means: Reliafy reads 0 = failed, 1 = still running. If yours is 1 = failed, add <code>--c-invert</code>.</li>
        <li>Reliafy Maintenance users also have <code>reliafy ingest readings</code>, <code>reliafy photo link|move|unlink</code>, and <code>reliafy document add FILE.pdf --to ID</code> / <code>reliafy document get ID -o FILE.pdf</code> for PDFs.</li>
        <li><code>reliafy photo add</code> and <code>reliafy document add</code> report each file and exit non-zero if any failed.</li>
      </ul>
    </div>
  );
}

// What each MCP tool does, in plain English (mirrors backend/mcp_server.py): a
// few tools, each doing one area's work by action (or, for get and list, kind).
// Reads and calculations are separate from the tools that change your workspace.
const MCP_TOOLS = [
  { name: "guide", desc: "Short how-tos by topic — life data and censoring, units, accelerated tests, repairable systems, building RBDs, analysing them, strategy, fleets, uploads, sharing, published failure data, the workspace, plans — so the agent reads the one it needs before a task. Never counted against the allowance." },
  { name: "get", desc: "One saved item in full, by kind and id.", actions: [
    ["model", "A saved life or recurrent model — distribution, parameters with confidence intervals, goodness of fit, MTTF and B-lives with lower bounds. Regression models add how good the model is (Harrell’s C, the integrated Brier score, the time-dependent AUC) and whether it holds (the proportional-hazards test with a plain verdict; for Cox PH robust standard errors, the tie method and strata). A model fitted by failure mode reports each mode’s share with 95% intervals and Gray’s test. Recurrent models give the growth verdict, ROCOF and MTBF with bounds and the trend tests."],
    ["dataset", "A dataset’s columns and rows, a page at a time."],
    ["rbd", "A diagram’s structure."],
    ["rbd_run", "One availability simulation in full — its results with their confidence intervals, the inputs and engine versions it ran on, the precision it achieved and what was quoted before it ran."],
    ["job", "A calculation queued on the calculation service (a long simulation, a what-to-improve or interval search, an ALT’s bootstrap bounds) — its place in the queue, then the result."],
    ["upload", "An uploaded file before importing it: a workbook’s sheets with their header rows, columns, row counts and a guessed mapping; a diagram file’s diagrams and block counts."],
    ["account", "Your plan; on Free, the tool calls used and left this month and the date they reset (Pro is unlimited); storage used against your plan’s limits, and whether simulation is included. Never counted against the allowance."],
  ] },
  { name: "list", desc: "Your saved items of one kind, with the shared samples.", actions: [
    ["models / datasets / rbds", "Your models (life or recurrent), datasets and diagrams."],
    ["rbd_runs", "Simulation history, from the app or any connector: who ran each run and from where, its status, method, runtime and result. Kept 7 days on the free plan and 90 on Pro."],
    ["fleets / fleet_alerts", "Your fleet forecasts and a fleet’s email alerts (Pro)."],
    ["share_links", "Your live share links."],
    ["workspace_changes", "What changed in your workspace over a period — the last 30 days by default, a number of days, a date, or since your last visit — worked out from what Reliafy stores, never estimated: new and changed items; refits whose B10 or MTTF moved by more than 10%; fleet forecasts that moved and alerts that fired (Pro); RCM decisions whose linked model was refitted; simulations that moved. It says what it can’t compare."],
  ] },
  { name: "life_data_analysis", desc: "Life data analysis that saves nothing.", actions: [
    ["fit", "Fit a distribution (or “best”) to failure times given inline or from a saved dataset — every model id, from Beta and Royston-Parmar to Buckley-James; shared frailty with group_column (frailty_family: gamma or lognormal); Cox PH with cox_options; covariates that change over time with id_column; by failure mode with causes and “competing_risks”. A fit whose data don’t pin the model down says so (fit_ok: false) so its numbers aren’t quoted. With “best”, criterion ranks by aic, aic_c, bic or neg_ll (the ranking gives each candidate’s parameters, score and delta) and include_mixtures lets two-mode mixtures compete. Regression fits report diagnostics.model_checks. Fitting is Pro."],
    ["fit_per_demand", "Per-demand (one-shot) reliability — a valve that must open, a standby start — from batches of demands and failures, with exact (Clopper-Pearson) bounds; zero failures is the success-run demonstration."],
    ["reliability_at", "Reliability, failure probability and hazard of a saved model at given times — for a unit that has already survived to some age too, with confidence bounds where the model has them. A regression model is evaluated at your covariates (or along a covariate schedule), with its B-lives and their lower bounds."],
    ["check_life_requirement", "Does a saved non-repairable model meet a B-life requirement — “B10 ≥ 50,000 cycles at 90% confidence”? Decided on the B-life’s one-sided lower bound, never the estimate."],
    ["compare_groups", "Is A better than B? The log-rank test, each group’s average life over a common window (RMST) with the difference and its interval, Gray’s test per failure mode, and a one-line verdict — without fitting."],
    ["alt_use_level", "Extrapolate a saved accelerated-life model to the use stress: characteristic, mean and B-lives, the mission reliability and the acceleration factor, with Wald, likelihood-ratio or bootstrap bounds (bootstrap: Pro, as a job)."],
    ["plan_demonstration_test", "Plan a reliability demonstration test — units, test time per unit and allowed failures — with a trade-off table; with producer_risk a plan that keeps both risks; the Weibull shape from a saved model if you like."],
  ] },
  { name: "repairable_analysis", desc: "Repairable systems from a saved recurrent model.", actions: [
    ["next_failure", "A system’s next failure at its current age: the chance of a failure within a time (say, before its next service), and the mean and percentiles of the time to it."],
    ["growth_projection", "Reliability growth projection (MIL-HDBK-189C, AMSAA-Crow): the MTBF a growth test reaches once its delayed fixes are in. Inline data is Pro (it fits)."],
  ] },
  { name: "strategy", desc: "Maintenance strategy calculators and fleet forecasts.", actions: [
    ["optimal_replacement / failure_finding_interval", "Cost-optimal replacement interval, and proof-test interval for a hidden function — for a saved Weibull fitted to data, at each end of the shape’s 95% interval too, with a note when that makes the recommendation less firm."],
    ["optimal_overhaul", "Optimal overhaul interval from a minimal-repair recurrent model."],
    ["fleet_forecast", "Expected failures across a fleet of in-service items, with exact P10–P90 intervals per period and each item’s chance of failing; regression and ALT fleets at each item’s covariates or stress; recurrent fleets count every repeat failure. Pro."],
  ] },
  { name: "rbd_analysis", desc: "Analyse a saved reliability block diagram; nothing is saved.", actions: [
    ["analyze", "System reliability, MTTF, B-lives and importance; for a repairable diagram exact availability over time, the window’s expected failures, downtime and cost, a safety function’s PFDavg and SIL, a priced diagram’s cost of ownership and capacities’ production availability — from new or from the blocks’ state now. The Monte-Carlo simulation adds the spread and the time to the next failure (Pro; a long one comes back as a job)."],
    ["quote_simulation", "How long a simulation should take, before anything runs."],
    ["sensitivity", "What to improve first in a repairable diagram: every lever moved a step, ranked by the gain in availability or cost, in plain words — by benefit per unit of cost when you price the changes — plus over_time, shares, joint, rate and uncertainty measures."],
    ["optimise_intervals", "Choose a repairable diagram’s age-replacement or proof-test intervals together (lowest cost, a target availability, PFDavg or SIL, or a cost cap), staggering tests if you like; returns the edits that apply the plan."],
    ["cheapest_design", "The redundancy that owns a repairable diagram at the lowest total cost, whole trains included, over several horizons. Pro."],
    ["compare", "Is design B better than design A? The difference in availability (and cost of ownership) over a window. Pro."],
    ["fault_tree", "The diagram as a fault tree: top event, ranked minimal cut sets, basic events by importance and each common-cause group’s share. Exact and free."],
    ["allocate_targets", "What reliability, availability or MTTF / MTTR each block needs for the system to meet a target. Exact and free."],
    ["system_history", "The observed availability from an outage log, each outage with the block that caused it, and the blocks ranked by downtime share."],
    ["export_python / export_json", "A standalone SurPyval + RePyability script, or RePyability’s JSON (rbd_from_json loads it; uploads import_rbd brings it back)."],
  ] },
  { name: "library", desc: "Published generic failure data, each record cited with its source and licence; free to read without an account at /api/library too. Never counted against the allowance.", actions: [
    ["search", "Failure rates and probabilities of failure on demand by component and failure mode (“motor-driven pump fails to start”), filtered by source, equipment type and kind, 25 a page with counts."],
    ["get", "One record in full: the mean with its 5th to 95th percentile spread, the evidence behind it (failures, demands or hours), conditions, citation and licence, and the model an RBD block would use. For a handbook rate, give the environment the part works in (e.g. GF, ground, fixed)."],
    ["sources", "The sources, their licences and what each holds. Today: the NRC / INL industry averages for U.S. nuclear power plant components (2020 update), and base failure rates for electronic parts from MIL-HDBK-217F, Notice 2."],
  ] },
  { name: "models", desc: "Save and change models (Claude asks before running it).", actions: [
    ["fit", "The same fit as life_data_analysis fit, saved as a model; with demand_batches, a per-demand model. Pro."],
    ["save", "Save a model from a distribution and parameters your agent fitted itself — e.g. locally with SurPyval."],
    ["fit_alt", "Fit and save an accelerated life test model — failure times at several stress levels and a life-stress relationship, inspection data and delayed entry included. Pro."],
    ["fit_recurrent", "Fit and save a recurrent-event (repairable-system) model: Crow-AMSAA and the other minimal-repair models, proportional intensity, or imperfect repair (Kijima I/II, ARA, ARI, G1). Pro."],
    ["update / delete", "Rename or annotate your own models, or delete one (never shared samples; not one a fleet forecast runs on)."],
  ] },
  { name: "datasets", desc: "Save and change datasets.", actions: [
    ["upload", "Save CSV text, or a CSV or Excel file sent with uploads create."],
    ["update / delete", "Rename or annotate your own datasets, or delete one (not one a model was fitted to)."],
  ] },
  { name: "rbd", desc: "Build and change reliability block diagrams.", actions: [
    ["create", "Build and save a diagram — series, parallel, k-of-n, standby, sub-systems — that opens in the RBD builder: mixtures of failure modes, imperfect repair, common-cause groups (beta factor or multiple Greek letter), capacities and a demand, phased missions, networks, covariate schedules, costs, scheduled and condition-based replacement and proof tests."],
    ["clone / edit", "Copy a sample or one of your diagrams, and change a diagram with a short batch of edits, all or nothing, instead of rebuilding it."],
    ["delete", "Delete one of your own diagrams."],
    ["upload_outage_log", "Save a real outage log (asset, down, back up) — CSV text or an uploaded file — against one of your diagrams."],
  ] },
  { name: "uploads", desc: "Files into Reliafy without pasting them.", actions: [
    ["create", "A single-use link (15 minutes) to send a file with a plain HTTP PUT — a ready curl command — with a reliafy.com fallback URL for networks that block the direct one. Up to 30 MB; deleted after its import, or after an hour."],
    ["send_part", "For an agent that can’t reach the upload URL at all: the file in base64 parts through the MCP connection, into the same upload. For files up to a few hundred KB; not counted against the Free allowance."],
    ["import_rbd", "Import diagrams from ReliaSoft BlockSim, Open-PSA XML, Galileo DFT, RePyability JSON or Reliafy’s Excel RBD template, with notes on anything approximated; preview first to check the structure."],
    ["import_excel", "A sheet as a dataset, an FMEA / RCM worksheet onto a maintenance position’s RCM (give its position_id), or the RBD template as a diagram (as a copy of an existing one, unless you ask to replace it)."],
  ] },
  { name: "sharing", desc: "Read-only pages anyone with the link can open, no account needed.", actions: [
    ["create_link", "Publish one of your own items — a model, dataset, diagram, strategy analysis, RCM study or fleet — optionally password-protected (a passphrase shown once, for you to send separately) and expiring."],
    ["create_report", "Several of your items on one print-ready page, with a title, an author line, an introduction and a note per item."],
    ["revoke_link", "End a link at once."],
  ] },
  { name: "fleet", desc: "Fleet alerts (Pro).", actions: [
    ["create_alert", "Email alerts on a fleet’s expected failures — checked each time usage arrives through the ingest API."],
  ] },
  { name: "upgrade_link", desc: "A Stripe checkout link for Reliafy Pro, for you to open and pay yourself — nothing is charged until you complete it. Works before you have Pro." },
];

// "Use Reliafy from Claude (MCP)": what the MCP server is and how to connect
// (headed, while the connector is switched off, by how to ask for it): the
// /api-docs/mcp page. ``tokenNote`` says where tokens come from.
function McpDocs({ tokenNote }) {
  const { mcp: mcpOn } = useAppConfig();
  const base = (typeof window !== "undefined" && window.location.origin) || "https://reliafy.com";
  const url = `${base}/mcp`;
  return (
    <div className="api-section">
        {!mcpOn && <McpOnRequest className="api-mcp-off" />}
        <p className="muted-line">
          Reliafy runs a remote <b>Model Context Protocol</b> server, so Claude — on the web, the
          desktop and mobile apps, or Claude Code — can work in your Reliafy account for you: fit
          distributions, read your models, build and analyse RBDs, and run the maintenance
          calculators. It sees what you see: your own data plus the shared samples. Self-hosted
          instances allow every tool for everyone.
        </p>

        <h3>Free to try, unlimited on Pro</h3>
        <p className="muted-line">
          On Reliafy Cloud, using Reliafy from AI agents (MCP) is part of <b>Pro</b> (US$19/month):
          every tool, no limit and unlimited storage. <b>Free</b> gives you 20 tool calls a month to
          try it — every tool except fitting, fleets and availability simulation, within the Free
          storage limits; the calls reset on the 1st of each month (UTC). Looking things up in the
          reliability data library doesn’t count. Past them, each tool says so, and{" "}
          <code>upgrade_link</code> gives you a link to subscribe.
        </p>

        <h3>Claude on the web, desktop and mobile</h3>
        <p className="muted-line">
          In Claude, open <b>Customize → Connectors</b> (<code>claude.ai/customize/connectors</code>), choose <b>Add custom connector</b>, enter{" "}
          <code>{url}</code>, then choose <b>Connect</b> and sign in to Reliafy. Reliafy asks you
          to approve the connection; you can disconnect it any time under Settings › Connected apps.
          Connectors added on claude.ai are available in the desktop and mobile apps too.
        </p>

        <h3>Claude Code</h3>
        <Code>{`claude mcp add --transport http reliafy ${url}`}</Code>
        <p className="muted-line">
          Then run <code>/mcp</code> in Claude Code, pick <b>reliafy</b> and sign in — a browser
          window opens for you to approve access. After that, ask something like “fit a Weibull to
          these bearing lives” or “build an RBD of my pump skid and tell me its MTTF”.{" "}
          <code>claude mcp list</code> shows the connection.
        </p>
        <p className="muted-line">
          Prefer a token (scripts, CI, headless machines)? A personal API token (<code>rlf_…</code>)
          still works — {tokenNote} Give it the <b>Read</b> scope for the reading and
          calculating tools, and <b>Write</b> too for the ones that save, change or delete.
        </p>
        <Code>{`claude mcp add --transport http reliafy ${url} --header "Authorization: Bearer rlf_YOUR_TOKEN"`}</Code>

        <h3>Other MCP clients</h3>
        <p className="muted-line">
          Any client that supports Streamable HTTP can connect to <code>{url}</code> — with OAuth
          (discovered automatically from the server; dynamic client registration and client ID
          metadata documents are both supported), or with a token header:
        </p>
        <Code>{`{
  "mcpServers": {
    "reliafy": {
      "type": "http",
      "url": "${url}",
      "headers": { "Authorization": "Bearer rlf_YOUR_TOKEN" }
    }
  }
}`}</Code>

        <h3>Sending files</h3>
        <p className="muted-line">
          Files don’t need to go through the conversation. <code>uploads</code> (action <code>create</code>) returns a single-use
          upload URL; Claude sends the file there from its shell, then imports it by its{" "}
          <code>upload_id</code>:
        </p>
        <Code>{`curl -X PUT --data-binary @plant.rsgz \\
  -H "Content-Type: application/octet-stream" \\
  "${base}/api/uploads/UPLOAD_ID?t=TOKEN"`}</Code>
        <ul className="api-list">
          <li>The link works once, expires after 15 minutes and takes at most 30 MB. Its answer, errors and privacy: <Link className="evidence-link" to={apiDocsPath("files")}>Files and photos</Link>.</li>
          <li>The upload URL points straight at Reliafy’s app service, which is fastest. Some sandboxes and corporate proxies refuse that host (for example <code>CONNECT tunnel failed, response 403</code>). For those, <code>uploads create</code> also returns <code>url_fallback</code> (with a ready <code>curl_fallback</code>): the same link on reliafy.com. Send the same PUT there once. It’s slower for large files. A PUT that a proxy refused never reached Reliafy, so the link is still unused.</li>
          <li>If Claude’s environment can’t reach either URL (no network), small text files (up to 200 KB) can be pasted instead — CSV into <code>datasets upload</code> or <code>rbd upload_outage_log</code>, Open-PSA or Galileo text into <code>uploads import_rbd</code>. Other files of up to a few hundred KB (an Excel workbook, a BlockSim project) can go through the MCP connection itself with <code>uploads send_part</code>: base64 parts into the same upload, checked against the file’s SHA-256. An FMEA / RCM worksheet goes onto a position’s RCM with <code>uploads import_excel</code> (target <code>rcm</code> and a <code>position_id</code>). Anything larger is uploaded in the app.</li>
        </ul>

        <h3>Tools</h3>
        <p className="muted-line">
          A few tools, each doing one area’s work: an agent picks the tool, then the action (or, for{" "}
          <code>get</code> and <code>list</code>, the kind). Each tool’s description lists its actions and what
          each takes, and <code>guide</code> gives the agent how-tos by topic.
        </p>
        <div className="api-tools">
          {MCP_TOOLS.map(({ name, desc, actions }) => (actions ? (
            <details className="api-tool" key={name}>
              <summary>
                <code>{name}</code>
                <span className="api-tool-meta">{desc}</span>
              </summary>
              <ul className="api-list">
                {actions.map(([action, text]) => (
                  <li key={action}><code>{action}</code> — {text}</li>
                ))}
              </ul>
            </details>
          ) : (
            <div className="api-tool api-tool-flat" key={name}>
              <code>{name}</code>
              <span className="api-tool-meta">{desc}</span>
            </div>
          )))}
        </div>
        <ul className="api-list">
          <li>Censoring follows Reliafy’s convention: <b>0 = failed</b>, <b>1 = still running</b>. Data coded the other way round can be fitted with the inverted-flags option.</li>
          <li>Reading and calculating tools (<code>guide</code>, <code>get</code>, <code>list</code>, the four analysis tools and <code>upgrade_link</code>) are marked read-only; the tools that save, change, share or delete in your workspace are marked as writes, so Claude asks before running them, and deletes only what you ask it to, after confirming by name.</li>
          <li>Errors: <code>401</code> (not signed in, or a missing, expired or revoked token), <code>403</code> (an API token whose owner isn’t on Pro — tokens are Pro-only; a signed-in Claude connection without Pro connects, and each tool says it needs Pro), <code>429</code> (over 120 requests/minute), <code>503</code> (the MCP connector isn’t switched on — it’s available on request).</li>
        </ul>
    </div>
  );
}

// ---- The pages and their frame ------------------------------------------------------
// The sub-navigation: a list down the left on a wide screen, a menu on a phone.
function ApiDocsNav({ page }) {
  const navigate = useNavigate();
  return (
    <nav className="api-docs-nav" aria-label="API docs pages">
      <label className="api-docs-select">
        <span>Page</span>
        <select value={apiDocsPath(page)} onChange={(e) => navigate(e.target.value)}>
          {API_DOCS_PAGES.map((p) => (
            <option key={p.slug} value={apiDocsPath(p.slug)}>{p.label}</option>
          ))}
        </select>
      </label>
      <ul className="api-docs-menu">
        {API_DOCS_PAGES.map((p) => (
          <li key={p.slug}>
            <Link
              to={apiDocsPath(p.slug)}
              className={p.slug === page ? "active" : undefined}
              aria-current={p.slug === page ? "page" : undefined}
            >
              {p.label}
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  );
}

function PrevNext({ page }) {
  const { prev, next } = apiDocsNeighbours(page);
  return (
    <div className="api-docs-pager">
      {prev ? (
        <Link className="api-docs-prev" to={apiDocsPath(prev.slug)}>
          <span>Previous</span>
          <b>{prev.label}</b>
        </Link>
      ) : <span />}
      {next && (
        <Link className="api-docs-next" to={apiDocsPath(next.slug)}>
          <span>Next</span>
          <b>{next.label}</b>
        </Link>
      )}
    </div>
  );
}

function PageBody({ page, base, tokenNote }) {
  switch (page) {
    case "authentication": return <Authentication base={base} />;
    case "tools": return <ToolsApi base={base} />;
    case "examples": return <Examples base={base} />;
    case "cli": return <CliDocs />;
    case "python": return <ClientDocs />;
    case "files": return <Files base={base} />;
    case "mcp": return <McpDocs tokenNote={tokenNote} />;
    case "v1-routes": return <HttpDocs base={base} />;
    default: return <Overview base={base} />;
  }
}

// The API docs, one page of them (``page`` is its slug; "" is the overview),
// with the sub-navigation and previous / next links. ``header`` is the host's
// page head (title and, on the overview, the introduction); ``tokenNote`` says
// where tokens come from. Examples use the live origin, so self-hosted
// instances show their own base URL.
export default function ApiDocs({ page = "", header, tokenNote }) {
  const base = (typeof window !== "undefined" && window.location.origin) || "https://reliafy.com";
  const navigate = useNavigate();
  const { hash } = useLocation();
  // Links to the old single page (/api-docs#mcp) go to the page that section
  // is on now; a link to an anchor on this page scrolls to it once drawn.
  useEffect(() => {
    if (!hash) return;
    const target = page === "" ? legacyApiDocsTarget(hash) : null;
    if (target) {
      navigate(target, { replace: true });
      return;
    }
    document.getElementById(decodeURIComponent(hash.slice(1)))?.scrollIntoView();
  }, [page, hash]);

  return (
    <div className="api-docs">
      <ApiDocsNav page={page} />
      <div className="api-docs-main">
        {header}
        <div className="card api-ref">
          <PageBody page={page} base={base} tokenNote={tokenNote} />
        </div>
        <PrevNext page={page} />
      </div>
    </div>
  );
}
