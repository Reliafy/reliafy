// A load's error as text, whether the page kept the Error or only its message.
function messageOf(error) {
  if (!error) return "";
  if (typeof error === "string") return error;
  return typeof error.message === "string" ? error.message : String(error);
}

// Did a load fail because the item isn't there (a 404's "Not found.", "Fleet
// not found.", "Dataset not found")? The API's errors reach the pages as their
// message only (or as the Error, with its status), so this reads the words.
export function isNotFound(error) {
  if (error && typeof error === "object" && error.status === 404) return true;
  const message = messageOf(error);
  return typeof message === "string" && /\bnot found\b/i.test(message);
}

// The browser's words for "the request never reached the server" (Chrome,
// Safari, Firefox).
const NETWORK = /^(failed to fetch|load failed|network ?error\b.*|networkerror\b.*|the network connection was lost\.?|the internet connection appears to be offline\.?)$/i;

// Server or framework text that means nothing to a user: HTTP status phrases,
// our client's "Request failed (500)" fallback, a validation list that became
// "[object Object]", or anything that reads like a stack trace.
const RAW = /^(internal server error|bad gateway|service unavailable|gateway time-?out|request failed \(\d+\)|\[object object\](,\[object object\])*|undefined|null)\.?$|\b(traceback|exception|errno|stack trace|typeerror|referenceerror|syntaxerror)\b/i;

// What a user reads when a load failed: the server's own sentence when it was
// written for people (a 4xx's "Pro feature" or "Not a member of this
// workspace"), and plain words in place of a raw server or browser message.
// Never shows "Internal Server Error" or a status code on its own.
export function plainLoadError(error) {
  const message = messageOf(error).trim();
  const status = error && typeof error === "object" ? error.status : undefined;
  if (NETWORK.test(message)) return "Reliafy couldn't be reached. Check your connection, then try again.";
  if (!message || (status && status >= 500) || RAW.test(message) || message.length > 300) {
    return "Something went wrong on our side. Your data is safe; try again in a moment.";
  }
  return message;
}
