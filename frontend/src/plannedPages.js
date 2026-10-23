// Pages that are in the menu so its structure can be tried before they are
// built. They show only where the deployment turns the menu preview on
// (MENU_PREVIEW, from /api/config); everywhere else the menu hides them.
// Each is a blank page that says what it will hold.
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
  risk: {
    title: "Risk",
    purpose: "Live risk from your block diagrams, kept current by what is fitted and what the sensors say.",
    will: [
      "Diagrams whose blocks follow the item fitted at their position",
      "Condition-monitoring alarms and remaining life per block",
      "What to fix first, recalculated as readings arrive",
      "Positions most at risk in the next 30 days",
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
  "fault-trees": {
    section: "systems",
    title: "Fault trees",
    purpose: "Work back from an unwanted event to the combinations of failures that cause it.",
    will: [
      "Build a tree from gates and basic events",
      "Top-event probability and the cut sets that drive it",
      "Link basic events to your models",
    ],
  },
  fmeca: {
    section: "systems",
    title: "FMECA",
    purpose: "Failure modes, their effects and how critical each one is, for a design.",
    will: [
      "Failure modes per function, with severity, occurrence and detection",
      "Criticality ranking",
      "Links to the RCM study and its tasks",
    ],
  },
};
