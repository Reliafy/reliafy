import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { listFailureReports } from "../api.js";
import { explorerPath } from "../assetTree.js";
import { modeReportsLink } from "../explorerRcm.js";

// A failure mode's failure reports, as one line in its panel: "2 failure reports · Open"
// (the review that closes the FRACAS loop starts from them). One report opens itself; several
// open the position's Failure reports tab. Nothing shows while there are none.
export default function ModeFailureReports({ modeId, positionId }) {
  const [found, setFound] = useState(null);
  useEffect(() => {
    let alive = true;
    setFound(null);
    if (!modeId) return undefined;
    listFailureReports({ failure_mode_id: modeId, limit: 1 })
      .then((out) => { if (alive) setFound({ total: out?.total || 0, first: out?.reports?.[0] || null }); })
      .catch(() => { if (alive) setFound(null); });
    return () => { alive = false; };
  }, [modeId]);
  const link = modeReportsLink(found, positionId);
  if (!link) return null;
  return (
    <p className="rw-mode-reports">
      {link.words} · <Link to={explorerPath("positions", link.query)} title={link.title}>Open</Link>
    </p>
  );
}
