"""MCP tools that do several things, one chosen by an argument (``action``, or
``kind`` for a read): the per-action tables that both check every call and
write the tool's description. Shared by the core tools (backend/mcp_server.py)
and Reliafy Maintenance's (backend/maintenance/mcp_tools.py).

A table maps each value of the choosing argument to (required arguments,
optional arguments, what it does). "Required" means not null; anything else a
call gives must be one of the optional ones. Every other argument of such a
tool defaults to null, so a call carries only what its action takes."""

from typing import Annotated, Any, Literal

from pydantic import Field

Table = dict[str, tuple[str, str, str]]


def check(selector: str, value: str, table: Table, args: dict[str, Any]) -> dict[str, Any]:
    """Hold one call to its action's (or kind's) arguments: every required one
    given, nothing it doesn't take. Returns the ones given (not null)."""
    required, optional, _ = table[value]
    required, optional = required.split(), optional.split()
    given = {k: v for k, v in args.items() if v is not None}
    takes = ", ".join([*required, *(o + "?" for o in optional)]) or "nothing else"
    missing = [a for a in required if a not in given]
    if missing:
        raise ValueError(f"{selector} '{value}' needs {', '.join(missing)} (it takes {takes}).")
    extra = [a for a in given if a not in required and a not in optional]
    if extra:
        raise ValueError(f"{selector} '{value}' doesn't take {', '.join(extra)} (it takes {takes}).")
    return given


def describe(intro: str, selector: str, table: Table, defaults: dict[str, dict[str, str]] | None = None) -> str:
    """A tool's description: what it's for, then every action with what it
    takes (``defaults``: an optional argument's default, by action, shown as
    ``name?=default``)."""
    lines = [" ".join(intro.split()), "",
             f"{selector} values, each with its arguments (? = optional) and when to use it:"]
    for value, (required, optional, text) in table.items():
        shown = (defaults or {}).get(value) or {}
        args = ", ".join([*required.split(),
                          *(o + "?" + (f"={shown[o]}" if o in shown else "") for o in optional.split())])
        lines.append(f"- {value}({args}): {' '.join(text.split())}")
    return "\n".join(lines)


def choice(table: Table) -> Any:
    """The choosing argument's type: one of the table's values."""
    return Annotated[Literal[tuple(table)], Field(  # type: ignore[valid-type]
        description="One of the values listed in the description, each with the arguments it takes.")]
