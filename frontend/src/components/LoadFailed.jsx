import { Link } from "react-router-dom";
import PageHeader from "./ui/PageHeader.jsx";
import { isNotFound } from "./loadFailed.js";

// A detail page whose item didn't load (deleted, a mistyped link, no access):
// the reason, and a way on to the list it belongs to — never a bare
// "Not found." with nowhere to go.
//
// A missing item is an empty state (a neutral card), not an error; anything
// else (the server failed, no connection) keeps the red error card.
//
//   error     the message the load failed with
//   to/label  the list to go back to
//   notFound  what to say instead when the item is missing ("Location not
//             found."), for a server that only says "Not found."
//   header    true on a page that has no header of its own: adds one, titled
//             "Not found" (or "Couldn't open this"), so the page isn't blank
export default function LoadFailed({ error, to, label, notFound, header = false }) {
  const missing = isNotFound(error);
  const text = missing && notFound ? notFound : error;
  return (
    <>
      {header && <PageHeader title={missing ? "Not found" : "Couldn't open this"} />}
      <div className={"card load-failed" + (missing ? "" : " error")} role={missing ? "status" : "alert"}>
        <p style={{ margin: 0 }}>{text}</p>
        {to && (
          <p style={{ margin: "6px 0 0" }}>
            {missing ? "It may have been deleted, or the link may be mistyped." : "Try again in a moment, or go back to the list."}{" "}
            <Link to={to}>{label}</Link>
          </p>
        )}
      </div>
    </>
  );
}
