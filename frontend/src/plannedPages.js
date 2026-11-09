// Blank pages for things not built yet, each saying what it will hold. They
// show only where the deployment turns the menu preview on (MENU_PREVIEW, from
// /api/config); everywhere else a visit says the page isn't available. Library
// (under Data) and Requests (under Maintenance) are in the preview menu;
// Requirements, Failures and Fleets have no place in the menu for now and are
// opened by address only.
export const PLANNED = {
  requirements: {
    title: "Requirements",
    purpose: "Targets for each system, allocated down to its parts and checked at every design review.",
    will: [
      "Reliability, availability and maintainability targets, with where each came from",
      "Allocation from a system down to its blocks",
      "Compliance at each review: the target, the prediction and the gap",
    ],
  },
  failures: {
    title: "Failures",
    purpose: "From a failure report to the fix, and whether the fix worked.",
    will: [
      "Failure reports and investigations, linked to the item, position and work order",
      "Corrective actions with owners and dates",
      "\"Did the change work?\": a before-and-after check on the failure rate",
    ],
  },
  fleets: {
    section: "assets",
    title: "Fleets",
    purpose: "A collection of items you look after together: a list you pick, or a query that stays current.",
    will: [
      "Members: where each item is, its age, state and open work",
      "Pooled life data, the fitted model and growth over time",
      "What is due across the fleet, spares cover and budget",
    ],
  },
  inbox: {
    section: "maintenance",
    title: "Requests",
    purpose: "Someone asking for work to be done, or for a record to be corrected, to review and act on.",
    will: [
      "Newest first, with status, who asked and what each request points at",
      "A request's notes, photos and the data it says is wrong, side by side",
      "Accept or decline a request, and link the work or correction made from it",
    ],
  },
};
