import { relativeTime } from "../instrument.js";
import { CATEGORY } from "../plotTheme.js";
import Chip from "../components/ui/Chip.jsx";
import { useNavigate } from "react-router-dom";
import { RowActions, RowLink, itemName, rowOpen } from "../components/LibRows.jsx";
import { SectionList } from "../components/SectionPage.jsx";

const ALT_COLOR = CATEGORY.teal;

// Saved accelerated-life models, laid out like the life-data and recurrent
// lists. ``models`` is null while loading.
export default function AltLibrary({ models, hrefFor, onDelete, help, empty }) {
  const navigate = useNavigate();
  return (
    <SectionList
      rows={models}
      noun={["model", "models"]}
      fields={(m) => [m.name, m.distribution, m.life_model]}
      help={help}
      empty={empty}
      head={[
        <th key="m" style={{ width: "36%" }}>Model</th>,
        <th key="l">Life–stress</th>,
        <th key="s" className="lib-opt" style={{ width: 80 }}>Stresses</th>,
        <th key="n" className="lib-opt" style={{ width: 70 }}>n</th>,
        <th key="d" className="lib-opt">Saved</th>,
        <th key="a"><span className="sr-only">Actions</span></th>,
      ]}
      render={(m) => (
        <tr key={m.id} className="lib-row" onClick={rowOpen(navigate, hrefFor(m.id))}>
          <td>
            <div className="lib-name">
              <RowLink to={hrefFor(m.id)}>{itemName(m)}</RowLink>
              {m.shared_by && <Chip title={`Shared by ${m.shared_by}`}>Shared</Chip>}
            </div>
          </td>
          <td>
            <Chip dot={ALT_COLOR}>
              {[m.distribution, m.life_model].filter(Boolean).join(" · ") || "—"}
            </Chip>
          </td>
          <td className="lib-n lib-opt">{m.n_stresses ?? 1}</td>
          <td className="lib-n lib-opt">{(m.n ?? 0).toLocaleString()}</td>
          <td className="lib-date lib-opt">{relativeTime(m.created_at)}</td>
          <RowActions item={m} to={hrefFor(m.id)} onDelete={() => onDelete(m)} />
        </tr>
      )}
    />
  );
}
