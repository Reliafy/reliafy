// Client-side list filter: an input styled like the table toolbar search.
// Lists are small and fully loaded, so filtering in the browser is exact
// and instant — no backend round-trip.
const SearchIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="11" cy="11" r="7" />
    <path d="m20 20-3.5-3.5" />
  </svg>
);

export default function ListSearch({ value, onChange, placeholder = "Search…" }) {
  return (
    <div className="search live">
      <SearchIcon />
      <input
        type="search"
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        aria-label={placeholder}
      />
    </div>
  );
}

// The match helper the list views share: case-insensitive substring over the
// fields that identify a row.
export function matches(query, ...fields) {
  const q = (query || "").trim().toLowerCase();
  if (!q) return true;
  return fields.some((f) => String(f || "").toLowerCase().includes(q));
}
