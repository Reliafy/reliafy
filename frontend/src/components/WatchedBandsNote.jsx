import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { listSignalChannels } from "../api.js";
import { useRoles } from "../RolesProvider.jsx";

// Risk › Condition monitoring: a line for the people who use Maintenance, pointing at the signal channels
// whose watched bands can be fitted for their time to the limit (Assets › Explorer › Signals).
export default function WatchedBandsNote() {
  const { has } = useRoles();
  const [channels, setChannels] = useState(null);
  useEffect(() => {
    if (!has.maintenance) return;
    listSignalChannels().then((d) => setChannels(d.channels || [])).catch(() => setChannels([]));
  }, [has.maintenance]);
  if (!has.maintenance || !channels || channels.length === 0) return null;
  const link = (c) => {
    const on = c.item || c.position;
    return `/asset-register/explorer?arrange=${c.item ? "items" : "positions"}&sel=${on?.id}&tab=signals`;
  };
  return (
    <section className="card" aria-label="Signal channels">
      <p className="sg-meta">
        Signal channels: see when a watched band is expected to reach its limit, and send its trend here.{" "}
        {channels.slice(0, 5).map((c, i) => (
          <span key={c.id}>{i ? ", " : ""}<Link to={link(c)}>{c.name}</Link></span>
        ))}
        {channels.length > 5 ? ` and ${channels.length - 5} more` : ""}.
      </p>
    </section>
  );
}
