// Small inline icons (Instrument style: 1.7px hairline strokes).
const svg = (paths) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    {paths}
  </svg>
);

export const WaveIcon = () => svg(<path d="M3 7c3 0 3 10 6 10s3-14 6-14 3 8 6 8" />);
export const PlusIcon = () => svg(<path d="M12 5v14M5 12h14" />);
export const ListIcon = () => svg(<path d="M4 6h16M4 12h16M4 18h10" />);
export const CompareIcon = () => svg(<><path d="M4 18V8M9 18V5M14 18v-7M19 18v-4" /></>);
export const RbdIcon = () => svg(<><rect x="3" y="4" width="6" height="6" rx="1" /><rect x="15" y="4" width="6" height="6" rx="1" /><rect x="9" y="14" width="6" height="6" rx="1" /><path d="M9 7h6M6 10v4M18 10v4" /></>);
export const StrategyIcon = () => svg(<><circle cx="12" cy="12" r="8.5" /><path d="M12 12l4-2.5M12 12v4.5" /><circle cx="12" cy="12" r="1.6" fill="currentColor" stroke="none" /></>);
export const CostIcon = () => svg(<><path d="M4 19h16" /><path d="M5 6c4 9 10 9 14 1" /></>);
export const DatabaseIcon = () => svg(<><ellipse cx="12" cy="6" rx="8" ry="3" /><path d="M4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6" /></>);
export const DegradeIcon = () => svg(<><path d="M4 5c2 6 4 9 7 11s6 2.5 9 2.5" /><path d="M3 19h18" strokeDasharray="3 3" /></>);
export const UploadIcon = () => svg(<><path d="M12 16V4m0 0 4 4m-4-4-4 4" /><path d="M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3" /></>);
