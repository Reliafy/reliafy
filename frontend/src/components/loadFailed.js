// Did a load fail because the item isn't there (a 404's "Not found.", "Fleet
// not found.", "Dataset not found")? The API's errors reach the pages as their
// message only, so this reads the words.
export function isNotFound(message) {
  return typeof message === "string" && /\bnot found\b/i.test(message);
}
