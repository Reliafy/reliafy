// The API docs page's live tool list, read from the server's OpenAPI spec
// (GET /api/v1/openapi.json) so the page never falls behind the tools.

// Tools only some accounts have (Reliafy Maintenance) aren't listed publicly:
// the page says they exist and who gets them.
const HIDDEN = /^maintenance_/;

function firstSentence(text) {
  const s = String(text || "").trim();
  const cut = s.search(/\.(\s|$)/);
  return cut === -1 ? s : s.slice(0, cut + 1);
}

/** The tools in an OpenAPI spec from /api/v1/openapi.json, in the spec's order:
 * ``[{ name, scope, actions: [{ action, path, summary, required, optional, pro, heavy }] }]``.
 * ``action`` is null for a tool without actions (POST /api/v1/{tool}). The
 * API-only operations (tag ``rest_only``) and Maintenance tools are left out. */
export function toolsFromSpec(spec) {
  const tools = new Map();
  for (const [path, ops] of Object.entries((spec && spec.paths) || {})) {
    const op = ops && ops.post;
    if (!op || op["x-reliafy-rest-only"] || !op["x-reliafy-tool"]) continue;
    const name = op["x-reliafy-tool"];
    if (HIDDEN.test(name)) continue;
    const schema = op.requestBody?.content?.["application/json"]?.schema || {};
    const args = Object.keys(schema.properties || {});
    const required = (schema.required || []).filter((a) => args.includes(a));
    if (!tools.has(name)) tools.set(name, { name, scope: op["x-reliafy-scope"] || "write", actions: [] });
    tools.get(name).actions.push({
      action: op["x-reliafy-action"] || null,
      path,
      summary: firstSentence(op.summary || op.description),
      required,
      optional: args.filter((a) => !required.includes(a)),
      pro: Boolean(op["x-reliafy-pro-only"]),
      heavy: Boolean(op["x-reliafy-heavy"]),
    });
  }
  return [...tools.values()];
}

/** How many actions the list holds (a tool without actions counts as one). */
export function countActions(tools) {
  return tools.reduce((n, t) => n + t.actions.length, 0);
}
