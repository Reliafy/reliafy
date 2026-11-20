import { Link } from "react-router-dom";
import PageHeader from "./ui/PageHeader.jsx";
import { isNotFound, plainLoadError } from "./loadFailed.js";

// A detail page whose item didn't load (deleted, a mistyped link, no access):
// the reason, and a way on to the list it belongs to — never a bare
// "Not found." with nowhere to go.
//
// A missing item is an empty state (a neutral card), not an error; anything
// else (the server failed, no connection) keeps the red error card.
//
//   error     the message (or the Error) the load failed with; a raw server
//             message ("Internal Server Error", "Request failed (500)") is
//             never shown, plain words take its place
//   what      what didn't load, said first ("Couldn't load your datasets.");
//             the reason follows it
//   to/label  the list to go back to
//   notFound  what to say instead when the item is missing ("Location not
//             found."), for a server that only says "Not found."
//   header    true on a page that has no header of its own: adds one, titled
//             "Not found" (or "Couldn't open this"), so the page isn't blank
//   onRetry   loads it again: a "Try again" button under the reason (a part of
//             a page, or a page, whose read failed: Home's lists, the Explorer's tree)
//   className more classes on the card (where it sits in a page)
export default function LoadFailed({ error, what = null, to, label, notFound, header = false, onRetry = null, className = "" }) {
  const missing = isNotFound(error);
  const reason = missing && notFound ? notFound : plainLoadError(error);
  const text = what && !(missing && notFound) ? `${what} ${reason}` : reason;
  return (
    <>
      {header && <PageHeader title={missing ? "Not found" : "Couldn't open this"} />}
      <div className={"card load-failed" + (missing ? "" : " error") + (className ? ` ${className}` : "")}
           role={missing ? "status" : "alert"}>
        <p style={{ margin: 0 }}>{text}</p>
        {to && (
          <p style={{ margin: "6px 0 0" }}>
            {missing && <>It may have been deleted, or the link may be mistyped.{" "}</>}
            <Link to={to}>{label}</Link>
          </p>
        )}
        {onRetry && !missing && (
          <button type="button" className="secondary load-failed-retry" onClick={onRetry}>Try again</button>
        )}
      </div>
    </>
  );
}
