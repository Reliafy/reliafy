import { MCP_CONTACT } from "../appConfig.js";

// Shown where the app would tell people to connect Claude or another agent,
// while the MCP connector is switched off (config.mcp false).
export default function McpOnRequest({ className = "muted-line" }) {
  return (
    <p className={className}>
      The MCP connector is available on request: email{" "}
      <a href={`mailto:${MCP_CONTACT}`}>{MCP_CONTACT}</a>.
    </p>
  );
}
