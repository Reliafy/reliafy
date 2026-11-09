// A small cache of the last few things fetched, oldest dropped first: the
// Explorer keeps the last positions' pages it read (TreeDetail), so coming
// back to a row, or switching back to the Summary tab, shows them at once.
// Reading a key counts as using it, so it stays longest.

export function createRecent(max) {
  const map = new Map();
  return {
    get(key) {
      if (!map.has(key)) return undefined;
      const value = map.get(key);
      map.delete(key);
      map.set(key, value);
      return value;
    },
    has: (key) => map.has(key),
    set(key, value) {
      map.delete(key);
      map.set(key, value);
      while (map.size > max) map.delete(map.keys().next().value);
    },
    clear: () => map.clear(),
    get size() {
      return map.size;
    },
  };
}
