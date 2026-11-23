import { Link } from "react-router-dom";
import Card, { CardHeader } from "./ui/Card.jsx";
import Chip from "./ui/Chip.jsx";
import { fmt, lengthText, pct } from "../explorerMissions.js";
import { boundText, calendarText, chanceOf, chanceSentence, failuresSentence, missionLength, rangeShort } from "../missionSetup.js";

// A mission's two answers as plain cards (the Missions tab, 23 Nov 2026): the chance of completing
// the whole phased mission, with its 90% one-sided lower bound, and the part failures to expect
// during it, with a 90% two-sided range. The plain sentence first, then the numbers; under them,
// what it assumed (its calendar, starting state, the plan not counted yet). Blocks with no model, or
// only a placeholder, stop both and are named (nothing is worked out on a guess).
//
//   answers   POST …/answers' payload (null: not worked out yet)   busy   error
//   onOpenRbd() to give the blocks their models   onUpgrade (the range is Pro)

export default function MissionAnswers({ answers, busy = false, error = null, onOpenRbd = null }) {
  if (error) return <p className="field-error" role="alert">{error}</p>;
  if (!answers) return <p className="rim-tquiet mission-wait" role="status">{busy ? "Working out the answers…" : "Changed: Save to work its answers out again."}</p>;
  if (answers.blocked?.length) {
    return (
      <Card className="mission-card mission-blocked" role="note" aria-label="Blocks with no model">
        <CardHeader title="No answers yet" level={3}
                    subtitle={`${answers.blocked.length === 1 ? "This block has" : "These blocks have"} no model, or only a placeholder, so nothing is worked out on a guess.`} />
        <ul className="mission-blocked-list">
          {answers.blocked.map((b) => <li key={b.id}><b>{b.label}</b>: {b.why}</li>)}
        </ul>
        {onOpenRbd && <button type="button" className="secondary sm" onClick={onOpenRbd}>Open its RBD to give them models</button>}
      </Card>
    );
  }
  const { chance, failures, unit, length } = answers;
  const lb = chance?.lower_bound;
  return (
    <div className="mission-answers" aria-busy={busy || undefined}>
      <div className="mission-cards">
        <Card className="mission-card">
          <CardHeader title="Chance of completing" level={3} subtitle={chanceSentence(chance, answers.clock) || "Waiting for the values the phases need."} />
          {chance?.value != null && (
            <p className="mission-figure">
              <b>{pct(chance.value)}</b>
              <span className="mission-figure-sub">{chanceOf(answers.clock)}. {boundText(chance)}</span>
            </p>
          )}
          {!lb && chance?.value != null && <Chip tone="neutral">No bound</Chip>}
        </Card>
        <Card className="mission-card">
          <CardHeader title="Failures to expect" level={3} subtitle={failuresSentence(failures, length, unit, answers.clock)} />
          {failures?.expected != null && (
            <p className="mission-figure">
              <b>{fmt(failures.expected)}</b>
              <span className="mission-figure-sub">
                {failures.range ? rangeShort(failures.range) : "part failures, each replaced like new"}
              </span>
            </p>
          )}
          {failures?.method === "simulated" && <Chip tone="warning" title={`${(failures.range?.runs || 0).toLocaleString("en-AU")} simulated missions, seeded`}>Simulated</Chip>}
          {failures?.pro && failures?.expected != null && (
            <p className="rim-tquiet">The 90% range comes from simulated missions, which is Pro: it adds the range of outcomes. <Link to="/billing">Upgrade to Pro</Link></p>
          )}
          {failures?.pro && failures?.expected == null && (
            <p className="rim-tquiet">{failures.note} <Link to="/billing">Upgrade to Pro</Link></p>
          )}
        </Card>
      </div>
      <ul className="mission-assumed" aria-label="What it assumed">
        <li>
          {answers.clock?.kind === "calendar" ? `Calendar time: ${answers.clock.words}` : `Operating time: ${answers.clock ? missionLength(answers.clock) : lengthText(length, unit)}, no calendar needed`}
          {` in ${answers.phases} phase${answers.phases === 1 ? "" : "s"}`}{answers.calendar ? ` · ${calendarText(answers.calendar)}` : ""}.
        </li>
        <li>{answers.setup?.from === "today" ? "Blocks start at their items' ages today." : "Every block starts new."}</li>
        {(answers.assumed || []).map((a) => <li key={a}>{a}</li>)}
      </ul>
      {answers.plan?.length > 0 && (
        <details className="mission-plan">
          <summary>The current maintenance plan on its positions ({answers.plan.length}, read only)</summary>
          <ul>{answers.plan.map((p, i) => <li key={`${p.position}-${p.task}-${i}`}>{p.position}: {p.task}{p.every ? `, ${p.every}` : ""}</li>)}</ul>
        </details>
      )}
    </div>
  );
}
