import { Component } from "react";
import { reportError } from "../telemetry.js";

// Catches render crashes so a bug shows a recoverable card instead of a
// white screen, and reports the error to the backend log.
export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    reportError(error?.message, `${error?.stack || ""}\n${info?.componentStack || ""}`);
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="app" style={{ padding: "2rem" }}>
        <div className="card error-boundary">
          <h2>Something went wrong</h2>
          <p className="muted-line">
            The page hit an unexpected error. It's been reported — reloading
            usually fixes it, and your saved work is safe on the server.
          </p>
          <div style={{ display: "flex", gap: "0.6rem" }}>
            <button onClick={() => window.location.reload()}>Reload</button>
            <button
              className="secondary"
              onClick={() => { window.location.href = "/modelling"; }}
            >
              Go to dashboard
            </button>
          </div>
        </div>
      </div>
    );
  }
}
