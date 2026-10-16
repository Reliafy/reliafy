// "If we hold [n]" (#31): the chance a stock runs out, read off a spares
// answer's risk curve as the user types, for the class and fleet forecasts.
import { useEffect, useState } from "react";
import { riskAt, riskText } from "../sparesPlan.js";

// "If we hold [n]": the chance of running out, from the answer's risk curve.
export default function SparesWhatIf({ curve, unit, over, initial, idPrefix }) {
  const [stock, setStock] = useState(initial ?? "");
  useEffect(() => { setStock(initial ?? ""); }, [initial]);
  const p = riskAt(curve, stock);
  return (
    <p style={{ display: "flex", alignItems: "center", flexWrap: "wrap", gap: "0.4rem" }}>
      <label htmlFor={`${idPrefix}-whatif`}>If we hold</label>
      <input id={`${idPrefix}-whatif`} type="number" inputMode="decimal" min="0" step="any" value={stock}
             style={{ width: "5rem" }} onChange={(e) => setStock(e.target.value)} />
      {unit && unit !== "each" && <span>{unit}</span>}
      <span data-testid="spares-whatif">
        {p == null ? "" : <>→ <b>{riskText(p)}</b> chance of running out over {over}.</>}
      </span>
    </p>
  );
}
