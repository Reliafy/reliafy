import { NO_BLOCKS } from "../rbdReadiness.js";

// What a builder tab shows while the diagram has nothing to analyse (#271):
// only Input and Output, or blocks not yet on a path between them. A next
// step, not an error — and the tab doesn't call the API meanwhile.
// ``goal`` finishes "Add blocks between Input and Output to …".
export default function RbdEmptyState({ gap, goal, onBuild }) {
  const empty = gap === NO_BLOCKS;
  return (
    <div className="rbd-empty" role="status">
      <svg className="rbd-empty-art" viewBox="0 0 220 56" aria-hidden="true">
        <circle cx="16" cy="28" r="9" className="rbd-empty-end" />
        <path d="M27 28 H74" className={empty ? "rbd-empty-wire missing" : "rbd-empty-wire"} />
        <rect x="78" y="10" width="64" height="36" rx="7" className={empty ? "rbd-empty-block missing" : "rbd-empty-block"} />
        <path d="M146 28 H193" className="rbd-empty-wire missing" />
        <circle cx="204" cy="28" r="9" className="rbd-empty-end" />
      </svg>
      <h3>
        {empty
          ? `Add blocks between Input and Output to ${goal}`
          : `Connect the blocks from Input to Output to ${goal}`}
      </h3>
      <p>
        {empty ? (
          <>Right-click the canvas to add a component, then drag from Input to it and from it to Output.</>
        ) : (
          <>
            Drag between the handles — Input to the first block, the last block to Output — or select the
            blocks and press <kbd>C</kbd> to wire them in a row.
          </>
        )}
      </p>
      {onBuild && (
        <button type="button" onClick={onBuild}>
          Go to the Builder
        </button>
      )}
    </div>
  );
}
