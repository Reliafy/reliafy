// The Guides drawer's filter box (components/HelpButton.jsx): the groups from
// guides.js `guidesByCategory` narrowed to the guides that match what was
// typed. A guide matches when every word typed is somewhere in its title or
// its one-line task, whatever the case or the order ("csv fit" finds "Fit
// your first non-repairable model from a CSV"). Groups left with no guide
// drop out; nothing typed keeps every group as it was.
export function filterGuideGroups(groups = [], query = "") {
  const words = String(query || "").toLowerCase().split(/\s+/).filter(Boolean);
  if (!words.length) return groups;
  return groups
    .map((group) => ({
      ...group,
      items: group.items.filter((g) => {
        const text = `${g.title || ""} ${g.task || ""}`.toLowerCase();
        return words.every((w) => text.includes(w));
      }),
    }))
    .filter((group) => group.items.length > 0);
}
