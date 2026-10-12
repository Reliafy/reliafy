import { useEffect, useState } from "react";
import { getAdminLibraries } from "../api.js";
import { relativeTime } from "../instrument.js";
import Card, { CardHeader } from "./ui/Card.jsx";
import Chip from "./ui/Chip.jsx";
import ResultSummary, { ResultDetails } from "./ui/ResultSummary.jsx";

const PR_SHOWN = 4;
const STEP = { do: { label: "To do", tone: "warning" }, wait: { label: "Waiting", tone: "neutral" }, info: { label: "Note", tone: "neutral" } };

const date = (iso) =>
  iso ? new Date(iso).toLocaleDateString("en-AU", { day: "numeric", month: "short", year: "numeric" }) : "";

function Unavailable({ part }) {
  return <span className="muted">Unavailable{part?.error ? ` (${part.error})` : ""}</span>;
}

function Ext({ href, children }) {
  return href ? (
    <a href={href} target="_blank" rel="noreferrer">
      {children}
    </a>
  ) : (
    children
  );
}

function Rows({ children }) {
  return <dl className="lib-rows">{children}</dl>;
}

function Row({ label, children }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}

function Branches({ b }) {
  if (!b || b.error) return <Unavailable part={b} />;
  return (
    <Ext href={b.url}>
      {b.integration} {b.ahead ?? "?"} ahead of {b.release}
      {b.behind ? `, ${b.behind} behind` : ""}
    </Ext>
  );
}

function Prs({ prs }) {
  if (!prs || prs.error) return <Unavailable part={prs} />;
  if (!prs.count) return "None";
  const list = (items) => (
    <ul className="lib-prs">
      {items.map((p) => (
        <li key={p.number}>
          <a href={p.url} target="_blank" rel="noreferrer">#{p.number}</a> {p.title}
          {p.draft && <> <Chip>Draft</Chip></>}
        </li>
      ))}
    </ul>
  );
  return (
    <>
      {prs.count}
      {prs.more ? "+" : ""} open
      {list(prs.items.slice(0, PR_SHOWN))}
      {prs.items.length > PR_SHOWN && (
        <ResultDetails summary={`${prs.items.length - PR_SHOWN} more`}>{list(prs.items.slice(PR_SHOWN))}</ResultDetails>
      )}
    </>
  );
}

function Ci({ run }) {
  if (!run || run.error) return <Unavailable part={run} />;
  if (run.status === "none") return <span className="muted">No runs</span>;
  const tone =
    run.status !== "completed" ? "accent" : run.conclusion === "success" ? "success" : run.conclusion === "failure" ? "danger" : "neutral";
  const label = run.status !== "completed" ? "Running" : run.conclusion === "success" ? "Passed" : run.conclusion || run.status;
  return (
    <>
      <Chip tone={tone}>{label}</Chip>{" "}
      <Ext href={run.url}>{run.sha}</Ext> <span className="muted">· {relativeTime(run.at)}</span>
    </>
  );
}

function Latest({ gh, pypi }) {
  return (
    <>
      {gh?.error ? (
        <>GitHub: <Unavailable part={gh} /></>
      ) : (
        <>
          <Ext href={gh.url}>{gh.version}</Ext>{" "}
          <span className="muted">
            {gh.kind === "tag" ? "tag" : "release"}
            {gh.at ? `, ${date(gh.at)}` : ""}
          </span>
        </>
      )}
      <br />
      {pypi?.error ? (
        <>PyPI: <Unavailable part={pypi} /></>
      ) : (
        <>
          PyPI <Ext href={pypi.url}>{pypi.version}</Ext>
          {pypi.at && <span className="muted">, {date(pypi.at)}</span>}
        </>
      )}
    </>
  );
}

function Accelerators({ acc }) {
  if (!acc) return <span className="muted">Not in this image</span>;
  const one = (label, on) => (
    <Chip tone={on ? "success" : "danger"}>
      {label} {on ? "active" : "off"}
    </Chip>
  );
  return (
    <span className="chip-row">
      {one("Fits", acc.fits)}
      {one("Simulations", acc.simulations)}
    </span>
  );
}

// Where SurPyval, RePyability and this deployment stand (Libraries tab):
// the answer first ("Up to date" or the next step), then each codebase.
export default function AdminLibrariesTab() {
  const [state, setState] = useState({ data: null, error: null });
  const [busy, setBusy] = useState(false);

  const load = (refresh = false) => {
    setBusy(true);
    return getAdminLibraries(refresh)
      .then((data) => setState({ data, error: null }))
      .catch((e) => setState((s) => ({ data: s.data, error: e.message })))
      .finally(() => setBusy(false));
  };
  useEffect(() => {
    load();
  }, []);

  const d = state.data;
  if (!d && state.error) return <Card className="empty"><p>{state.error}</p></Card>;
  if (!d) return <Card className="empty">Checking GitHub and PyPI…</Card>;

  const a = d.answer;
  const rel = d.reliafy;
  const sp = d.surpyval;
  const rp = d.repyability;
  const rest = a.up_to_date ? a.steps : a.steps.slice(1);
  const limited = d.refresh?.limited;

  return (
    <div className="lib">
      <div className="lib-bar">
        <span className="muted">
          {d.checked_at ? `Checked ${relativeTime(new Date(d.checked_at * 1000).toISOString())}` : "Not checked"}
          {!d.github_authenticated && " · GitHub without a token (60 requests an hour)"}
          {limited && ` · refreshed under a minute ago, try again in ${d.refresh.retry_in} s`}
        </span>
        <button type="button" className="secondary sm" onClick={() => load(true)} disabled={busy}>
          {busy ? "Checking…" : "Refresh"}
        </button>
      </div>

      <ResultSummary
        tone={a.up_to_date ? "good" : "caveat"}
        sentence={a.up_to_date ? <b>Up to date</b> : a.headline}
      >
        {a.up_to_date && a.note ? `${a.note} ` : ""}
        Rule: {d.rule}
      </ResultSummary>

      {rest.length > 0 && (
        <Card className="lib-steps">
          <CardHeader title={a.up_to_date ? "Next" : "Then"} level={3} />
          <ol>
            {rest.map((s, i) => (
              <li key={i}>
                <Chip tone={STEP[s.kind]?.tone}>{STEP[s.kind]?.label}</Chip> {s.text}
              </li>
            ))}
          </ol>
        </Card>
      )}

      <div className="lib-cards">
        <Card>
          <CardHeader title={<Ext href={rel.repo_url}>Reliafy</Ext>} subtitle="This deployment" level={3} />
          <Rows>
            <Row label="Running">
              RePyability {rel.installed.repyability || "?"} · SurPyval {rel.installed.surpyval || "?"}
            </Row>
            <Row label="Revision">
              {rel.revision || <span className="muted">Not on Cloud Run</span>}
              {rel.commit && <span className="muted"> · {rel.commit}</span>}
            </Row>
            <Row label="Accelerators">
              <Accelerators acc={rel.accelerators} />
            </Row>
            <Row label="Branches">
              <Branches b={rel.branches} />
            </Row>
            <Row label="CI on main">
              <Ci run={rel.ci?.main} />
            </Row>
            <Row label="CI on dev">
              <Ci run={rel.ci?.dev} />
            </Row>
            <Row label="Pull requests">
              <Prs prs={rel.prs} />
            </Row>
          </Rows>
        </Card>

        {[rp, sp].map((lib) => (
          <Card key={lib.name}>
            <CardHeader title={<Ext href={lib.repo_url}>{lib.name}</Ext>} level={3} />
            <Rows>
              <Row label="Latest">
                <Latest gh={lib.github} pypi={lib.pypi} />
              </Row>
              {lib === rp && (
                <Row label="Needs SurPyval">
                  {rp.pypi?.error ? (
                    <Unavailable part={rp.pypi} />
                  ) : (
                    <>
                      {rp.pypi.requires_surpyval || "any"}
                      {rp.pypi.targets_surpyval && <span className="muted"> · targets {rp.pypi.targets_surpyval}</span>}
                    </>
                  )}
                </Row>
              )}
              <Row label="Branches">
                <Branches b={lib.branches} />
              </Row>
              <Row label="Pull requests">
                <Prs prs={lib.prs} />
              </Row>
            </Rows>
          </Card>
        ))}
      </div>
      {state.error && <p className="muted-line warn">{state.error}</p>}
    </div>
  );
}
