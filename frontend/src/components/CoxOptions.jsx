import { useState } from "react";
import Select from "./Select.jsx";

// Cox PH's own fit options (#61), folded under "Advanced", as the plain
// distributions' are: how tied failure times are handled, a column to
// stratify on (a baseline hazard per level, no coefficient) and a column to
// cluster the robust standard errors by. ``value`` is { tie_method, strata,
// cluster } ("" = the default); ``columns`` are the data's columns that are
// free to use (not the time, status, count or a covariate).
const TIES = [
  { value: "", label: "Efron (default)" },
  { value: "breslow", label: "Breslow" },
  { value: "exact", label: "Exact" },
  { value: "kalbfleisch-prentice", label: "Kalbfleisch-Prentice" },
];

export default function CoxOptions({ value, onChange, columns = [] }) {
  const v = value || {};
  const active = ["tie_method", "strata", "cluster"].filter((k) => v[k]).length;
  const [open, setOpen] = useState(active > 0);
  const set = (key, val) => onChange({ ...v, [key]: val || "" });
  const none = [{ value: "", label: "None" }, ...columns.map((c) => ({ value: c, label: c }))];
  return (
    <div className="fitopts">
      <button type="button" className="fitopts-toggle" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        {open ? "▾" : "▸"} Advanced Cox options{active > 0 ? ` (${active} active)` : ""}
      </button>
      {open && (
        <div className="fitopts-body cox-opts">
          <label className="dist-field" style={{ width: 240 }}>
            <span className="dist-label">Tied failure times</span>
            <Select value={v.tie_method || ""} onChange={(x) => set("tie_method", x)} options={TIES} />
          </label>
          <label className="dist-field" style={{ width: 240 }}>
            <span className="dist-label">Stratify by</span>
            <Select value={v.strata || ""} onChange={(x) => set("strata", x)} options={none} />
          </label>
          <label className="dist-field" style={{ width: 240 }}>
            <span className="dist-label">Cluster robust errors by</span>
            <Select value={v.cluster || ""} onChange={(x) => set("cluster", x)} options={none} />
          </label>
          <p className="muted-line" style={{ margin: 0, width: "100%" }}>
            Stratify on a column whose levels fail differently in a way you don't need to measure (site,
            batch): each level gets its own baseline, and the covariates&rsquo; effects are shared. Cluster by a
            unit or group id when several rows come from one; the Validation tab then gives standard errors that
            allow for it.
          </p>
        </div>
      )}
    </div>
  );
}
