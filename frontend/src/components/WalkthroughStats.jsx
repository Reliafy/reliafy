import Card, { CardHeader } from "./ui/Card.jsx";
import ScrollCue from "./ui/ScrollCue.jsx";
import { formatPercent } from "../format.js";
import { getWalkthrough, stepFunnel } from "../walkthroughs.js";

// The operator page's walkthrough report (#32): per walkthrough, runs started,
// completed and skipped, the completion rate, and how many runs reached each
// step. ``rows`` is the traffic report's ``walkthroughs``.
export default function WalkthroughStats({ rows }) {
  if (!rows || rows.length === 0) return null;
  const any = rows.some((r) => r.started > 0);
  return (
    <Card style={{ marginTop: "1rem" }}>
      <CardHeader title="Walkthroughs" />
      {!any ? (
        <p className="muted-line">No walkthroughs started in this window.</p>
      ) : (
        <ScrollCue className="usage-table-wrap">
          <table className="usage-table">
            <thead>
              <tr>
                <th>Walkthrough</th>
                <th>Started</th>
                <th>Completed</th>
                <th>Skipped</th>
                <th>Completion</th>
                <th style={{ textAlign: "left" }}>Reached step 1, 2, …</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.key}>
                  <td style={{ textAlign: "left" }}>{getWalkthrough(r.key)?.title || r.key}</td>
                  <td>{r.started}</td>
                  <td>{r.completed}</td>
                  <td>{r.skipped}</td>
                  <td>{r.completion_rate == null ? "—" : formatPercent(r.completion_rate)}</td>
                  <td style={{ textAlign: "left" }}>{stepFunnel(r, r.key).join(" → ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </ScrollCue>
      )}
    </Card>
  );
}
