"""Draft a report's notes with the in-app assistant (#41, first half).

The figures come from the items' stored results (:mod:`report_facts`); the
model is asked only to word them. It answers through one tool call,
``write_report_notes``, with an introduction and one note per section, so the
reply needs no free-text parsing (a plain-text reply becomes the
introduction). Every number in the draft that isn't among the facts is
returned as ``unverified`` for the owner to check. Nothing here saves or
publishes anything: the draft goes back to the composer to be edited.
"""

from __future__ import annotations

import json

from backend.services import report_facts

TOOL_NAME = "write_report_notes"

SYSTEM_PROMPT = """\
You draft the narrative notes of a short reliability report made in Reliafy, for a reader such as a \
manager or a client who is not a reliability specialist.

Rules:
- Use only the facts given for each section. Copy every figure exactly as written there, with its unit. \
Never calculate, convert, re-round or estimate a number, and never add one that isn't given.
- If a section has no facts, describe what the item is without figures.
- Plain words: no formulas, symbols you don't explain, library names or jargon.
- Be brief and neutral. Don't recommend anything the facts don't say.

Call write_report_notes once: an introduction of 2 to 4 sentences that says what the report covers and its \
main findings, and one note per section (1 to 3 sentences each), in the order given.\
"""

TOOLS = [{
    "name": TOOL_NAME,
    "description": "Return the drafted report notes.",
    "parameters": {
        "type": "object",
        "properties": {
            "introduction": {"type": "string", "description": "2 to 4 sentences introducing the report."},
            "notes": {
                "type": "array",
                "items": {"type": "string"},
                "description": "One note per section, in the order the sections were given.",
            },
        },
        "required": ["introduction", "notes"],
    },
}]


def prompt(title: str, sections: list[dict]) -> str:
    """The user turn: the report's title and, per section, its kind, name and
    facts. ``sections`` items carry ``kind``, ``name`` and ``facts``."""
    lines = [f"Report title: {title or 'Untitled report'}", ""]
    for i, s in enumerate(sections, 1):
        lines.append(f"Section {i}: {s.get('kind') or 'Item'} “{s.get('name') or 'Untitled'}”")
        facts = s.get("facts") or ["(no figures available)"]
        lines.extend(f"- {f}" for f in facts)
        lines.append("")
    return "\n".join(lines).strip()


def messages(title: str, sections: list[dict]) -> list[dict]:
    return [{"role": "user", "content": prompt(title, sections)}]


def _from_tool_input(data, n: int) -> dict | None:
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except ValueError:
            return None
    if not isinstance(data, dict):
        return None
    notes = data.get("notes") if isinstance(data.get("notes"), list) else []
    notes = [str(x or "").strip() for x in notes][:n]
    return {"introduction": str(data.get("introduction") or "").strip(), "notes": notes + [""] * (n - len(notes))}


def parse(message, n: int) -> dict:
    """The draft from a provider-native assistant message (Anthropic content
    blocks, or OpenAI Responses output items)."""
    texts: list[str] = []
    if isinstance(message, dict):  # Anthropic
        for block in message.get("content") or []:
            if block.get("type") == "tool_use" and block.get("name") == TOOL_NAME:
                got = _from_tool_input(block.get("input"), n)
                if got:
                    return got
            elif block.get("type") == "text":
                texts.append(block.get("text") or "")
    elif isinstance(message, list):  # OpenAI Responses
        for item in message:
            if item.get("type") == "function_call" and item.get("name") == TOOL_NAME:
                got = _from_tool_input(item.get("arguments"), n)
                if got:
                    return got
            elif item.get("type") == "message":
                texts.extend(c.get("text") or "" for c in item.get("content") or [] if c.get("type") == "output_text")
    return {"introduction": "\n".join(t.strip() for t in texts if t.strip()), "notes": [""] * n}


def check(draft: dict, title: str, sections: list[dict]) -> list[str]:
    """Numbers in the draft found in none of the facts, the title or the item names."""
    sources = [title or ""]
    for s in sections:
        sources.append(s.get("name") or "")
        sources.extend(s.get("facts") or [])
    text = "\n".join([draft.get("introduction") or "", *(draft.get("notes") or [])])
    return report_facts.unverified_numbers(text, sources)
