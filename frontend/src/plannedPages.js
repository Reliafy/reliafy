// Blank pages for things not built yet, each saying what it will hold. They
// show only where the deployment turns the menu preview on (MENU_PREVIEW, from
// /api/config); everywhere else a visit says the page isn't available. Library
// (under Data) and Field inbox (under Maintenance) are in the preview menu;
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
    title: "Field inbox",
    purpose: "Field reports sent from the mobile app: notes, photos and recordings to read and act on.",
    will: [
      "Newest first, with status, author and what each report points at",
      "A report's notes, photos and audio side by side",
      "Mark a report handled and link what was made from it",
    ],
  },
  library: {
    section: "data",
    title: "Library",
    purpose: "Published reliability data to start from when you have none of your own.",
    will: [
      "Cited failure-rate and Weibull records, each with its source and licence",
      "Search by part or equipment type",
      "Use a record as a block's life model, marked as a generic estimate",
    ],
  },
};
