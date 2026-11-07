import { useCallback, useEffect, useState } from "react";
import { useLocation, useParams } from "react-router-dom";
import { listSignalChannels } from "../api.js";
import LoadFailed from "../components/LoadFailed.jsx";
import PageHeader from "../components/ui/PageHeader.jsx";
import { ChannelView } from "../components/SignalsPanel.jsx";
import SignalStorage from "../components/SignalStorage.jsx";
import { PageTitle } from "../components/usePageTitle.js";
import { explorerPath } from "../assetTree.js";
import { channelPlace } from "../measurementsTab.js";
import "./Maintenance.css";

// One signal channel (/asset-register/channels/:id): a sensor that sends
// snapshots (a vibration burst, a device's spectrum, a smart plug's power).
// It's a row of the Explorer's Measurements tab, beside the hand-read points on
// its position; this page holds what the row can't: the spectrum and its
// player, the watch bands and levels (#bands: a row's "Edit bands…"), the
// level over time, and the channel's settings.

const EXPLORER_TAB = "measurements";

// Where the channel is in the Explorer: its position's row (a fitted item's
// position, else the item's row in Locations), on the Measurements tab.
function placeCrumb(ch) {
  const label = channelPlace(ch) || "Its place";
  if (ch.position?.id) return { label, to: explorerPath("positions", { sel: ch.position.id, tab: EXPLORER_TAB }) };
  if (ch.item?.fitted_to?.id) return { label, to: explorerPath("positions", { sel: ch.item.fitted_to.id, tab: EXPLORER_TAB }) };
  if (ch.item?.id) return { label, to: explorerPath("locations", { sel: ch.item.id, tab: EXPLORER_TAB }) };
  return null;
}

export default function SignalChannel() {
  const { id } = useParams();
  const { hash } = useLocation();
  const [all, setAll] = useState(null);
  const [error, setError] = useState(null);
  const [tick, setTick] = useState(0);
  const load = useCallback(() => listSignalChannels()
    .then((d) => { setAll(d.channels || []); setError(null); })
    .catch((e) => setError(e.message)), []);
  useEffect(() => { load(); }, [load]);

  const ch = all?.find((c) => c.id === id);
  const back = explorerPath("positions", { tab: EXPLORER_TAB });
  if ((error && !all) || (all && !ch)) {
    return (
      <div className="app">
        <LoadFailed header error={error || "Not found"} notFound="Sensor channel not found." to={back}
                    label="Go to the Explorer's measurements" />
      </div>
    );
  }
  if (!ch) return <div className="app"><div className="card empty">Loading…</div></div>;
  const place = placeCrumb(ch);
  const meta = ["Sensor channel", ch.unit, ch.tag && `tag ${ch.tag}`, ch.axes?.length > 1 && `axes ${ch.axes.join(", ")}`]
    .filter(Boolean).join(" · ");
  return (
    <div className="app sg-page">
      <PageTitle name={ch.name} />
      <PageHeader
        crumbs={[{ label: "Assets", to: "/asset-register" }, { label: "Explorer", to: explorerPath("positions") }, ...(place ? [place] : [])]}
        title={ch.name}
        meta={meta}
        id={ch.id}
      />
      <div className="sg">
        <SignalStorage refresh={tick} />
        <ChannelView key={ch.id} summary={ch} all={all} focusBands={hash === "#bands"}
                     onChanged={() => { setTick((t) => t + 1); return load(); }} />
      </div>
    </div>
  );
}
