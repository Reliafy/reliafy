// A .md (or .txt) file chosen for a function's working: read in the browser,
// checked, and turned into text for the box. Nothing is sent until Save.

export const BASIS_MAX = 20000; // characters, as the server has it
export const BASIS_FILE_MAX = 100 * 1024; // bytes read (20,000 characters are at most 80 KB in UTF-8)
export const BASIS_FILE_ACCEPT = ".md,.markdown,.txt,text/markdown,text/plain";

const num = (x) => x.toLocaleString("en-AU");

const tooBig = (size) => ({
  error: `That file is ${num(Math.ceil(size / 1024))} KB; a working is at most ${num(BASIS_MAX)} characters. Shorten it, or attach it as a PDF.`,
});

// The text in the bytes of a file, or { error } in plain words.
export function decodeBasisFile(bytes) {
  const b = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
  if (b.length > BASIS_FILE_MAX) return tooBig(b.length);
  if (b.includes(0)) return { error: "That isn't a text file. Choose a .md or .txt file." };
  let text;
  try {
    text = new TextDecoder("utf-8", { fatal: true }).decode(b);
  } catch {
    return { error: "This file isn't UTF-8 text. Save it as UTF-8 and try again." };
  }
  text = tidyBasis(text.replace(/^﻿/, ""));
  const n = Array.from(text).length;
  if (n > BASIS_MAX) return { error: `The file is ${num(n)} characters; a working is at most ${num(BASIS_MAX)}.` };
  return { text };
}

// Line endings as the server keeps them (LF), trailing spaces off each line, the whole trimmed.
export function tidyBasis(text) {
  return String(text || "").replace(/\r\n?/g, "\n").split("\n").map((l) => l.replace(/\s+$/, "")).join("\n").trim();
}

export async function readBasisFile(file) {
  if (file.size > BASIS_FILE_MAX) return tooBig(file.size);
  return decodeBasisFile(new Uint8Array(await file.arrayBuffer()));
}

// What the box holds after a file is added to text that's already there:
// "replace" with the file's text, or "add" below it after a blank line.
export function joinBasis(current, added, how) {
  const cur = String(current || "").trim();
  if (how === "add" && cur) return `${cur}\n\n${added}`;
  return added;
}

// Characters as the server counts them (code points of the trimmed text).
export const basisLength = (text) => Array.from(String(text || "").trim()).length;
