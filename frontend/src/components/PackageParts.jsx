import { useEffect, useState } from "react";
import { getPackageParts } from "../api.js";
import { formatNumber } from "../format.js";
import { riskText } from "../sparesPlan.js";
import { countedText, dayText } from "../sparesYear.js";
import { ResultDetails } from "./ui/ResultSummary.jsx";

// A package's next visit against stock (maintenance get.package_parts): each part its tasks use,
// how many the visit needs and how many are usable now, when an order placed today lands (before
// the visit or after), and the chance a part runs out before that order lands, counting the
// visit's jobs and failures wherever the part is used. Untick a task to see the answer without it
// (a what-if: nothing changes until you take the task out of the package). The Packages page and
// the Explorer's Packages view both show it; built from the app's lib-table and ResultDetails.
export default function PackageParts({ packageId, version = 0, className = "" }) {
  const [leave, setLeave] = useState([]);
  const [state, setState] = useState({ key: null, data: null, error: null });
  const key = `${packageId}:${version}:${leave.join(",")}`;
  useEffect(() => {
    let live = true;
    getPackageParts(packageId, { leaveOut: leave })
      .then((data) => live && setState({ key, data, error: null }))
      .catch((e) => live && setState({ key, data: null, error: e.message }));
    return () => { live = false; };
  }, [key]); // eslint-disable-line react-hooks/exhaustive-deps
  const data = state.data; // the last answer stays while a what-if is worked out
  const flip = (id) => setLeave((l) => (l.includes(id) ? l.filter((x) => x !== id) : [...l, id]));
  if (state.error) return <p className="lib-date">Couldn&apos;t check the parts: {state.error}</p>;
  if (!data) return <p className="lib-date">Checking the parts against stock…</p>;
  if (!data.visit || !data.parts.length) return null;
  return (
    <section className={`pk-parts ${className}`.trim()} aria-label="Parts for the next visit" data-testid="package-parts">
      <h4 className="td-sublabel">Parts for the visit on {dayText(data.visit.on)}</h4>
      <div className="maint-scroll">
        <table className="lib-table">
          <thead>
            <tr><th scope="col">Part</th><th scope="col">Needed</th><th scope="col">Usable now</th>
              <th scope="col">Ordered today, lands</th><th scope="col">Chance it runs out first</th></tr>
          </thead>
          <tbody>
            {data.parts.map((r) => (
              <tr key={r.part.id}>
                <td><b>{r.part.part_number}</b> {r.part.name}</td>
                <td className={r.short ? "maint-overdue num" : "num"}>{formatNumber(r.needed_most)}{r.short ? " ! short" : ""}
                  {r.needed < r.needed_most - 0.005 && <div className="lib-date">≈ {formatNumber(r.needed, { sig: 2 })} expected</div>}</td>
                <td className="num">{formatNumber(r.usable_now)}<div className="lib-date">{countedText(r, data.today)}</div></td>
                <td>{dayText(r.order_today_arrives)}
                  <div className={r.arrives_before_visit ? "lib-date" : "maint-overdue"}>{r.arrives_before_visit ? "before the visit" : "after the visit"}</div></td>
                <td className="num">{riskText(r.chance_short_before_arrival)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <ResultDetails summary="Which jobs to do at this visit" open={leave.length > 0}>
        <p className="lib-date">Untick a job to see the parts without it. This only shows the answer: take the task out of the
          package to change the plan.</p>
        <ul className="pk-members">
          {data.parts.flatMap((r) => r.jobs.map((j) => ({ ...j, part: r.part }))).map((j) => (
            <li key={`${j.task.id}-${j.part.id}`} className="pk-member">
              <label className="pk-member-main">
                <span><input type="checkbox" checked={!j.left_out} disabled={j.too_young} onChange={() => flip(j.task.id)} />{" "}
                  {j.task.name} · {j.position.name}</span>
                <span className="lib-date pk-sub">{j.part.part_number} × {formatNumber(j.qty)}
                  {j.too_young ? " · skipped: the item is younger than its shutdown age" : j.older_than
                    ? ` · only if older than ${j.older_than.value} ${j.older_than.unit} (${Math.round(j.chance_done * 100)}% likely)` : ""}</span>
              </label>
            </li>
          ))}
        </ul>
        <p className="lib-date">{data.rule}</p>
      </ResultDetails>
    </section>
  );
}
