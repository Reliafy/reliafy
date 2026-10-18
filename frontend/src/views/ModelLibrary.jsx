import { distColor, relativeTime } from "../instrument.js";
import Chip from "../components/ui/Chip.jsx";
import { RowActions, itemName } from "../components/LibRows.jsx";
import { SectionList } from "../components/SectionPage.jsx";
import { distLabel } from "../allModels.js";

// The saved life-data models: the section list (search, your own models,
// then the shared samples). ``models`` is null while loading.
export default function ModelLibrary({ models, onOpen, onDelete, help, empty }) {
  return (
    <SectionList
      rows={models}
      noun={["model", "models"]}
      fields={(m) => [m.name, m.distribution]}
      help={help}
      empty={empty}
      head={[
        <th key="m" style={{ width: "40%" }}>Model</th>,
        <th key="d">Distribution</th>,
        <th key="n" className="lib-opt" style={{ width: 80 }}>n</th>,
        <th key="s" className="lib-opt">Saved</th>,
        <th key="a"><span className="sr-only">Actions</span></th>,
      ]}
      render={(m) => (
        <tr key={m.id} className="lib-row" onClick={() => onOpen(m.id)}>
          <td>
            <div className="lib-name">
              {itemName(m)}
              {m.shared_by && <Chip title={`Shared by ${m.shared_by}`}>Shared</Chip>}
            </div>
          </td>
          <td>
            <Chip dot={distColor(m.distribution)}>
              {distLabel(m.distribution)}
              {m.kind === "regression" && " · PH"}
            </Chip>
          </td>
          <td className="lib-n lib-opt">{(m.n ?? 0).toLocaleString()}</td>
          <td className="lib-date lib-opt">{relativeTime(m.created_at)}</td>
          <RowActions item={m} onOpen={() => onOpen(m.id)} onDelete={() => onDelete(m)} />
        </tr>
      )}
    />
  );
}
