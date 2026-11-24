// What a page's address asks it to show already worked out (Derryn, 25 Nov 2026: a demonstration
// run as a script, one link a step, "I can't do all these actions in front of a team"). Each is
// read once, as the page opens; the page works as before without them. Pure, tested in
// urlAsks.test.js.
//
//   RBD builder        ?tab=calc|tree|design|targets|outages   the tab it opens on
//                      ?calc=1                                  Calculate pressed on opening
//                      ?compare=<rbd id>                        Compare with… that diagram, worked out
//   Repairable model   ?next=<hours>                            Calculator › From now on, worked out
//                      ?repair=<$>&overhaul=<$>                 Plan ahead › Overhaul interval, worked out
//   Dataset            ?compare=<column>&run=1                  Compare groups, worked out
//   Life model         ?calc=time                               Calculator on Time at reliability
//   Explorer History   ?status=<chip>  ?fview=ranking  ?group=failure_mode|part|position
//                      ?rank=failures|rate|downtime|cost  ?window=12m|all

// The address's query string now (none where there's no window: prerendering, some tests).
function search() {
  return typeof window !== "undefined" && window.location ? window.location.search : "";
}

// One value the address asks for, or null.
export function urlAsk(name, query = search()) {
  const v = new URLSearchParams(query || "").get(name);
  return v == null || v === "" ? null : v;
}

// A positive number the address asks for (as typed, for an input box), or null.
export function positiveAsk(name, query = search()) {
  const v = urlAsk(name, query);
  return v != null && Number(v) > 0 && Number.isFinite(Number(v)) ? v : null;
}

// One of `allowed` the address asks for, or `fallback`.
export function choiceAsk(name, allowed, fallback = null, query = search()) {
  const v = urlAsk(name, query);
  return v != null && allowed.includes(v) ? v : fallback;
}
