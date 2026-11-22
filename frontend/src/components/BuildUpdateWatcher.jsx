import { useEffect, useReducer, useRef } from "react";
import { useLocation } from "react-router-dom";
import { currentBuildAction, reloadForBuild, subscribeBuild } from "../buildCheck.js";

// Mounted once, inside the router. Reloads at a route change when the server has
// been updated and nothing is unsaved; with unsaved work, shows a slim bar.
export default function BuildUpdateWatcher() {
  const [, bump] = useReducer((n) => n + 1, 0);
  const { pathname } = useLocation();
  const first = useRef(true);
  useEffect(() => subscribeBuild(bump), []);
  useEffect(() => {
    if (first.current) { first.current = false; return; }
    if (currentBuildAction() === "reload") reloadForBuild();
  }, [pathname]);
  if (currentBuildAction() !== "bar") return null;
  return (
    <div className="verify-banner" role="status">
      <div className="verify-banner-text">
        <b>Reliafy has been updated.</b> Reload when you're ready. Your unsaved changes stay until you do.
      </div>
      <div className="verify-banner-actions">
        <button type="button" className="secondary" onClick={reloadForBuild}>Reload</button>
      </div>
    </div>
  );
}
