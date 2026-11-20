import { downloadCsv } from "../csv.js";
import { DownloadIcon } from "./Plot.jsx";

// "Download CSV" on a card: the table the card shows, at full precision, with
// the units and any bound's confidence in the column names. The same quiet
// look as a chart's PNG and SVG buttons; it sits at the right of the card's
// heading. ``rows``: a function giving [[header…], …] when clicked;
// ``filename`` from csvFileName; ``what`` names it to a screen reader.
export default function CsvButton({ rows, filename, what = "this table", className = "" }) {
  return (
    <button type="button" className={"plot-dl-btn csv-btn" + (className ? " " + className : "")}
            title="Download CSV" aria-label={`Download ${what} as CSV`}
            onClick={() => downloadCsv(rows(), filename)}>
      <DownloadIcon /> CSV
    </button>
  );
}
