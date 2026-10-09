import { useEffect, useRef, useState } from "react";
import Modal from "./Modal.jsx";
import Select from "./Select.jsx";
import ExcelSheetPicker, { useExcelInspection } from "./ExcelSheetPicker.jsx";
import SheetColumnMapper, { mappingComplete } from "./SheetColumnMapper.jsx";
import { downloadRbdTemplate, excelTable, importRbdFile } from "../api.js";

const BLOCK_SHEETS = /^(blocks?|components?|rbd|diagram)$/i;
const LINK_SHEETS = /^(connections?|links|edges|arrows|wiring)$/i;
const SKIP_SHEETS = /^(readme|read me|instructions|notes|help|about)$/i;
const NO_LINKS = "";

// An Excel workbook that isn't laid out like the RBD template: say which sheet
// holds the blocks and which columns mean what (and, optionally, which sheet
// lists the connections), then import it through the regular RBD importer.
export default function RbdExcelImportModal({ file, message, onClose, onImported }) {
  const { inspection, error: inspectError, loading } = useExcelInspection(file);
  const [step, setStep] = useState("sheet"); // sheet | map
  const [blocksSel, setBlocksSel] = useState(null);
  const [blocks, setBlocks] = useState(null); // table response
  const [blockMap, setBlockMap] = useState({});
  const [linkSheet, setLinkSheet] = useState(NO_LINKS);
  const [links, setLinks] = useState(null);
  const [linkMap, setLinkMap] = useState({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const errorRef = useRef(null);
  useEffect(() => {
    if (error) errorRef.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [error]);
  const sheets = inspection?.sheets || [];

  useEffect(() => {
    if (!sheets.length) return;
    const usable = sheets.filter((s) => s.rows > 0 && !SKIP_SHEETS.test(s.name.trim()));
    const first = usable.find((s) => BLOCK_SHEETS.test(s.name.trim())) || usable[0] || sheets[0];
    setBlocksSel({ sheet: first.name, headerRow: first.guessed_header_row });
    const linkGuess = usable.find((s) => s.name !== first.name && LINK_SHEETS.test(s.name.trim()));
    setLinkSheet(linkGuess ? linkGuess.name : NO_LINKS);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [inspection]);

  // Connections sheet table (header row = its guess).
  useEffect(() => {
    if (step !== "map" || !linkSheet) { setLinks(null); return undefined; }
    let live = true;
    const s = sheets.find((x) => x.name === linkSheet);
    excelTable(file, linkSheet, s?.guessed_header_row, "rbd_connections")
      .then((t) => { if (live) { setLinks(t); setLinkMap(t.guess || {}); } })
      .catch((e) => { if (live) { setLinks(null); setError(e.message); } });
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step, linkSheet, file]);

  const toMapping = async () => {
    setBusy(true);
    setError(null);
    try {
      const t = await excelTable(file, blocksSel.sheet, blocksSel.headerRow, "rbd_blocks");
      setBlocks(t);
      setBlockMap(t.guess || {});
      if (linkSheet === blocksSel.sheet) setLinkSheet(NO_LINKS);
      setStep("map");
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const blocksOk = blocks && mappingComplete(blocks.fields, blockMap, ["id", "label"]);
  const linksOk = !linkSheet || (links && mappingComplete(links.fields, linkMap));

  const doImport = async () => {
    setBusy(true);
    setError(null);
    try {
      const mapping = {
        blocks: { sheet: blocks.sheet, header_row: blocks.header_row, mapping: blockMap },
        connections: linkSheet && links
          ? { sheet: links.sheet, header_row: links.header_row, mapping: linkMap }
          : null,
      };
      onImported(await importRbdFile(file, mapping));
    } catch (e) {
      setError(e.message);
      setBusy(false);
    }
  };

  const footer = step === "sheet" ? (
    <>
      <button className="secondary" onClick={onClose} disabled={busy}>Cancel</button>
      <button onClick={toMapping} disabled={busy || !blocksSel}>{busy ? "Reading…" : "Next: map columns"}</button>
    </>
  ) : (
    <>
      <button className="secondary" onClick={() => setStep("sheet")} disabled={busy}>Back</button>
      <button onClick={doImport} disabled={busy || !blocksOk || !linksOk}>{busy ? "Importing…" : "Import diagram"}</button>
    </>
  );

  return (
    <Modal title={`Import RBD from ${file.name}`} className="modal-xl" locked={busy} onClose={onClose} footer={footer}>
      {step === "sheet" && (
        <div className="fit-step">
          <p className="muted-line" style={{ margin: 0 }}>
            {message || "This workbook isn't laid out like Reliafy's RBD template."} Pick the sheet that lists
            the blocks (one row per block) and its header row, then map its columns.{" "}
            <button className="link" onClick={() => downloadRbdTemplate().catch((e) => setError(e.message))}>
              Download the template
            </button>
          </p>
          {loading && <p className="hint">Reading the workbook…</p>}
          {inspectError && <div className="error">{inspectError}</div>}
          {inspection && blocksSel && (
            <ExcelSheetPicker inspection={inspection} value={blocksSel} onChange={setBlocksSel} sheetLabel="Blocks sheet" />
          )}
        </div>
      )}

      {step === "map" && blocks && (
        <div className="fit-step">
          <div className="xl-rbd-section">
            <div className="ds-section-h">Blocks · {blocks.sheet} · {blocks.n_rows} rows</div>
            <p className="hint" style={{ margin: 0 }}>
              Each block needs an ID or a name, and (unless it's a k-of-n node) a failure distribution
              with its parameters — Weibull (alpha, beta), Exponential (failure rate or MTTF),
              Lognormal / Normal (mu, sigma), Gamma, LogLogistic, Gumbel, Logistic, Rayleigh.
            </p>
            <SheetColumnMapper fields={blocks.fields} columns={blocks.columns} mapping={blockMap}
                               onChange={setBlockMap} rows={blocks.rows} requireOneOf={["id", "label"]}
                               collapsed={["Repair", "Type extras"]} />
          </div>
          <div className="xl-rbd-section">
            <div className="ds-section-h">Connections sheet</div>
            <label className="xl-inline">
              <span>Connections sheet</span>
              <Select
                value={linkSheet}
                onChange={setLinkSheet}
                options={[
                  { value: NO_LINKS, label: "None — use Feeds / Fed by columns (or connect in series)" },
                  ...sheets.filter((s) => s.name !== blocks.sheet && s.rows > 0).map((s) => ({ value: s.name, label: s.name })),
                ]}
              />
            </label>
            {linkSheet && links && (
              <SheetColumnMapper fields={links.fields} columns={links.columns} mapping={linkMap}
                                 onChange={setLinkMap} rows={links.rows} />
            )}
            <p className="hint" style={{ margin: 0 }}>
              Blocks with nothing feeding them connect from the diagram's input; blocks feeding nothing
              connect to its output.
            </p>
          </div>
        </div>
      )}
      {error && <div className="error" ref={errorRef}>{error}</div>}
    </Modal>
  );
}
