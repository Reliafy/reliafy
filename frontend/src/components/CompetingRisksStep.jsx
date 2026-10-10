import Select from "./Select.jsx";
import "./CompetingRisks.css";

// The fit wizard's Model step when a failure-mode column is mapped (#177):
// the modes are fitted as competing risks. Without covariates that is the
// non-parametric cumulative incidence; with them, the advanced choice of a
// regression per mode. Gray's test compares groups when a column is picked.
export const CR_OPTIONS = [
  { id: "competing_risks", name: "Competing risks (by failure mode)", covariates: false,
    blurb: "Each mode's chance of causing a failure by each time, with the other modes still acting. "
      + "No distribution assumed." },
  { id: "competing_risks_cox", name: "Cause-specific Cox", covariates: true,
    blurb: "How each covariate changes the failure rate from each mode, among units still running." },
  { id: "competing_risks_fine_gray", name: "Fine-Gray", covariates: true,
    blurb: "How each covariate changes the chance of failing from each mode, with the other modes acting." },
];

export default function CompetingRisksStep({ options, value, onChange, columns, mapping, onMapping }) {
  const selected = options.find((o) => o.id === value) || options[0];
  const taken = new Set(["x", "c", "n", "e"].map((k) => mapping[k]).filter(Boolean));
  const groupOptions = [
    { value: "", label: "— none —" },
    ...columns.filter((c) => !taken.has(c)).map((c) => ({ value: c, label: c })),
  ];
  return (
    <div className="dist-picker">
      <div className="dist-field">
        <span className="dist-label">Model</span>
        <Select value={selected?.id} onChange={onChange}
                options={options.map((o) => ({ value: o.id, label: o.name }))} />
      </div>
      {selected && <p className="dist-blurb">{selected.blurb}</p>}
      <div className="dist-field cr-group-field">
        <span className="dist-label">Compare groups (optional)</span>
        <Select value={mapping.g || ""} onChange={(g) => onMapping({ ...mapping, g })} options={groupOptions} />
      </div>
      <p className="dist-blurb">
        Pick a column such as site or supplier: Gray's test then asks whether each mode's chance differs
        between its groups.
      </p>
    </div>
  );
}
