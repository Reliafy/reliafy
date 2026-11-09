import { useEffect, useState } from "react";
import { Navigate, useLocation, useParams } from "react-router-dom";
import { getMeasurementPoint, listSignalChannels } from "../api.js";
import LoadFailed from "../components/LoadFailed.jsx";
import { explorerPath } from "../assetTree.js";
import { measurementAddress } from "../measurementsTab.js";

// The earlier addresses of a measuring point's and a sensor channel's own
// pages (/asset-register/points/:id, /asset-register/channels/:id). Both now
// open inside the Explorer's Measurements tab with the tree on the left, which
// needs the position they're on: read the point or channel, then go there
// (keeping #bands). A static row in redirects.js can't, as the id alone
// doesn't say the position.

function Resolve({ read, kind, missing }) {
  const { id } = useParams();
  const { hash } = useLocation();
  const [to, setTo] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    let live = true;
    read(id).then((thing) => {
      if (!live) return;
      if (!thing) { setError("Not found"); return; }
      const where = measurementAddress(thing, kind, { bands: hash === "#bands" });
      // With no place to open it at, the Explorer's tab with the point or channel open.
      setTo(where.startsWith("/asset-register/explorer") ? where
        : `${explorerPath("positions", { tab: "measurements", [kind]: id })}${hash === "#bands" ? "#bands" : ""}`);
    }).catch((e) => live && setError(e.message));
    return () => { live = false; };
  }, [id, hash, kind, read]);
  if (to) return <Navigate to={to} replace />;
  if (error) {
    return (
      <div className="app">
        <LoadFailed header error={error} notFound={missing} to={explorerPath("positions", { tab: "measurements" })}
                    label="Go to the Explorer's measurements" />
      </div>
    );
  }
  return <div className="app"><div className="card empty">Loading…</div></div>;
}

const readPoint = (id) => getMeasurementPoint(id);
const readChannel = (id) => listSignalChannels().then((d) => (d.channels || []).find((c) => c.id === id) || null);

export function PointRedirect() {
  return <Resolve read={readPoint} kind="point" missing="Measuring point not found." />;
}

export function ChannelRedirect() {
  return <Resolve read={readChannel} kind="channel" missing="Sensor channel not found." />;
}
