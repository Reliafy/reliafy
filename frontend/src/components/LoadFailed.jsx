import { Link } from "react-router-dom";

// A detail page whose item didn't load (deleted, a mistyped link, no access):
// the reason, and a way on to the list it belongs to — never a bare
// "Not found." with nowhere to go.
export default function LoadFailed({ error, to, label }) {
  return (
    <div className="card error" role="alert">
      <p style={{ margin: 0 }}>{error}</p>
      {to && (
        <p style={{ margin: "6px 0 0" }}>
          It may have been deleted, or the link may be mistyped. <Link to={to}>{label}</Link>
        </p>
      )}
    </div>
  );
}
