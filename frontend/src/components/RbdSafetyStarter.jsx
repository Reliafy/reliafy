import { Link } from "react-router-dom";
import { openGuide } from "./HelpButton.jsx";

const ShieldIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
       aria-hidden="true">
    <path d="M12 3 4.5 6v5.5c0 4.6 3.1 8.2 7.5 9.5 4.4-1.3 7.5-4.9 7.5-9.5V6Z" />
    <path d="m8.8 12.2 2.2 2.2 4.2-4.4" />
  </svg>
);

// "Verify a safety function (SIL / PFDavg)" (#298), on the home, RBD and
// Strategy pages: one slim card that opens the starter diagram — sensors
// voting 1oo2, a logic solver and a final element — in safety mode, unsaved.
export default function SafetyStarterCard() {
  return (
    <div className="sif-card">
      <span className="sif-card-ic"><ShieldIcon /></span>
      <div className="sif-card-body">
        <b>Verify a safety function (SIL / PFDavg)</b>
        <span>
          Sensors voting 1oo2, a logic solver and a final element: the PFDavg, the SIL it reaches (IEC 61511) and
          which element dominates.{" "}
          <button type="button" className="link" onClick={() => openGuide("verify-a-safety-function")}>
            How it works
          </button>
        </span>
      </div>
      <Link className="sif-card-cta" to="/rbds/b" state={{ starter: "safety" }}>
        Open the starter →
      </Link>
    </div>
  );
}
