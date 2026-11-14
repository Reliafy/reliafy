import { money } from "../lsaTab.js";
import { formatMonth } from "../dates.js";
import "./ForecastPreview.css";

// The Maintenance tab's Forecast view, as a PREVIEW of its layout only (shown where the menu
// preview is on, MENU_PREVIEW). Every number here is made up to show the shape: nothing is
// worked out from the position's tasks, plan or models yet. The forecast itself needs the
// scheduling library; until then this says so plainly, at the top and on the table.
//
// The layout: the answer first ("Next 12 months: 58 tasks, about 46 labour hours; 0.6 failures
// expected (0 to 1), about $3,000"), then a month-by-month table with the tasks due each month.

// Placeholder months, starting at `start` (an ISO date): hours, tasks, labour, failures, costs.
const ROWS = [
  [176, 3, 2.5, 420, 0.02, 105, []], [368, 4, 3, 560, 0.05, 227, []], [336, 4, 3, 560, 0.05, 217, []],
  [320, 4, 3, 560, 0.04, 214, []], [368, 5, 4, 700, 0.05, 252, []], [352, 6, 7.5, 1310, 0.05, 247, ["Service"]],
  [336, 5, 4, 700, 0.05, 239, []], [352, 4, 3, 560, 0.05, 252, []], [352, 4, 3, 560, 0.05, 253, []],
  [352, 5, 4, 700, 0.05, 252, []], [352, 5, 6.5, 1170, 0.05, 250, ["Service"]], [336, 9, 2.5, 2560, 0.05, 236, ["Shutdown overhaul"]],
];

function months(start) {
  const [y, m] = String(start).slice(0, 7).split("-").map(Number);
  return ROWS.map((r, i) => {
    const t = new Date(Date.UTC(y, m - 1 + i, 1));
    return { month: t.toISOString().slice(0, 10), hours: r[0], tasks: r[1], labour: r[2], planned: r[3], failures: r[4], failureCost: r[5], others: r[6] };
  });
}

const ordinal = (n) => `${n}${n % 100 >= 10 && n % 100 <= 20 ? "th" : ({ 1: "st", 2: "nd", 3: "rd" }[n % 10] || "th")}`;

export default function ForecastPreview({ today, where }) {
  const fromDay = Number(String(today || "").slice(8, 10)) || 1;
  const rows = months(today || new Date().toISOString().slice(0, 10));
  const tasks = rows.reduce((t, r) => t + r.tasks, 0);
  const labour = rows.reduce((t, r) => t + r.labour, 0);
  return (
    <section className="fc-preview" aria-label="Forecast (preview)">
      <p className="fc-flag" role="note">
        <strong>Preview with made-up numbers.</strong> This shows how the forecast will be laid out. None of these
        figures come from {where || "this position"}: they aren&apos;t its tasks, hours or failures.
      </p>
      <p className="fc-answer">
        Next 12 months: {tasks} tasks, about {Math.round(labour)} labour hours; 0.6 failures expected (0 to 1), about {money(3000)}.
      </p>
      <p className="lib-date fc-how">
        Hours from the operating plan; failures from the life models on the positions here and below, laid on the
        calendar through the plan. The range is 90% of outcomes (5% to 95%).
      </p>
      <div className="maint-scroll fc-scroll">
        <table className="lib-table fc-table">
          <caption className="sr-only">Month by month (made-up numbers)</caption>
          <thead>
            <tr>
              <th scope="col">Month</th><th scope="col" className="num">Operating hours</th><th scope="col" className="num">Tasks</th>
              <th scope="col" className="num">Labour hours</th><th scope="col" className="num">Planned cost</th>
              <th scope="col" className="num">Expected failures</th><th scope="col" className="num">Failure cost</th>
              <th scope="col">Besides the routine</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.month}>
                <th scope="row">{formatMonth(r.month)}{r === rows[0] && fromDay > 1 ? <span className="lib-date"> (from the {ordinal(fromDay)})</span> : null}</th>
                <td className="num">{r.hours.toLocaleString("en-GB")} h</td>
                <td className="num">{r.tasks}</td>
                <td className="num">{r.labour.toLocaleString("en-GB")} h</td>
                <td className="num">{money(r.planned)}</td>
                <td className="num">{r.failures.toFixed(2)}</td>
                <td className="num">{money(r.failureCost)}</td>
                <td>{r.others.join(", ") || <span className="lib-date">—</span>}</td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr>
              <th scope="row">12 months</th>
              <td className="num">{rows.reduce((t, r) => t + r.hours, 0).toLocaleString("en-GB")} h</td>
              <td className="num">{tasks}</td>
              <td className="num">{Math.round(labour)} h</td>
              <td className="num">{money(rows.reduce((t, r) => t + r.planned, 0))}</td>
              <td className="num">0.6 (0 to 1)</td>
              <td className="num">{money(3000)}</td>
              <td />
            </tr>
          </tfoot>
        </table>
      </div>
      <p className="lib-date">
        In the real forecast each number will say where it came from, and a position with others inside it will
        sum them, with a way to open it by position.
      </p>
    </section>
  );
}
