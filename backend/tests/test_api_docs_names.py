"""The hand-written API docs name only tools and actions that exist: every
``rf.call("tool", "action"``, ``/api/v1/<tool>/<action>`` and ``reliafy
<tool> <action>`` in them is checked against the MCP registry (and the fixed
/api/v1 routes), so a renamed tool can't leave a stale example behind."""

import ast
import os
import re

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
DOCS = ["python/README.md", "docs/api.md", "docs/library.md", "frontend/src/content/guides/use-the-api-and-cli.md"]

CALL = re.compile(r"""\.call\(\s*["']([\w.]+)["']\s*(?:,\s*["']([\w.]+)["'])?""")
REST = re.compile(r"/api/v1((?:/[\w.\-{}]+)+)")
CLI = re.compile(r"(?:^|`|\$ )reliafy ([a-z_]+)(?: ([a-z_][\w.]*))?", re.M)


def _builtins() -> set:
    """The CLI's own commands (python/reliafy/cli.py BUILTINS), read without importing it."""
    tree = ast.parse(open(os.path.join(ROOT, "python/reliafy/cli.py"), encoding="utf-8").read())
    for node in tree.body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "BUILTINS":
            return set(ast.literal_eval(node.value))
    raise AssertionError("BUILTINS not found in cli.py")


@pytest.fixture()
def registry(monkeypatch):
    from backend import config, mcp_server
    from backend.maintenance import mcp_tools
    from backend.routers import api_tools, field_reports, maintenance_sync, public_api, support

    monkeypatch.setattr(config, "MAINTENANCE_ENABLED", True)
    mcp_tools.register()
    actions = {(tool, a) for tool, (_, table) in mcp_server._all_tables().items() for a in table}
    plain = {t.name for t in mcp_server.mcp._tool_manager.list_tools()} - {t for t, _ in actions}
    # Fixed /api/v1 routes outside the tool registry: the offline sync (#802,
    # #804) and field reports (v1_router) are mounted before the generic ones.
    routers = [m.router for m in (public_api, support, api_tools, maintenance_sync)] + [field_reports.v1_router]
    fixed = [re.compile("^" + re.sub(r"\{[^/]+\}", "[^/]+", r.path) + "$")
             for rt in routers for r in rt.routes
             if r.path.startswith("/api/v1") and not r.path.startswith("/api/v1/{")]
    yield actions, plain, fixed
    mcp_tools.unregister()


def _known(tool: str, action, registry) -> bool:
    actions, plain, _ = registry
    return (tool, action) in actions if action else tool in plain


@pytest.mark.parametrize("doc", DOCS)
def test_docs_name_only_real_tools(doc, registry):
    text = open(os.path.join(ROOT, doc), encoding="utf-8").read()
    builtins = _builtins() | {"models"}  # `reliafy models list` is a built-in shortcut
    bad = []
    for m in CALL.finditer(text):
        if not _known(m.group(1), m.group(2), registry):
            bad.append(f"rf.call {m.group(1)} {m.group(2) or ''}")
    for m in REST.finditer(text):
        path = "/api/v1" + m.group(1).rstrip(".")
        parts = m.group(1).strip("/").split("/")
        if any("{" in p for p in parts) or any(rx.match(path) for rx in registry[2]):
            continue
        if len(parts) > 2 or not _known(parts[0], parts[1] if len(parts) == 2 else None, registry):
            bad.append(path)
    for m in CLI.finditer(text):
        if m.group(1) not in builtins and not _known(m.group(1), m.group(2), registry):
            bad.append(f"reliafy {m.group(1)} {m.group(2) or ''}")
    assert not bad, f"{doc} names tools or actions that don't exist: {sorted(set(bad))}"
