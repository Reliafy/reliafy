import { useState } from "react";
import { ROLES } from "../navigation.js";
import { useRoles } from "../RolesProvider.jsx";
import Button from "./ui/Button.jsx";
import Card, { CardHeader } from "./ui/Card.jsx";
import Chip from "./ui/Chip.jsx";

const sameList = (a, b) => a.length === b.length && a.every((x, i) => x === b[i]);

// "What do you do?" (#438): pick any roles, in order; the first is the
// primary role. `value` and `onChange` carry the role ids.
export default function RolePicker({ value, onChange, disabled = false }) {
  return (
    <div className="role-picker" role="group" aria-label="What do you do?">
      {ROLES.map((r) => {
        const at = value.indexOf(r.id);
        return (
          <label key={r.id} className={"role-option" + (at >= 0 ? " on" : "")}>
            <input
              type="checkbox"
              checked={at >= 0}
              disabled={disabled}
              onChange={() => onChange(at >= 0 ? value.filter((x) => x !== r.id) : [...value, r.id])}
            />
            <span className="role-option-label">{r.label}</span>
            {at === 0 && value.length > 1 && <Chip tone="accent">Primary</Chip>}
          </label>
        );
      })}
    </div>
  );
}

const EXPLAIN = "The menu shows what your roles use first, and keeps the rest one click away under More. "
  + "Home leads with your first pick. Pick none to see everything.";

// The picker as a card: Settings' (`offer` false) and Home's one-time question
// to a new user (`offer`: "Not now" instead of "Show everything").
export function RolesCard({ offer = false, style }) {
  const { roles, loaded, saveRoles, dismissOffer } = useRoles();
  const [picked, setPicked] = useState(null); // null: the saved roles
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const value = picked ?? roles;
  const changed = picked !== null && !sameList(picked, roles);

  const save = async (next) => {
    setBusy(true);
    setError("");
    setSaved(false);
    try {
      await saveRoles(next);
      setPicked(null);
      setSaved(true);
    } catch {
      setError("Couldn't save that — please try again.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card className={offer ? "roles-offer" : undefined} style={style}>
      <CardHeader title="What do you do?" subtitle={EXPLAIN} />
      <RolePicker value={value} onChange={(v) => { setPicked(v); setSaved(false); }} disabled={!loaded || busy} />
      <div className="row role-actions">
        {offer ? (
          <>
            <Button onClick={() => save(value)} disabled={busy || !value.length}>
              {busy ? "Saving…" : "Save"}
            </Button>
            <Button variant="secondary" onClick={dismissOffer} disabled={busy}>Not now</Button>
          </>
        ) : (
          <>
            <Button onClick={() => save(value)} disabled={busy || !changed}>
              {busy ? "Saving…" : "Save"}
            </Button>
            {roles.length > 0 && (
              <Button variant="secondary" onClick={() => save([])} disabled={busy}>Show everything</Button>
            )}
            {saved && <span className="muted-line" role="status">Saved.</span>}
          </>
        )}
      </div>
      {error && <div className="error" style={{ marginBottom: 0 }}>{error}</div>}
    </Card>
  );
}
