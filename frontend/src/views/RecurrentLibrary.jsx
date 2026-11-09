import { relativeTime } from "../instrument.js";
import Chip from "../components/ui/Chip.jsx";
import { useNavigate } from "react-router-dom";
import { RowActions, RowLink, itemName, rowOpen } from "../components/LibRows.jsx";
import { SectionList } from "../components/SectionPage.jsx";

// Growth verdict → chip tone: green is the good verdict, red the bad one.
const GROWTH = {
  improving: { label: "Improving", tone: "success" },
  stable: { label: "Stable", tone: "neutral" },
  deteriorating: { label: "Deteriorating", tone: "danger" },
};

// Saved recurrent-event models, laid out like the life-data model list.
// ``models`` is null while loading.
export default function RecurrentLibrary({ models, hrefFor, onDelete, help, empty }) {
  const navigate = useNavigate();
  return (
    <SectionList
      rows={models}
      noun={["model", "models"]}
      fields={(m) => [m.name, m.model, m.growth]}
      help={help}
      empty={empty}
      head={[
        <th key="m" style={{ width: "36%" }}>Model</th>,
        <th key="g">Growth</th>,
        <th key="s" className="lib-opt" style={{ width: 90 }}>Systems</th>,
        <th key="f" className="lib-opt" style={{ width: 90 }}>Failures</th>,
        <th key="d" className="lib-opt">Saved</th>,
        <th key="a"><span className="sr-only">Actions</span></th>,
      ]}
      render={(m) => {
        // No verdict (an imperfect-repair model, say): an empty cell, not a "—" chip.
        const g = m.growth ? GROWTH[m.growth] || { label: m.growth, tone: "neutral" } : null;
        return (
          <tr key={m.id} className="lib-row" onClick={rowOpen(navigate, hrefFor(m.id))}>
            <td>
              <div className="lib-name">
                <RowLink to={hrefFor(m.id)}>{itemName(m)}</RowLink>
                {m.shared_by && <Chip title={`Shared by ${m.shared_by}`}>Shared</Chip>}
              </div>
            </td>
            <td>{g && <Chip tone={g.tone}>{g.label}</Chip>}</td>
            <td className="lib-n lib-opt">{(m.n_systems ?? 0).toLocaleString()}</td>
            <td className="lib-n lib-opt">{m.n_events != null ? m.n_events.toLocaleString() : "—"}</td>
            <td className="lib-date lib-opt">{relativeTime(m.created_at)}</td>
            <RowActions item={m} to={hrefFor(m.id)} onDelete={() => onDelete(m)} />
          </tr>
        );
      }}
    />
  );
}
