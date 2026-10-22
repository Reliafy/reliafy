"""The ``reliafy`` command (also installed as ``reliafy-client``).

    reliafy login                                   # saves your API token
    reliafy tools                                   # every tool and action you may call
    reliafy <tool> <action> --arg value ...         # any of them (--help on each)
    reliafy models list
    reliafy fit data.csv --dist weibull
    reliafy push model.json
    reliafy upload data.csv --name Bearings
    reliafy import rbd plant.xml
    reliafy photo add IMG_01.jpg IMG_02.HEIC --to POSITION_ID
    reliafy photo link PHOTO_ID --to LOCATION_ID      # show it there too
    reliafy photo move PHOTO_ID --to POSITION_ID      # only there
    reliafy document add manual.pdf --to ITEM_ID --kind manual
    reliafy document get DOCUMENT_ID -o manual.pdf
    reliafy ingest usage fleet.csv --fleet FLEET_ID
    reliafy ingest readings readings.csv

The generic commands come from the server's OpenAPI spec, so a new tool
action is on the command line as soon as the server has it. Output is a
readable summary; ``--json`` prints the result as JSON.
"""

from __future__ import annotations

import argparse
import csv
import getpass
import glob
import hashlib
import json
import os
import sys
import time
from typing import Any

from reliafy import config as _config
from reliafy.client import Client, ReliafyError, ServerTooOld, _version

SPEC_TTL_S = 24 * 3600
BUILTINS = ("login", "logout", "whoami", "tools", "spec", "call", "push", "fit", "upload", "import", "photo",
            "document", "ingest", "help")


# ---- output --------------------------------------------------------------------

def _scalar(v) -> bool:
    return v is None or isinstance(v, (str, int, float, bool))


def _cell(v, width: int = 60) -> str:
    text = "" if v is None else (v if isinstance(v, str) else json.dumps(v, default=str))
    text = " ".join(str(text).split())
    return text if len(text) <= width else text[: width - 1] + "…"


def table(rows: list, out=None, max_cols: int = 8) -> None:
    out = out or sys.stdout
    cols: list[str] = []
    for r in rows:
        for k, v in r.items():
            if k not in cols and _scalar(v) and len(cols) < max_cols:
                cols.append(k)
    if not cols:
        out.write(json.dumps(rows, indent=2, default=str) + "\n")
        return
    cells = [[_cell(r.get(c)) for c in cols] for r in rows]
    widths = [max(len(c), *(len(row[i]) for row in cells)) for i, c in enumerate(cols)]
    out.write("  ".join(c.ljust(w) for c, w in zip(cols, widths)).rstrip() + "\n")
    out.write("  ".join("-" * w for w in widths) + "\n")
    for row in cells:
        out.write("  ".join(v.ljust(w) for v, w in zip(row, widths)).rstrip() + "\n")


def render(result: Any, as_json: bool, out=None) -> None:
    out = out or sys.stdout
    if as_json:
        out.write(json.dumps(result, indent=2, default=str) + "\n")
        return
    if isinstance(result, list):
        if result and all(isinstance(r, dict) for r in result):
            table(result, out)
        else:
            out.write(json.dumps(result, indent=2, default=str) + "\n")
        return
    if not isinstance(result, dict):
        out.write(f"{result}\n")
        return
    tables = []
    for k, v in result.items():
        if k == "data_notice":
            continue
        if isinstance(v, list) and v and all(isinstance(r, dict) for r in v):
            tables.append((k, v))
        else:
            out.write(f"{k}: {_cell(v, 200) if not isinstance(v, str) else v}\n")
    for k, rows in tables:
        out.write(f"\n{k} ({len(rows)}):\n")
        table(rows, out)


# ---- the spec, cached ----------------------------------------------------------

def _spec_cache(client: Client) -> str:
    key = hashlib.sha256(f"{client.base_url}|{client.token or ''}".encode()).hexdigest()[:16]
    return os.path.join(_config.config_dir(), f"spec-{key}.json")


def load_spec(client: Client, refresh: bool = False) -> dict:
    path = _spec_cache(client)
    if not refresh:
        try:
            if time.time() - os.path.getmtime(path) < SPEC_TTL_S:
                with open(path, encoding="utf-8") as fh:
                    return json.load(fh)
        except (OSError, ValueError):
            pass
    spec = client.spec(refresh=True)
    try:
        os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(spec, fh)
    except OSError:
        pass
    return spec


def operations(spec: dict) -> dict:
    """``{(tool, action or None): operation}`` for every tool action in a spec."""
    ops = {}
    for path, item in (spec.get("paths") or {}).items():
        op = item.get("post") or {}
        tool = op.get("x-reliafy-tool")
        if tool:
            ops[(tool, op.get("x-reliafy-action"))] = op
    return ops


def commands_from_spec(spec: dict) -> list[str]:
    """Every generic command the CLI offers for a spec: ``tool action`` (or
    ``tool`` for a tool without actions)."""
    return sorted(f"{t} {a}" if a else t for t, a in operations(spec))


# ---- generic tool commands -----------------------------------------------------

def _resolve(schema: dict, spec: dict) -> dict:
    ref = schema.get("$ref")
    if ref and ref.startswith("#/components/schemas/"):
        return spec["components"]["schemas"].get(ref.rsplit("/", 1)[1], {})
    return schema


def _types(schema: dict, spec: dict) -> set:
    schema = _resolve(schema, spec)
    out = set()
    if "type" in schema:
        t = schema["type"]
        out.update(t if isinstance(t, list) else [t])
    if "enum" in schema:
        out.update(type(v).__name__ for v in schema["enum"] if v is not None)
    if "const" in schema:
        out.add(type(schema["const"]).__name__)
    for key in ("anyOf", "oneOf", "allOf"):
        for sub in schema.get(key) or []:
            out |= _types(sub, spec)
    out.discard("null")
    out.discard("NoneType")
    return {"string" if t == "str" else t for t in out}


def parse_value(raw: str, schema: dict, spec: dict) -> Any:
    """A command-line value as the argument's type: text for a string
    argument, else JSON (numbers, true/false, lists, objects), with ``@path``
    reading a file and ``1,2,3`` a list of numbers."""
    types = _types(schema, spec)
    if raw.startswith("@") and len(raw) > 1 and os.path.exists(raw[1:]):
        with open(raw[1:], encoding="utf-8") as fh:
            text = fh.read()
        return text if types == {"string"} else json.loads(text)
    if types == {"string"}:
        return raw
    try:
        value = json.loads(raw)
    except ValueError:
        if "array" in types and "," in raw:
            parts = [p.strip() for p in raw.split(",")]
            try:
                return [json.loads(p) for p in parts]
            except ValueError:
                return parts
        if raw.lower() in ("yes", "on"):
            return True
        if raw.lower() in ("no", "off"):
            return False
        return raw
    if "array" in types and not isinstance(value, list) and value is not None:
        return [value]
    return value


def _type_label(schema: dict, spec: dict) -> str:
    s = _resolve(schema, spec)
    for key in ("anyOf", "oneOf"):
        subs = [x for x in s.get(key) or [] if x.get("type") != "null"]
        if len(subs) == 1:
            s = _resolve(subs[0], spec)
    if s.get("enum"):
        return "{" + ",".join(str(v) for v in s["enum"] if v is not None) + "}"
    types = sorted(_types(schema, spec))
    return "|".join(types) or "json"


def tool_parser(prog: str, op: dict, spec: dict) -> tuple[argparse.ArgumentParser, dict]:
    body = (((op.get("requestBody") or {}).get("content") or {}).get("application/json") or {}).get("schema") or {}
    props = body.get("properties") or {}
    required = set(body.get("required") or [])
    p = argparse.ArgumentParser(prog=prog, description=op.get("description") or op.get("summary"),
                                formatter_class=argparse.RawDescriptionHelpFormatter, allow_abbrev=False)
    _global_options(p, defaults=False)
    p.add_argument("--args", metavar="JSON", help="All the arguments as one JSON object (or @file.json).")
    p.add_argument("--no-wait", action="store_true", help="Don't wait for a long-running job; print its job_id.")
    for name, schema in props.items():
        desc = _resolve(schema, spec).get("description") or schema.get("description") or ""
        flags = sorted({f"--{name}", f"--{name.replace('_', '-')}"})
        label = _type_label(schema, spec)
        p.add_argument(*flags, dest=f"arg__{name}", metavar=label if label.startswith("{") else label.upper(),
                       action="append", nargs="?", const="true",
                       help=(("(required) " if name in required else "") + " ".join(desc.split())).replace("%", "%%"))
    return p, props


def run_tool(client: Client, spec: dict, tool: str, action: str | None, argv: list, as_json: bool) -> int:
    op = operations(spec)[(tool, action)]
    prog = f"reliafy {tool}" + (f" {action}" if action else "")
    parser, props = tool_parser(prog, op, spec)
    ns = parser.parse_args(argv)
    _apply_globals(client, ns)
    as_json = as_json or getattr(ns, "json", False)
    args: dict = {}
    if ns.args:
        text = ns.args
        if text.startswith("@"):
            with open(text[1:], encoding="utf-8") as fh:
                text = fh.read()
        args.update(json.loads(text))
    for name, schema in props.items():
        given = getattr(ns, f"arg__{name}")
        if not given:
            continue
        values = [parse_value(v, schema, spec) for v in given]
        if len(values) == 1:
            args[name] = values[0]
        else:  # repeated: one list
            args[name] = [x for v in values for x in (v if isinstance(v, list) else [v])]
    result = client.call(tool, action, wait=not ns.no_wait, **args)
    render(result, as_json)
    return 0


# ---- built-in commands ---------------------------------------------------------

def _global_options(p: argparse.ArgumentParser, defaults: bool = True) -> None:
    d = None if defaults else argparse.SUPPRESS
    p.add_argument("--base-url", default=d, help="The Reliafy server (default: saved, RELIAFY_BASE_URL, "
                                                 "or https://reliafy.com).")
    p.add_argument("--token", default=d, help="An API token (default: saved by login, or RELIAFY_TOKEN).")
    p.add_argument("--json", action="store_true", default=False if defaults else argparse.SUPPRESS,
                   help="Print the result as JSON.")


def _apply_globals(client: Client, ns) -> None:
    if getattr(ns, "base_url", None):
        client.base_url = ns.base_url.rstrip("/")
    if getattr(ns, "token", None):
        client.token = ns.token


def cmd_login(client: Client, ns) -> int:
    token = ns.token or os.environ.get("RELIAFY_TOKEN") or getpass.getpass(
        "API token (Reliafy > Settings > API access): ").strip()
    if not token:
        print("No token given.", file=sys.stderr)
        return 2
    client.token = token
    account = client.call("get", "account")
    data = _config.load()
    data.update({"token": token, "base_url": client.base_url})
    path = _config.save(data)
    who = account.get("email") or account.get("name") or "your account"
    print(f"Signed in to {client.base_url} as {who}. Token saved in {path}.")
    return 0


def cmd_logout(client: Client, ns) -> int:
    print("Signed out (saved token removed)." if _config.clear() else "No saved token.")
    return 0


def cmd_tools(client: Client, ns) -> int:
    listing = client.tools()
    load_spec(client, refresh=True)  # keep the command list in step with the server
    if ns.json:
        render(listing, True)
        return 0
    for t in listing["tools"]:
        print(f"{t['name']}  ({t['scope']})  {t.get('title') or ''}")
        for a in t["actions"]:
            if a["action"]:
                args = ", ".join([*a["required"], *(o + "?" for o in a["optional"])])
                print(f"  {a['action']}({args})")
    if listing.get("rest_only"):
        print("\nAPI/CLI only (no MCP twin):")
        for r in listing["rest_only"]:
            print(f"  {r['method']} {r['path']}: {r['summary']}")
    print("\nRun: reliafy <tool> <action> --help")
    return 0


def cmd_spec(client: Client, ns) -> int:
    render(load_spec(client, refresh=True), True)
    return 0


def cmd_whoami(client: Client, ns) -> int:
    render(client.call("get", "account"), ns.json)
    return 0


def cmd_call(client: Client, ns) -> int:
    args = json.loads(ns.args) if ns.args else {}
    render(client.call(ns.tool, ns.action, wait=not ns.no_wait, **args), ns.json)
    return 0


def cmd_push(client: Client, ns) -> int:
    with open(ns.file, encoding="utf-8") as fh:
        body = json.load(fh)
    if ns.name:
        body["name"] = ns.name
    if ns.unit:
        body["unit"] = ns.unit
    if not body.get("name"):
        body["name"] = os.path.splitext(os.path.basename(ns.file))[0]
    result = client.request("POST", "/api/import/models", body)
    if result.get("url", "").startswith("/"):
        result["url"] = client.base_url + result["url"]
    render(result, ns.json)
    return 0


def _read_lives(path: str, time_column: str | None, censor_column: str | None, count_column: str | None):
    """A CSV's failure times (and censoring flags / counts) as lists."""
    with open(path, newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        raise ReliafyError(f"{path} has no rows.")
    cols = list(rows[0])

    def numeric(c):
        try:
            [float(r[c]) for r in rows if r[c] not in ("", None)]
            return True
        except ValueError:
            return False

    time_column = time_column or next((c for c in cols if numeric(c)), None)
    if time_column not in cols:
        raise ReliafyError(f"No time column {time_column!r} in {path} (columns: {', '.join(cols)}).")
    if censor_column is None:
        censor_column = next((c for c in cols if c.lower() in ("c", "censored", "censor", "censoring")
                              and c != time_column), None)
    if censor_column is None:
        # A column like "failed" is a flag the other way round as often as not:
        # never guess its meaning.
        flag = next((c for c in cols if c != time_column and c.lower().strip() in (
            "failed", "failure", "fail", "event", "status", "flag", "suspended", "running")), None)
        if flag:
            raise ReliafyError(
                f"Column {flag!r} looks like a censoring flag. Say how to read it: --censor-column {flag} "
                f"(Reliafy reads 0 = failed, 1 = still running), adding --c-invert if 1 means failed.")
    data, censored, counts = [], [], []
    for r in rows:
        if r[time_column] in ("", None):
            continue
        data.append(float(r[time_column]))
        if censor_column:
            censored.append(int(float(r[censor_column] or 0)))
        if count_column:
            counts.append(int(float(r[count_column] or 1)))
    return data, (censored or None), (counts or None), time_column, censor_column


def cmd_fit(client: Client, ns) -> int:
    data, censored, counts, tcol, ccol = _read_lives(ns.file, ns.time_column, ns.censor_column, ns.count_column)
    if not ns.json:
        print(f"Fitting {len(data)} rows: times from {tcol!r}"
              + (f", censoring from {ccol!r} (0 = failed, 1 = still running" + (", inverted" if ns.c_invert else "")
                 + ")" if ccol else ", all failures") + ".", file=sys.stderr)
    result = client.fit(data, distribution=ns.dist, censored=censored, counts=counts,
                        c_invert=True if ns.c_invert else None, unit=ns.unit, save_as=ns.save)
    render(result, ns.json)
    return 0


def cmd_upload(client: Client, ns) -> int:
    render(client.upload_dataset(ns.file, name=ns.name, sheet=ns.sheet), ns.json)
    return 0


def cmd_import(client: Client, ns) -> int:
    if ns.what == "rbd":
        result = client.import_rbd(ns.file, name=ns.name, format=ns.format)
    else:
        result = client.import_excel(ns.file, target=ns.target, sheet=ns.sheet, name=ns.name)
    render(result, ns.json)
    return 0


def _expand(patterns: list[str]) -> list[str]:
    files: list[str] = []
    for pat in patterns:
        hits = sorted(glob.glob(os.path.expanduser(pat))) if any(ch in pat for ch in "*?[") else [pat]
        files.extend(hits or [pat])
    return files


def cmd_photo(client: Client, ns) -> int:
    if ns.verb != "add":
        return _photo_links(client, ns)
    if not ns.to:
        raise ReliafyError("photo add needs --to TARGET_ID.")
    files = _expand(ns.files)
    failed = 0
    results = []
    for path in files:
        try:
            out = client.add_photo(path, ns.to, ns.caption)
            photo = out.get("photo") or {}
            results.append({"file": path, "ok": True, "photo_id": photo.get("id"), "detail": ""})
        except (ReliafyError, OSError) as exc:
            if isinstance(exc, ServerTooOld):
                raise
            failed += 1
            results.append({"file": path, "ok": False, "photo_id": None,
                            "detail": str(getattr(exc, "detail", None) or exc)})
    if ns.json:
        render(results, True)
    else:
        table(results)
        print(f"\n{len(files) - failed} of {len(files)} added.")
    return 1 if failed else 0


def _photo_links(client: Client, ns) -> int:
    """photo link / move / unlink: maintenance_attachments link_photo,
    move_photo and unlink_photo for each photo id."""
    if ns.verb == "unlink":
        if not ns.from_id:
            raise ReliafyError("photo unlink needs --from TARGET_ID.")
    elif not ns.to:
        raise ReliafyError(f"photo {ns.verb} needs --to TARGET_ID.")
    results = []
    for photo_id in ns.files:
        if ns.verb == "unlink":
            out = client.call("maintenance_attachments", "unlink_photo", photo_id=photo_id, target_id=ns.from_id)
        else:
            out = client.call("maintenance_attachments", f"{ns.verb}_photo", photo_id=photo_id, target_id=ns.to,
                              from_id=ns.from_id if ns.verb == "move" else None)
        results.append({"photo_id": photo_id, "on": ", ".join(t.get("name") or t["id"] for t in out.get("on", []))})
    render(results, ns.json)
    return 0


def cmd_document(client: Client, ns) -> int:
    """document add FILE.pdf … (kept on an item, a position or a class) and
    document get ID (saved as a file)."""
    if ns.verb == "get":
        if len(ns.files) != 1:
            raise ReliafyError("document get takes one document id.")
        path = client.download_document(ns.files[0], ns.output)
        render({"document_id": ns.files[0], "saved_to": path}, ns.json)
        return 0
    if bool(ns.to) == bool(ns.position_class):
        raise ReliafyError("document add needs --to ITEM_OR_POSITION_ID or --class POSITION_CLASS (one of them).")
    if ns.output:
        raise ReliafyError("-o is for document get.")
    files = _expand(ns.files)
    failed = 0
    results = []
    for path in files:
        try:
            doc = client.add_document(path, ns.to, position_class=ns.position_class,
                                      title=ns.title if len(files) == 1 else None, kind=ns.kind)
            results.append({"file": path, "ok": True, "document_id": doc.get("id"), "detail": ""})
        except (ReliafyError, OSError) as exc:
            if isinstance(exc, ServerTooOld):
                raise
            failed += 1
            results.append({"file": path, "ok": False, "document_id": None,
                            "detail": str(getattr(exc, "detail", None) or exc)})
    if ns.json:
        render(results, True)
    else:
        table(results)
        print(f"\n{len(files) - failed} of {len(files)} added.")
    return 1 if failed else 0


def cmd_ingest(client: Client, ns) -> int:
    if ns.what == "usage":
        if not ns.fleet:
            raise ReliafyError("ingest usage needs --fleet FLEET_ID.")
        result = client.push_usage(ns.fleet, file=ns.file)
    elif ns.what == "readings":
        result = client.push_readings(file=ns.file)
    elif ns.what == "measurements":
        if not ns.fleet:
            raise ReliafyError("ingest measurements needs --fleet FLEET_ID.")
        result = client.push_measurements(ns.fleet, file=ns.file)
    else:
        if not ns.dataset:
            raise ReliafyError("ingest lives needs --dataset DATASET_ID.")
        result = client.push_lives(ns.dataset, file=ns.file, refit=not ns.no_refit)
    render(result, ns.json)
    return 0


def builtin_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="reliafy", description="Reliafy from the command line: every tool action, files, photos, documents "
                                    "and ingest.",
        epilog="Any tool action: reliafy <tool> <action> --arg value … (reliafy tools lists them; add --help).",
        formatter_class=argparse.RawDescriptionHelpFormatter, allow_abbrev=False)
    p.add_argument("--version", action="version", version=f"reliafy-client {_version()}")
    _global_options(p)
    sub = p.add_subparsers(dest="command", metavar="command")

    def add(name, fn, help_):
        sp = sub.add_parser(name, help=help_, description=help_, allow_abbrev=False)
        _global_options(sp, defaults=False)
        sp.set_defaults(fn=fn)
        return sp

    sp = add("login", cmd_login, "Save an API token (and server) for later commands.")
    add("logout", cmd_logout, "Forget the saved token.")
    add("whoami", cmd_whoami, "Your account and plan.")
    sp = add("tools", cmd_tools, "List every tool and action you may call.")
    add("spec", cmd_spec, "Print the server's OpenAPI spec.")
    sp = add("call", cmd_call, "Call a tool action with JSON arguments.")
    sp.add_argument("tool")
    sp.add_argument("action", nargs="?")
    sp.add_argument("--args", help="The arguments as a JSON object.")
    sp.add_argument("--no-wait", action="store_true")
    sp = add("push", cmd_push, "Push a model from a JSON file: {distribution, params | data, name?, unit?}.")
    sp.add_argument("file")
    sp.add_argument("--name")
    sp.add_argument("--unit")
    sp = add("fit", cmd_fit, "Fit a life distribution to a CSV of times (0 = failed, 1 = still running).")
    sp.add_argument("file")
    sp.add_argument("--dist", help="weibull, lognormal, exponential, … (default: the best fit).")
    sp.add_argument("--time-column")
    sp.add_argument("--censor-column")
    sp.add_argument("--count-column")
    sp.add_argument("--c-invert", action="store_true", help="The censor column uses 1 = failed.")
    sp.add_argument("--unit")
    sp.add_argument("--save", metavar="NAME", help="Save the model under this name.")
    sp = add("upload", cmd_upload, "Upload a CSV or .xlsx file as a dataset.")
    sp.add_argument("file")
    sp.add_argument("--name")
    sp.add_argument("--sheet")
    sp = add("import", cmd_import, "Import a diagram file (rbd) or an .xlsx workbook (excel).")
    sp.add_argument("what", choices=["rbd", "excel"])
    sp.add_argument("file")
    sp.add_argument("--name")
    sp.add_argument("--format", help="rbd: blocksim, openpsa, galileo, excel or repyability (default: detected).")
    sp.add_argument("--target", help="excel: dataset, rcm or rbd.")
    sp.add_argument("--sheet")
    sp = add("photo", cmd_photo, "Add photos to a maintenance position, item, location or work order; link a "
                                 "photo to another one too, move it, or unlink it.")
    sp.add_argument("verb", choices=["add", "link", "move", "unlink"])
    sp.add_argument("files", nargs="+", help="add: image files (globs work; JPEG, PNG, WebP, HEIC). "
                                             "link, move, unlink: photo ids.")
    sp.add_argument("--to", help="The position, item, location or work order id.")
    sp.add_argument("--from", dest="from_id", help="unlink: where to take it off. move: only off this one "
                                                   "(default: off everywhere else).")
    sp.add_argument("--caption")
    sp = add("document", cmd_document, "Keep PDFs on a maintenance item, position or position class, or save "
                                       "one to a file.")
    sp.add_argument("verb", choices=["add", "get"])
    sp.add_argument("files", nargs="+", help="add: PDF files (globs work; at most 20 MB each). get: a document id.")
    sp.add_argument("--to", help="add: the item or position id.")
    sp.add_argument("--class", dest="position_class", help="add: a position class (instead of --to).")
    sp.add_argument("--title", help="add: the title (one file; default: the file name).")
    sp.add_argument("--kind", choices=["manual", "datasheet", "invoice", "drawing", "certificate", "other"])
    sp.add_argument("-o", "--output", help="get: where to save it (default: its own file name).")
    sp = add("ingest", cmd_ingest, "Push usage, readings, measurements or life data from a CSV file.")
    sp.add_argument("what", choices=["usage", "readings", "measurements", "lives"])
    sp.add_argument("file")
    sp.add_argument("--fleet")
    sp.add_argument("--dataset")
    sp.add_argument("--no-refit", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    client = Client()
    try:
        # Global options may come first: take them off to find the command.
        pre = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
        _global_options(pre)
        known, rest = pre.parse_known_args(argv)
        _apply_globals(client, known)
        command = rest[0] if rest else None
        if command == "models" and len(rest) > 1 and rest[1] == "list":
            ns = argparse.Namespace(json=known.json or "--json" in rest[2:])
            render(client.list("models"), ns.json)
            return 0
        if command and not command.startswith("-") and command not in BUILTINS:
            spec = load_spec(client)
            ops = operations(spec)
            tools = {t for t, _ in ops}
            if command not in tools:
                spec = load_spec(client, refresh=True)
                ops = operations(spec)
                tools = {t for t, _ in ops}
            if command not in tools:
                print(f"reliafy: no command or tool '{command}'. Run reliafy tools to list them.", file=sys.stderr)
                return 2
            action = rest[1] if len(rest) > 1 and not rest[1].startswith("-") else None
            if (command, action) not in ops:
                actions = sorted(a for t, a in ops if t == command and a)
                if not actions and (command, None) in ops:
                    return run_tool(client, spec, command, None, rest[1:], known.json)
                print(f"usage: reliafy {command} {{{','.join(actions)}}} [--arg value …]\n"
                      f"reliafy {command}: choose an action (add --help after one for its arguments).",
                      file=sys.stderr)
                return 2
            return run_tool(client, spec, command, action, rest[2:] if action else rest[1:], known.json)
        parser = builtin_parser()
        ns = parser.parse_args(argv)
        if not getattr(ns, "fn", None):
            parser.print_help()
            return 0
        _apply_globals(client, ns)
        return ns.fn(client, ns)
    except ReliafyError as exc:
        print(f"reliafy: {exc}", file=sys.stderr)
        return 1
    except (OSError, ValueError) as exc:
        print(f"reliafy: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:  # pragma: no cover
        return 130


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
