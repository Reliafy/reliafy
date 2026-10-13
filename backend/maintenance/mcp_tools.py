"""MCP tools for Reliafy Maintenance.

Registered on the MCP server only when ``MAINTENANCE_ENABLED`` (local only for
now), so production's tool list is unchanged. They act on the caller's
personal workspace, like the other MCP tools.
"""


import dataclasses
from typing import Annotated, Any, Literal

from pydantic import Field

TOOL_NAMES: list[str] = []
_ORIGINAL: dict = {}
# Tools that fit a life model on the server: Pro only, like the MCP server's
# other fitting tools (added to its plan gating when registered).
PRO_FIT_TOOLS = ("fit_class_model",)
# Tools that can take a while: they share the MCP server's heavy-call slots.
HEAVY_TOOLS = ("fit_class_model", "import_history", "plan_economics", "generate_rbd")


def register() -> None:
    """Add the maintenance tools to the MCP server (idempotent)."""
    if TOOL_NAMES:
        return
    from mcp.server.mcpserver import Context
    from mcp.server.mcpserver.exceptions import ToolError

    from backend.maintenance.access import allowed
    from backend.maintenance.service import Invalid, Maintenance, NotFound, summary
    from backend import mcp_server
    from backend.mcp_server import _READ, _WRITE, _caller, _db, _reader, _tool, mcp
    from backend.routers.maintenance import get_store
    from backend.schema import RcmStudy
    from backend.services import access as access_service

    def m_for(ctx: Context) -> Maintenance:
        user = _caller(ctx)
        if not allowed(user):
            raise ToolError("Reliafy Maintenance isn't available on your account yet.")
        return Maintenance(get_store(), user["uid"], user["uid"])

    def run(fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except NotFound:
            raise ToolError("Not found in your maintenance workspace.") from None
        except Invalid as err:
            raise ToolError(str(err)) from None

    def study_for(ctx: Context, study_id: str) -> RcmStudy:
        user = _caller(ctx)
        study, _ = access_service.fetch_readable(_db(), "rcm_studies", RcmStudy, study_id, _reader(user))
        if study is None:
            raise ToolError("RCM study not found.")
        return study

    def tool(name, annotations, title):
        TOOL_NAMES.append(name)
        return _tool(name, annotations, title)

    DateText = Annotated[str | None, Field(description="A date like 2026-10-13. Default: today.")]
    Precision = Literal["exact", "month", "year", "estimated"]
    RoughDate = Annotated[str | None, Field(description=(
        "A date like 2026-10-13, or 2022-03 / 2022 when only the month or year is known "
        "(the precision follows). Default: today."))]
    ItemDate = Annotated[dict[str, str] | None, Field(description=(
        "{date: '2022' | '2022-03' | '2022-03-15', precision?: exact|month|year|estimated (from the "
        "date's form if left out; estimated = a guess, e.g. 'about 6 months ago'), source?: where it "
        "came from, e.g. 'receipt', 'serial date code', \"owner's estimate\"}. Never invent a day: give "
        "'2022' with precision year rather than 2022-07-01."))]
    ReplacementCost = Annotated[dict[str, Any] | None, Field(description=(
        "{amount, currency?: 3-letter code (AUD), source?: e.g. 'supplier quote', as_of?: date of the "
        "price (default today)}."))]

    # ---- reading ---------------------------------------------------------------------

    @tool("maintenance_overview", _READ, "Maintenance overview")
    def maintenance_overview(ctx: Context) -> dict[str, Any]:
        """The maintenance workspace at a glance: counts, the tree of positions (the
        functional hierarchy, each with what's fitted, its task count, next due date
        and open work orders), tasks due in the next 30 days, open work orders, and
        critical_spares: critical spares below the minimum their position keeps on hand.
        Start here; use the ids with the other maintenance tools.

        The model: a position is a functional location (SAP's FLOC): the slot, by what it
        does (Electrical > MCC-3 > Feeder 12; House > Pool > Pump). A location is a physical
        place (Site > Area X > Substation 2; House > Laundry; Store A). The two are separate
        trees that cut across each other, so build each once: never copy the functional tree
        into locations or the physical tree into positions. Link them by giving a position
        a location_id (create_position / update_position); positions inside it inherit it
        unless one says otherwise. An item (a serial-numbered thing) is fitted to a position
        and is then where its position is: it needs no placement. place_item is only for
        items that aren't fitted (a spare in a store, one away at a repairer)."""
        m = m_for(ctx)
        return run(lambda: {"summary": summary(m), "tree": m.tree(), "due": m.due_tasks(30),
                            "open_work_orders": m.work_orders("open"), "critical_spares": m.critical_spares_short()})

    @tool("get_position", _READ, "Read a maintenance position")
    def get_position(position_id: str, ctx: Context) -> dict[str, Any]:
        """One position: its path, the positions inside it, the item fitted now, every
        past fitment (with from_precision / to_precision when a date is known only roughly),
        its failure modes (from RCM, added by hand, or ad hoc: typed in at a failure),
        class_failure_modes (modes seen at other positions of its class, to offer when it
        fails), its tasks with last-done and next-due dates and the trade each needs, its work
        orders, its document links, its parts_list (catalogue parts it uses: the replacement
        part first, with stock on hand, what to use instead if superseded, interchangeable
        alternatives, critical-spare minimums and compatibility notes) and its life data (one
        row per item fitted: days in service, c = 0 failed or 1 censored, 2 failed within
        xl..xr days). location: where it physically is (display: 'Site › Area X › Substation 2'),
        with inherited true and inherited_from when it comes from a position above it (or from
        the item it's inside); null when no location is set on it or above it."""
        return run(m_for(ctx).position, position_id)

    @tool("list_work_orders", _READ, "List work orders")
    def list_work_orders(ctx: Context, status: Literal["open", "planned", "in_progress", "waiting", "closed",
                                                       "cancelled"] | None = None,
                         location_id: str | None = None) -> dict[str, Any]:
        """Work orders, newest first, each with its position and that position's location. status
        'open' gives every one not yet done (open, planned, in progress, waiting); or one status
        exactly. location_id: only work in that area (positions located there or in a location
        inside it, set or inherited), e.g. everything open in Substation 2."""
        return {"work_orders": run(m_for(ctx).work_orders, status, location_id)}

    @tool("get_work_order", _READ, "Read a work order")
    def get_work_order(work_order_id: str, ctx: Context) -> dict[str, Any]:
        """A work order: its position, task, status and dates, the trade it needs, its notes (with
        note_history: every earlier version), the actions and close_notes recorded when it
        closed, the cancel_reason if cancelled, and (for an open one) the item fitted now and the
        position's failure modes, which close_work_order's actions can name. suggested_parts is the
        position's parts list (replacement part first, with stock by location): pick from it for a
        replacement or a part used rather than searching the catalogue. warranty is set when
        the item fitted when it was raised was under warranty then: check the coverage before
        paying for the work."""
        return run(m_for(ctx).work_order, work_order_id)

    @tool("list_maintenance_items", _READ, "List items")
    def list_maintenance_items(ctx: Context) -> dict[str, Any]:
        """Every physical item (serial-numbered thing), with the position it's fitted to and
        where it is: location (how: fitted = its position's location, or placed = a placement
        while not fitted), or last_at (taken out of a position and not placed since: where
        that position is)."""
        return {"items": run(m_for(ctx).items)}

    @tool("list_locations", _READ, "List locations")
    def list_locations(ctx: Context) -> dict[str, Any]:
        """Physical locations (sites, areas, buildings, rooms, stores) as a tree, each with
        positions (located there, set or inherited) and items (placed there, not fitted), and
        all_positions / all_items counting the locations inside it too."""
        return {"tree": run(m_for(ctx).location_tree)}

    # ---- building the plant ------------------------------------------------------------

    @tool("create_position", _WRITE, "Create a position")
    def create_position(name: str, ctx: Context, parent_id: str | None = None, tag: str = "",
                        position_class: str = "", description: str = "",
                        location_id: str | None = None) -> dict[str, Any]:
        """A position: a functional location (SAP's FLOC), the job something does in the plant,
        such as 'Hot water system', 'MCC-3' or 'Pump A'. Items are fitted to positions. Put it
        inside another position with parent_id, or inside an item (parent_id = an item id) for
        a position that travels with that item, like an engine's turbo. position_class groups
        like positions for comparison and pooled life data (e.g. 'Centrifugal pump').
        location_id: where it physically is (a location from create_location / list_locations);
        leave it out to inherit its parent's, and set it only where a child is somewhere else
        (Feeder 12 is under MCC-3 but out in the conveyor gallery)."""
        m = m_for(ctx)
        return run(lambda: m.position(m.create_position(name, tag, parent_id, position_class, description,
                                                        location_id)["id"]))

    @tool("update_position", _WRITE, "Update a position")
    def update_position(position_id: str, ctx: Context, name: str | None = None, tag: str | None = None,
                        position_class: str | None = None, description: str | None = None,
                        parent_id: str | None = None, move_to_top_level: bool = False,
                        location_id: str | None = None, clear_location: bool = False) -> dict[str, Any]:
        """Rename a position, change its tag, class or description, move it inside another
        position (parent_id) or to the top level (move_to_top_level), or say where it physically
        is: location_id (positions inside it that have none of their own follow), or
        clear_location to inherit its parent's again. The item fitted to it is where it is."""
        m = m_for(ctx)
        changes = {k: v for k, v in (("name", name), ("tag", tag), ("position_class", position_class),
                                     ("description", description)) if v is not None}
        if parent_id or move_to_top_level:
            changes["parent_id"] = None if move_to_top_level else parent_id
        if location_id or clear_location:
            changes["location_id"] = None if clear_location else location_id
        return run(lambda: (m.update_position(position_id, **changes), m.position(position_id))[1])

    @tool("copy_position", _WRITE, "Copy a position")
    def copy_position(position_id: str, name: str, ctx: Context, parent_id: str | None = None) -> dict[str, Any]:
        """Copy a position and everything inside it (the positions, their failure modes,
        tasks and parts lists, and any location set on them; not items, stock or work orders)
        under a new name, optionally inside another position. Call it repeatedly to build many
        like structures; then update_position the copy's location_id if it's somewhere else."""
        return run(m_for(ctx).copy_position, position_id, name, parent_id)

    @tool("position_from_rcm", _WRITE, "Create a position from an RCM study")
    def position_from_rcm(study_id: str, ctx: Context, parent_id: str | None = None) -> dict[str, Any]:
        """Create a position named for an RCM study's system, with the study's failure
        modes and a scheduled task for every decision that has an interval. Find study
        ids with list_rcm_studies; create_rcm_study makes one from JSON."""
        return run(m_for(ctx).position_from_rcm, study_for(ctx, study_id), parent_id)

    @tool("apply_rcm_to_position", _WRITE, "Apply an RCM study to a position")
    def apply_rcm_to_position(position_id: str, study_id: str, ctx: Context) -> dict[str, Any]:
        """Bring an RCM study's failure modes and scheduled tasks onto an existing
        position. Applying it again adds what's new and updates changed tasks."""
        m = m_for(ctx)
        return run(lambda: {**m.apply_rcm(position_id, study_for(ctx, study_id)), "position": m.position(position_id)})

    @tool("fit_item", _WRITE, "Fit an item to a position")
    def fit_item(position_id: str, ctx: Context, item_id: str | None = None, item_name: str | None = None,
                 serial: str = "", part_number: str = "", manufacturer: str = "", on: RoughDate = None,
                 from_precision: Precision | None = None) -> dict[str, Any]:
        """Fit an item to an empty position: an existing item (item_id), or a new one
        (item_name, with optional serial, part number and manufacturer). 'on' is the
        date it went in; if it's known only roughly, say so (on '2022', or a day with
        from_precision 'estimated'): life data then treats its life as a range. A new
        item renews the position's tasks. To replace an item, close a work order with a
        replace action instead."""
        new_item = {"name": item_name, "serial": serial, "part_number": part_number,
                    "manufacturer": manufacturer} if item_name else None
        return run(m_for(ctx).fit, position_id, item_id, new_item, on, from_precision)

    @tool("remove_item", _WRITE, "Remove a fitted item")
    def remove_item(position_id: str, ctx: Context, on: RoughDate = None,
                    reason: Literal["planned", "failure", "other"] | None = None,
                    failure_mode_id: str | None = None, failure_mode_text: str | None = None,
                    to_precision: Precision | None = None) -> dict[str, Any]:
        """Take the fitted item out of a position with no work order (a correction, or
        moving it). Work done on it belongs on a work order (close_work_order). If it failed,
        name how: failure_mode_id (a mode in get_position), or failure_mode_text in words
        (the position's mode of that name is reused, else an ad-hoc one is added). A failure
        mode with no reason means it failed; with no mode, a planned removal. Recording a
        failure as planned corrupts the life data, so name a mode whenever it failed.
        to_precision: how well the date is known."""
        return run(m_for(ctx).remove, position_id, on, reason, failure_mode_id, failure_mode_text, to_precision)

    @tool("add_past_fitment", _WRITE, "Add a past fitment to a position's history")
    def add_past_fitment(position_id: str, start: RoughDate, end: RoughDate, ctx: Context,
                         reason: Literal["planned", "failure", "other"] | None = None,
                         item_id: str | None = None, item_name: str | None = None, serial: str = "",
                         part_number: str = "", manufacturer: str = "", model: str = "",
                         failure_mode_id: str | None = None, failure_mode_text: str | None = None,
                         from_precision: Literal["exact", "month", "year", "estimated"] | None = None,
                         to_precision: Literal["exact", "month", "year", "estimated"] | None = None,
                         note: str = "") -> dict[str, Any]:
        """Put an earlier item into a position's history (migrating records from another
        system) without remove / refit / work order steps: it went in on start and came out
        on end (dates like 2019-03-01). The item: an existing one (item_id) or a new one
        (item_name, serial...). reason: failure (name the mode by failure_mode_id or in words
        with failure_mode_text), planned, or other; with a mode and no reason it's a failure.
        It may sit before the current fitment but must not overlap any other fitment at the
        position (or the item's own elsewhere); the current item and tasks are untouched.
        from_precision / to_precision: how well each date is known (exact, month, year,
        estimated), when it was e.g. 'sometime in 2019'. Returns the position."""
        new_item = {"name": item_name, "serial": serial, "part_number": part_number,
                    "manufacturer": manufacturer, "model": model} if item_name else None
        return run(m_for(ctx).add_past_fitment, position_id, start, end, reason, item_id, new_item,
                   failure_mode_id, failure_mode_text, from_precision, to_precision, note)

    @tool("add_failure_mode", _WRITE, "Add a failure mode to a position")
    def add_failure_mode(position_id: str, text: str, ctx: Context, function: str = "", failure: str = "",
                         consequence: str = "") -> dict[str, Any]:
        """A failure mode on a position without an RCM study: how it fails (text: 'Bearing
        worn', 'Seal leaking'), optionally the function it serves, the functional failure
        ('No flow') and the consequence. Failures (remove_item, close_work_order,
        add_past_fitment) and tasks (create_task, update_task) can then name it by id."""
        return run(m_for(ctx).add_failure_mode, position_id, text, function, failure, consequence)

    @tool("update_failure_mode", _WRITE, "Edit a failure mode")
    def update_failure_mode(failure_mode_id: str, ctx: Context, text: str | None = None,
                            function: str | None = None, failure: str | None = None,
                            consequence: str | None = None) -> dict[str, Any]:
        """Edit a failure mode added by hand or typed in at a failure (ad hoc). Editing an
        ad-hoc mode confirms it as a formal one. Modes from an RCM study change in the study."""
        return run(m_for(ctx).update_failure_mode, failure_mode_id, text, function, failure, consequence)

    @tool("merge_failure_mode", _WRITE, "Merge one failure mode into another")
    def merge_failure_mode(failure_mode_id: str, into_failure_mode_id: str, ctx: Context) -> dict[str, Any]:
        """Fold a failure mode into another on the same position (a duplicate, or an ad-hoc
        mode typed in at a failure): its recorded failures, findings and tasks move to the
        other, so the life data keeps them, and it leaves the list. To link an ad-hoc mode to
        an RCM study's, apply the study to the position, then merge the ad-hoc mode into the
        study's. Returns the position."""
        return run(m_for(ctx).merge_failure_mode, failure_mode_id, into_failure_mode_id)

    @tool("set_task_last_done", _WRITE, "Set when a task was last done")
    def set_task_last_done(task_id: str, on: str, ctx: Context) -> dict[str, Any]:
        """Record when a task was last done (before it was tracked here), so its next
        due date counts from then. Task ids are in get_position."""
        return run(m_for(ctx).set_last_done, task_id, on)

    @tool("create_location", _WRITE, "Create a location")
    def create_location(name: str, ctx: Context, parent_id: str | None = None, description: str = "") -> dict[str, Any]:
        """A physical place (site, area, building, room, substation, store), optionally inside
        another: the physical tree, separate from the positions (the functional tree). Don't
        mirror the positions here: make the places, then give positions a location_id."""
        return run(m_for(ctx).create_location, name, parent_id, description)

    @tool("place_item", _WRITE, "Place an item at a location")
    def place_item(item_id: str, location_id: str, ctx: Context, on: DateText = None) -> dict[str, Any]:
        """Record where an item that ISN'T fitted is: a spare in a store, one away at a
        repairer or in the workshop. A fitted item is where its position is and is refused here:
        set the position's location instead (update_position location_id). An item taken out of
        a position stays 'last at' that position's location until it's placed. 'on' defaults to
        today."""
        return run(m_for(ctx).place_item, item_id, location_id, on)

    # ---- work ---------------------------------------------------------------------------

    @tool("open_work_order", _WRITE, "Open a work order")
    def open_work_order(position_id: str, title: str, ctx: Context,
                        type: Literal["corrective", "preventive", "inspection", "other"] = "corrective",
                        task_id: str | None = None, due: DateText = None, notes: str = "",
                        trade: str | None = None) -> dict[str, Any]:
        """Open a work order on a position: corrective (something's wrong), preventive
        (usually for a task: task_id), inspection, or other. trade: the trade, licence or
        competency the work needs ('licensed electrician'); a task's work order takes the
        task's unless given. The result flags warranty if the fitted item is under one."""
        return run(m_for(ctx).open_work_order, position_id, title, type, task_id, due, notes, trade)

    @tool("generate_work_orders", _WRITE, "Create work orders for due tasks")
    def generate_work_orders(ctx: Context, horizon_days: int = 30) -> dict[str, Any]:
        """Open a preventive work order for every task due within horizon_days that
        doesn't already have an open one."""
        return {"work_orders": run(m_for(ctx).generate_work_orders, max(0, min(horizon_days, 366)))}

    @tool("close_work_order", _WRITE, "Close a work order")
    def close_work_order(work_order_id: str, ctx: Context,
                         actions: Annotated[list[dict], Field(description=(
                             "What was done, in order. Each: {kind: 'replace'|'repair'|'inspect'|'other', "
                             "failure_mode_id?: a failure mode on the position, or failure_mode_text?: one in "
                             "words (the position's mode of that name, else a new ad-hoc one) (for a replace, "
                             "naming one means it failed that way; none means a planned replacement), "
                             "finding?: 'ok'|'degraded'|'found_failed' (inspect only), "
                             "new_item?: {name, serial?, part_number?, manufacturer?} or item_id? "
                             "(replace: what went in), part_id?: a catalogue part used doing it (from "
                             "get_work_order's suggested_parts; for a replace with no new_item / item_id, the new "
                             "item is made from it), quantity? (default: the parts list's quantity per job, "
                             "else 1), from_location_id? (issue it from stock there), notes?}"))] = [],
                         on: DateText = None, notes: str = "",
                         readings: Annotated[list[dict], Field(description=(
                             "Manual readings taken during the work: [{point_id, value}]."))] = []) -> dict[str, Any]:
        """Close a work order with what was done. A replacement ends the fitted item's
        time at the position (a failure if a failure mode is named, otherwise a planned
        removal) and fits the new item; that is what builds the life data. Get the
        position's failure-mode ids from get_work_order first; if none fits, describe it in
        failure_mode_text rather than leaving a failure as planned. Nothing is saved if any
        action is invalid."""
        return run(m_for(ctx).close_work_order, work_order_id, actions, on, notes, readings)

    # ---- items, locations, classes and corrections --------------------------------------

    @tool("get_item", _READ, "Read an item")
    def get_item(item_id: str, ctx: Context) -> dict[str, Any]:
        """An item (a physical, serial-numbered thing): details and nameplate fields, notes (with
        note_history: every earlier version, dated); purchase, in-service and manufacture dates
        (each with its precision and source); replacement cost (its own, and its position class's
        default); warranty (with a summary: in warranty until, registration due by); document
        links; where it's fitted and where it is (location: how fitted, from its position, or
        placed; or last_at: the position it last came out of, until it's placed), every position
        it has been fitted to, its placements (current marks the one in force), its own positions
        (an engine's turbos) and its photos."""
        return run(m_for(ctx).item, item_id)

    @tool("update_item", _WRITE, "Update an item's details")
    def update_item(item_id: str, ctx: Context, name: str | None = None, serial: str | None = None,
                    part_number: str | None = None, manufacturer: str | None = None, model: str | None = None,
                    notes: Annotated[str | None, Field(description=(
                        "Replaces the WHOLE note. To add to it, use append_note."))] = None,
                    append_note: Annotated[str | None, Field(description=(
                        "A line to add to the end of the notes, dated today; the rest is kept."))] = None,
                    nameplate: Annotated[dict[str, str] | None, Field(description=(
                        "Other fields from the nameplate, as label: value (e.g. {'Capacity': '315 L', "
                        "'Element': '3.6 kW', 'Year': '2019'}). Merged into what's there; a value of '' "
                        "removes that field."))] = None,
                    purchase_date: ItemDate = None, in_service_date: ItemDate = None,
                    manufacture_date: ItemDate = None, replacement_cost: ReplacementCost = None,
                    warranty: Annotated[dict[str, Any] | None, Field(description=(
                        "{ends_on: date, terms?: text, coverage?: what it covers, registration_required?: "
                        "bool, registered?: bool, register_by?: date}. Replaces the whole warranty."))] = None,
                    clear: Annotated[list[Literal["purchase_date", "in_service_date", "manufacture_date",
                                                  "replacement_cost", "warranty"]] | None,
                                     Field(description="Details to remove.")] = None) -> dict[str, Any]:
        """Change an item's details. After reading a nameplate photo (get_photo), put the make in
        manufacturer, the model, the serial, and everything else on the plate in nameplate. Say
        what you read and what you couldn't. To add an observation, use append_note rather than
        retyping notes; every version of the note is kept in note_history. Dates, replacement cost
        and warranty go in their own fields, not in notes: in_service_date is when it was installed
        or first used; a date known only roughly keeps its precision (2022 → precision year)."""
        details = {k: v for k, v in (("purchase_date", purchase_date), ("in_service_date", in_service_date),
                                     ("manufacture_date", manufacture_date), ("replacement_cost", replacement_cost),
                                     ("warranty", warranty)) if v is not None}
        details |= {k: None for k in clear or []}
        return run(m_for(ctx).update_item, item_id, nameplate, append_note,
                   **{k: v for k, v in (("name", name), ("serial", serial), ("part_number", part_number),
                                        ("manufacturer", manufacturer), ("model", model), ("notes", notes))
                      if v is not None}, **details)

    @tool("move_item", _WRITE, "Move an item to another position")
    def move_item(item_id: str, position_id: str, ctx: Context, on: DateText = None) -> dict[str, Any]:
        """Move an item from wherever it's fitted to an empty position (a planned removal there and
        a fit here), keeping its one history: a rotable going round, a pump swapped to standby."""
        return run(m_for(ctx).move_item, item_id, position_id, on)

    @tool("void_fitment", _WRITE, "Strike out a mistaken fitment")
    def void_fitment(fitment_id: str, ctx: Context, reason: str = "") -> dict[str, Any]:
        """Strike out a fitment recorded by mistake (wrong item or position): it leaves the
        position's history and life data; the event log keeps it. Fitment ids are in
        get_position (fitments, life_data)."""
        m = m_for(ctx)
        return run(lambda: (m.void_fitment(fitment_id, reason), {"voided": fitment_id})[1])

    @tool("correct_fitment", _WRITE, "Correct a fitment's dates")
    def correct_fitment(fitment_id: str, ctx: Context, start: RoughDate = None, end: RoughDate = None,
                        from_precision: Precision | None = None, to_precision: Precision | None = None
                        ) -> dict[str, Any]:
        """Correct the date an item went in (start) or came out (end) of a position, and how
        well each is known (from_precision / to_precision: exact, month, year, estimated). A
        precision alone re-reads the date already there (from_precision 'year' turns
        2022-07-01 into 2022)."""
        return run(m_for(ctx).correct_fitment, fitment_id, start, end, from_precision, to_precision)

    @tool("update_work_order", _WRITE, "Update a work order")
    def update_work_order(work_order_id: str, ctx: Context, title: str | None = None, due: str | None = None,
                          notes: Annotated[str | None, Field(description=(
                              "Replaces the WHOLE note. To add to it, use append_note."))] = None,
                          type: Literal["corrective", "preventive", "inspection", "other"] | None = None,
                          assignee: str | None = None, planned_for: str | None = None,
                          append_note: Annotated[str | None, Field(description=(
                              "A line to add to the end of the notes, dated today; the rest is kept."))] = None,
                          trade: str | None = None) -> dict[str, Any]:
        """Change an open work order's title, due date (a date, or '' to clear it), notes, type, who
        it's assigned to, the day it's planned for, or the trade / licence / competency the work
        needs ('licensed electrician'; '' clears it). append_note adds a dated line to the notes
        (a finding, progress) and works on closed and cancelled work orders too; every version of
        the note is kept in note_history."""
        return run(m_for(ctx).update_work_order, work_order_id, title, due, notes, type, assignee, planned_for,
                   append_note, trade)

    @tool("set_work_status", _WRITE, "Move a work order along")
    def set_work_status(work_order_id: str, status: Literal["open", "planned", "in_progress", "waiting"],
                        ctx: Context, note: str = "") -> dict[str, Any]:
        """Set an open work order's status: planned, in_progress, waiting (parts or access), or back to
        open. Finish it with close_work_order."""
        return run(m_for(ctx).set_work_status, work_order_id, status, note)

    @tool("log_labour", _WRITE, "Log labour on a work order")
    def log_labour(work_order_id: str, hours: float, ctx: Context, who: str = "", rate: float | None = None,
                   on: DateText = None, note: str = "") -> dict[str, Any]:
        """Hours worked on a work order, by whom, at an hourly rate if known (for its cost)."""
        return run(m_for(ctx).log_labour, work_order_id, hours, who, rate, on, note)

    @tool("add_part_used", _WRITE, "Record a part used")
    def add_part_used(work_order_id: str, ctx: Context, part: str | None = None, quantity: float = 1,
                      unit_cost: float | None = None, part_number: str = "", note: str = "",
                      part_id: str | None = None, from_location_id: str | None = None) -> dict[str, Any]:
        """A part or consumable used on a work order (bearings, a seal kit, oil): free text (part), or a
        catalogue part (part_id; its cost fills in), taken out of stock at from_location_id if given.
        Pick part_id from get_work_order's suggested_parts (the position's parts list) first; its stock
        shows where there are some to take."""
        return run(m_for(ctx).add_part_used, work_order_id, part, quantity, unit_cost, part_number, note,
                   part_id, from_location_id)

    from backend.maintenance import importer

    @tool("import_history", _WRITE, "Import positions and item history")
    def import_history(rows: Annotated[list[dict[str, str]], Field(description=(
                           "One row per item per position: {position: 'House > Pool > Pump', class?, item?, "
                           "serial?, manufacturer?, model?, part number?, fitted?: date, removed?: date, "
                           "failed?: yes/no, failure mode?}. Column names are matched loosely."))],
                       ctx: Context, dry_run: bool = True) -> dict[str, Any]:
        """Bring an existing history in: positions (made from their paths), items and when they were
        fitted, removed and whether they failed. Every row is checked first; with any error nothing is
        written. dry_run (the default) only reports what would be made: show it, then run with
        dry_run false. At most 5000 rows; for a file, the user can import it on the Maintenance page."""
        if len(rows) > importer.MAX_ROWS:
            raise ToolError(f"At most {importer.MAX_ROWS} rows at a time.")
        return run(importer.run, m_for(ctx), [{str(k): str(v) for k, v in r.items()} for r in rows], dry_run)

    @tool("list_parts", _READ, "List parts and stock")
    def list_parts(ctx: Context) -> dict[str, Any]:
        """The parts catalogue: each part's stock by location, reorder points (low = at or below),
        use over the last year and months of cover, the positions that use it (used_at) and
        critical_short when it's a critical spare kept below a position's minimum."""
        return {"parts": run(m_for(ctx).parts)}

    @tool("get_part", _READ, "Read a part")
    def get_part(part_id: str, ctx: Context) -> dict[str, Any]:
        """One catalogue part: stock by location, what supersedes it and what it's interchangeable
        with, and where it's used (used_at: each position whose parts list names it, with the role,
        quantity per job and any critical-spare minimum)."""
        return run(m_for(ctx).part, part_id)

    PartRole = Literal["replacement", "component", "consumable"]

    @tool("add_position_part", _WRITE, "Put a part on a position's parts list")
    def add_position_part(position_id: str, part_id: str, ctx: Context, role: PartRole = "component",
                          quantity: float = 1, critical: bool = False, min_on_hand: float | None = None,
                          notes: str = "") -> dict[str, Any]:
        """Link a catalogue part (create_part first if it isn't there) to a position: its bill of
        materials. role: replacement (the part that replaces what's fitted, one per position),
        component (used in its maintenance: a seal kit, bearings) or consumable (a filter, oil).
        quantity: how many one job takes. critical: a critical spare, with min_on_hand the least to
        keep in stock (default one job's worth); falling below it shows on the overview. notes:
        compatibility ('needs the matching button kit', 'fits from serial 4000 on'). Supersession
        and interchangeable parts come from the catalogue (link_parts), not here. Returns the
        position's parts list."""
        return run(m_for(ctx).add_position_part, position_id, part_id, role, quantity, critical, min_on_hand, notes)

    @tool("update_position_part", _WRITE, "Change a parts-list entry")
    def update_position_part(listing_id: str, ctx: Context, role: PartRole | None = None,
                             quantity: float | None = None, critical: bool | None = None,
                             min_on_hand: float | None = None, notes: str | None = None) -> dict[str, Any]:
        """Change an entry on a position's parts list (its id is in get_position's parts_list): role,
        quantity per job, the critical flag (false drops the minimum), min_on_hand, or the
        compatibility notes. For a different part, remove the entry and add the other."""
        return run(m_for(ctx).update_position_part, listing_id, role, quantity, critical,
                   ... if min_on_hand is None else min_on_hand, notes)

    @tool("remove_position_part", _WRITE, "Take a part off a position's parts list")
    def remove_position_part(listing_id: str, ctx: Context) -> dict[str, Any]:
        """Take an entry off a position's parts list (the part stays in the catalogue). Returns the
        position's parts list."""
        return run(m_for(ctx).remove_position_part, listing_id)

    @tool("spares_cover", _READ, "Where the spares fall short")
    def spares_cover(ctx: Context, include_unlisted: bool = False) -> dict[str, Any]:
        """Where the spares don't cover the plant. short: critical spares with fewer usable in stock
        (the part, what supersedes it and its interchangeable alternatives, in every store) than
        their position's minimum. no_spare: positions whose critical replacement part has none
        usable at all. include_unlisted adds without_parts_list: positions with no parts list yet."""
        return run(m_for(ctx).spares_cover, include_unlisted)

    @tool("create_part", _WRITE, "Add a part to the catalogue")
    def create_part(part_number: str, name: str, ctx: Context, manufacturer: str = "", unit: str = "each",
                    unit_cost: float | None = None, notes: str = "") -> dict[str, Any]:
        """A part in the catalogue, by part number (unique)."""
        return run(m_for(ctx).create_part, part_number, name, manufacturer, unit, unit_cost, notes)

    @tool("adjust_stock", _WRITE, "Receive or issue stock")
    def adjust_stock(part_id: str, location_id: str, quantity: float, ctx: Context, reason: str = "",
                     on: DateText = None) -> dict[str, Any]:
        """Receive stock (positive quantity) or issue / write off (negative) at a location."""
        return run(m_for(ctx).adjust_stock, part_id, location_id, quantity, reason, on)

    @tool("set_reorder_point", _WRITE, "Set a reorder point")
    def set_reorder_point(part_id: str, location_id: str, reorder_point: float, ctx: Context) -> dict[str, Any]:
        """Stock at or below this at the location counts as low."""
        return run(m_for(ctx).set_reorder_point, part_id, location_id, reorder_point)

    @tool("link_parts", _WRITE, "Supersede or link parts")
    def link_parts(part_id: str, other_part_id: str, ctx: Context,
                   relation: Literal["superseded_by", "interchangeable"] = "interchangeable") -> dict[str, Any]:
        """Record that part_id is superseded by other_part_id, or that the two are interchangeable."""
        m = m_for(ctx)
        if relation == "superseded_by":
            return run(m.supersede_part, part_id, other_part_id)
        return run(m.mark_interchangeable, part_id, other_part_id)

    @tool("add_work_cost", _WRITE, "Add another cost to a work order")
    def add_work_cost(work_order_id: str, description: str, amount: float, ctx: Context) -> dict[str, Any]:
        """Any other cost of the work (a contractor, hire, call-out)."""
        return run(m_for(ctx).add_cost, work_order_id, description, amount)

    @tool("remove_work_entry", _WRITE, "Remove a labour, part or cost entry")
    def remove_work_entry(entry_id: str, ctx: Context) -> dict[str, Any]:
        """Remove a labour, part or cost entry recorded by mistake (ids are in get_work_order)."""
        return run(m_for(ctx).remove_entry, entry_id)

    @tool("check_item", _WRITE, "Tick a checklist item")
    def check_item(work_order_id: str, index: int, ctx: Context, done: bool = True) -> dict[str, Any]:
        """Tick (or untick) a work order's checklist item, numbered from 0."""
        return run(m_for(ctx).check_item, work_order_id, index, done)

    @tool("cancel_work_order", _WRITE, "Cancel a work order")
    def cancel_work_order(work_order_id: str, ctx: Context, reason: str = "") -> dict[str, Any]:
        """Cancel an open work order that won't be done (a duplicate, raised by mistake). The reason
        is kept as cancel_reason; the notes are left as they are. Use close_work_order for work
        that was done."""
        return run(m_for(ctx).cancel_work_order, work_order_id, reason)

    Outcome = Literal["fixed_interval", "failure_finding", "on_condition"]
    Source = Literal["manual", "oem", "statutory", "other"]

    @tool("create_task", _WRITE, "Add a scheduled task to a position")
    def create_task(position_id: str, name: str, interval: float, ctx: Context, unit: str = "months",
                    outcome: Outcome | None = None, also_interval: float | None = None, also_unit: str | None = None,
                    point_id: str | None = None, instructions: str = "", checklist: list[str] | None = None,
                    source: Source = "manual", reference: str = "", failure_mode_id: str | None = None,
                    last_done: DateText = None, trade: str = "") -> dict[str, Any]:
        """A scheduled task on a position without an RCM study (e.g. from the maker's manual or
        a regulation). It falls due, raises work orders (generate_work_orders) and renews when a
        new item is fitted, like a task from RCM. interval + unit: days, weeks, months, years, or
        a unit of use (hours, cycles, km) counted by a counter on the position (point_id picks
        one). also_interval + also_unit: a second limit, whichever comes first. outcome:
        fixed_interval (replace or restore; the class life model proposes its interval and
        plan_economics costs it), failure_finding (a check of a hidden function), on_condition
        (a condition check), or none for other routine work (lubrication, cleaning). source:
        oem, statutory, manual (own practice) or other, with reference (a manual section, a
        clause). failure_mode_id links it to a failure mode on the position (from RCM: it then
        becomes that decision's task). last_done: when it was last done, if known. trade: who may
        do it ('licensed electrician', 'gas fitter'); its work orders carry it."""
        return run(m_for(ctx).create_task, position_id, name, interval, unit, outcome, also_interval, also_unit,
                   point_id, instructions, checklist, source, reference, failure_mode_id, last_done, trade)

    @tool("update_task", _WRITE, "Update a task")
    def update_task(task_id: str, ctx: Context, name: str | None = None, interval: float | None = None,
                    unit: str | None = None, also_interval: float | None = None, also_unit: str | None = None,
                    point_id: str | None = None, instructions: str | None = None,
                    checklist: list[str] | None = None, failure_mode_id: str | None = None,
                    unlink_failure_mode: bool = False, source: Source | None = None,
                    reference: str | None = None, outcome: Outcome | None = None,
                    clear_outcome: bool = False, trade: str | None = None) -> dict[str, Any]:
        """Rename a task or change its interval (unit: days, weeks, months, years, or a unit of use
        such as hours, cycles, km, from a counter on the position). also_interval + also_unit
        add a second limit, whichever comes first (every 500 hours or 6 months); also_interval 0
        removes it. point_id picks the counter a task by use goes by. instructions, checklist (steps to
        tick off) and trade (who may do it: 'licensed electrician', 'gas fitter'; '' clears it) are
        copied onto each work order the task raises. failure_mode_id links a task added by hand to
        a failure mode on its position (one from an RCM study makes it that decision's task:
        applying the study again updates it); unlink_failure_mode removes the link. source,
        reference and outcome (or clear_outcome) apply to tasks added by hand."""
        mode = "" if unlink_failure_mode else failure_mode_id
        return run(m_for(ctx).update_task, task_id, name, interval, unit, also_interval, also_unit, point_id,
                   instructions, checklist, mode, source, reference,
                   None if clear_outcome else outcome if outcome is not None else ..., trade)

    @tool("add_measurement_point", _WRITE, "Add a measurement point")
    def add_measurement_point(position_id: str, ctx: Context, name: str = "",
                              kind: Literal["counter", "condition"] = "condition", unit: str = "",
                              source: Literal["manual", "automated"] = "manual", tag: str = "",
                              alarm_above: float | None = None, alarm_below: float | None = None) -> dict[str, Any]:
        """Something measured on a position. kind 'counter' counts use (run hours, cycles, km; only goes
        up; tasks by use in that unit fall due from it). kind 'condition' shows condition (vibration
        mm/s, temperature, wear) with alarm limits: a reading past one opens an inspection. source
        'manual': someone reads it (record_reading). 'automated': a feed sends readings under tag to
        the ingest API (POST /api/ingest/maintenance/readings with an ingest-scope token)."""
        return run(m_for(ctx).add_point, position_id, name, kind, unit, source, tag, alarm_above, alarm_below)

    @tool("record_reading", _WRITE, "Record a manual reading")
    def record_reading(point_id: str, value: float, ctx: Context, on: DateText = None, note: str = "") -> dict[str, Any]:
        """A manual reading of a measurement point (the hour meter says 12,340; vibration 4.2 mm/s).
        Counters only go up. 'on' is the day it was read (a past date backdates it). To fix one already
        recorded, use correct_reading or void_reading. Returns the point: latest, rate or trend,
        status, any alarm work order."""
        return run(m_for(ctx).record_reading, point_id, value, on, note)

    @tool("get_measurement_point", _READ, "Read a measurement point")
    def get_measurement_point(point_id: str, ctx: Context) -> dict[str, Any]:
        """A measurement point: kind, source and tag, latest reading, rate (counter) or trend and the date
        it should reach an alarm limit (condition), status, recent readings. Ids are in get_position.
        A manual point's readings include struck-out ones, each with a status: ok, correction (replaces
        another: replaces, reason), voided (void_reason) or replaced (by a correction: replaced_by).
        Rates, due dates and alarms use only ok and correction readings."""
        return run(m_for(ctx).point, point_id)

    @tool("void_reading", _WRITE, "Strike out a reading")
    def void_reading(reading_id: str, reason: str, ctx: Context) -> dict[str, Any]:
        """Strike out a manual reading entered by mistake (a duplicate, the wrong meter), saying why.
        It stays in the point's readings, marked voided; rates, due dates and alarms leave it out.
        If the value or date was just wrong, use correct_reading instead. Reading ids are in
        get_measurement_point. Returns the point."""
        return run(m_for(ctx).void_reading, reading_id, reason)

    @tool("correct_reading", _WRITE, "Correct a reading")
    def correct_reading(reading_id: str, reason: str, ctx: Context, value: float | None = None,
                        on: Annotated[str | None, Field(description=(
                            "The date it was really read, like 2026-10-13. Default: unchanged."))] = None
                        ) -> dict[str, Any]:
        """Correct a manual reading: its value (a typo: 3,774 for 4,774), its date (an old reading
        entered as today: move it to the day it was read), or both. The original is struck out and
        the corrected reading recorded in its place, linked both ways, with the reason. Rates and
        the due dates of tasks by use are worked out again. Returns the point."""
        return run(m_for(ctx).correct_reading, reading_id, value, on, reason)

    @tool("update_measurement_point", _WRITE, "Change a measurement point")
    def update_measurement_point(point_id: str, ctx: Context, name: str | None = None,
                                 alarm_above: float | None = None, alarm_below: float | None = None,
                                 clear_alarm_above: bool = False, clear_alarm_below: bool = False,
                                 tag: str | None = None) -> dict[str, Any]:
        """Rename a point, set or clear its alarm limits, or change an automated point's tag."""
        kwargs = {}
        if name is not None:
            kwargs["name"] = name
        if alarm_above is not None or clear_alarm_above:
            kwargs["alarm_above"] = None if clear_alarm_above else alarm_above
        if alarm_below is not None or clear_alarm_below:
            kwargs["alarm_below"] = None if clear_alarm_below else alarm_below
        if tag is not None:
            kwargs["tag"] = tag
        return run(m_for(ctx).update_point, point_id, **kwargs)

    @tool("retire_task", _WRITE, "Retire a task")
    def retire_task(task_id: str, ctx: Context, reason: str = "") -> dict[str, Any]:
        """Stop scheduling a task (it stays in the history)."""
        m = m_for(ctx)
        return run(lambda: (m.retire_task(task_id, reason), {"retired": task_id})[1])

    @tool("retire_position", _WRITE, "Retire a position")
    def retire_position(position_id: str, ctx: Context, reason: str = "") -> dict[str, Any]:
        """Take a position out of the plant (it stays in the history). Nothing may be fitted, no
        position inside it in use, and no work order open."""
        m = m_for(ctx)
        return run(lambda: (m.retire_position(position_id, reason), {"retired": position_id})[1])

    @tool("get_location", _READ, "Read a location")
    def get_location(location_id: str, ctx: Context) -> dict[str, Any]:
        """A location (the physical tree): its path, the locations inside it (with counts), the
        positions there, set on them or inherited, here or in a location inside it, grouped by
        system (each group's top position), each with its fitted item, whether its location is
        set on it (direct) or inherited_from, and its open work orders; the items placed there
        (not fitted: spares, repairs); and counts (positions, fitted_items, items,
        open_work_orders). At most 500 positions are listed (positions_truncated); counts cover
        all. For the work there, list_work_orders with this location_id."""
        return run(m_for(ctx).location, location_id)

    @tool("adopt_item_placements", _WRITE, "Turn fitted items' placements into position locations")
    def adopt_item_placements(ctx: Context, dry_run: bool = True) -> dict[str, Any]:
        """A one-off tidy-up for a workspace that placed fitted items at locations (before a
        fitted item was simply where its position is): each fitted item placed while fitted gives
        its position that location, where the position has none of its own and doesn't already
        inherit it. Placements from before an item went in (where a spare was kept) are skipped.
        dry_run (the default) only lists the changes: show them, then run with dry_run false."""
        return run(m_for(ctx).adopt_placements, dry_run)

    @tool("update_location", _WRITE, "Update a location")
    def update_location(location_id: str, ctx: Context, name: str | None = None, description: str | None = None,
                        parent_id: str | None = None, move_to_top_level: bool = False) -> dict[str, Any]:
        """Rename a location, change its description, or move it inside another (parent_id) or to
        the top level."""
        kwargs = {k: v for k, v in (("name", name), ("description", description)) if v is not None}
        if parent_id or move_to_top_level:
            kwargs["parent_id"] = None if move_to_top_level else parent_id
        return run(m_for(ctx).update_location, location_id, **kwargs)

    @tool("list_position_classes", _READ, "List position classes")
    def list_position_classes(ctx: Context) -> dict[str, Any]:
        """Each class of position (e.g. 'Centrifugal pump'), with its positions, fitments and
        failures (what can be compared and pooled), its costs, default replacement cost and
        document links."""
        return {"classes": run(m_for(ctx).position_classes)}

    @tool("class_life_data", _READ, "Life data for a position class")
    def class_life_data(position_class: str, ctx: Context) -> dict[str, Any]:
        """Every fitment at every position of a class, pooled: x = days in service, c = 0 failed
        or 1 censored (removed on purpose, or still fitted). Where a date was known only roughly,
        the row also has xl / xr, the shortest and longest life the dates allow: a failure is then
        c = 2 (interval censored: fit with xl / xr), anything else censored at xl. fit_class_model
        handles both."""
        return run(m_for(ctx).class_life_data, position_class)

    # ---- connections, redundancy, the generated RBD -----------------------------------

    from backend.maintenance import rbd_derive

    @tool("connect_positions", _WRITE, "Connect two positions")
    def connect_positions(from_id: str, to_id: str, ctx: Context,
                          kind: Literal["flow", "electrical", "mechanical", "signal", "data", "other"] = "flow",
                          medium: str = "", name: str = "", rating: str = "",
                          realised_by: str | None = None) -> dict[str, Any]:
        """Say that something passes from one position to another (water from the tank to the pump,
        240 V from the switchboard to the motor, a signal from the sensor to the controller).
        realised_by: a position for the connection itself when it's maintainable (a hose, a cable).
        Connections wire the RBD generate_rbd makes and drive impact."""
        return run(m_for(ctx).connect, from_id, to_id, kind, medium, name, rating, realised_by)

    @tool("disconnect_positions", _WRITE, "Remove a connection")
    def disconnect_positions(interface_id: str, ctx: Context) -> dict[str, Any]:
        """Remove a connection (its id is in get_position's connections)."""
        m = m_for(ctx)
        return run(lambda: (m.disconnect(interface_id), {"removed": interface_id})[1])

    @tool("create_redundancy_group", _WRITE, "Make a redundancy group")
    def create_redundancy_group(member_ids: list[str], ctx: Context, name: str = "", k: int = 1,
                                mode: Literal["active", "standby"] = "active",
                                standby: Literal["cold", "warm", "hot"] = "cold") -> dict[str, Any]:
        """Positions doing the same job where k of them are enough (two pumps, either will do: k = 1).
        mode standby: the others wait to take over. The generated RBD draws it as k of n."""
        return run(m_for(ctx).create_group, name, member_ids, k, mode, standby)

    @tool("update_redundancy_group", _WRITE, "Change a redundancy group")
    def update_redundancy_group(group_id: str, ctx: Context, name: str | None = None, k: int | None = None,
                                mode: Literal["active", "standby"] | None = None,
                                standby: Literal["cold", "warm", "hot"] | None = None,
                                add: list[str] = [], remove: list[str] = []) -> dict[str, Any]:
        """Rename a group, change k or its mode, or add / remove member positions."""
        return run(m_for(ctx).update_group, group_id, name, k, mode, standby, add, remove)

    @tool("set_duty", _WRITE, "Set which unit is on duty")
    def set_duty(group_id: str, position_id: str, ctx: Context) -> dict[str, Any]:
        """Record which member of a standby group is running now (a duty/standby swap)."""
        return run(m_for(ctx).set_duty, group_id, position_id)

    @tool("impact", _READ, "What depends on a position")
    def impact(position_id: str, ctx: Context) -> dict[str, Any]:
        """If this position fails, what loses its supply downstream (through connections), and
        whether redundancy covers it."""
        return run(m_for(ctx).impact, position_id)

    @tool("generate_rbd", _WRITE, "Make an RBD from the plant")
    def generate_rbd(position_id: str, ctx: Context) -> dict[str, Any]:
        """Generate (or regenerate) a reliability block diagram for a system position from the
        positions inside it: connections wire the blocks, redundancy groups become k-of-n votes, and
        each block takes its class's fitted life model (placeholders otherwise, listed in notes).
        It's saved as a normal RBD: analyse it with analyze_rbd."""
        return run(rbd_derive.save, m_for(ctx), _db(), position_id)

    # ---- closing the loop -------------------------------------------------------------

    from backend.maintenance import loop

    @tool("set_class_costs", _WRITE, "Set a position class's costs")
    def set_class_costs(position_class: str, ctx: Context, planned_cost: float | None = None,
                        failure_cost: float | None = None, availability_target: float | None = None,
                        replacement_cost: ReplacementCost = None,
                        clear_replacement_cost: bool = False) -> dict[str, Any]:
        """What a planned replacement and a failure cost for a class of position (any currency, the
        same for both), and the availability a hidden (protective) function must reach (e.g. 0.99).
        Proposed intervals are optimised against these. replacement_cost: what an item doing this
        job costs to replace, the default for items with none of their own."""
        m = m_for(ctx)

        def go():
            if (planned_cost, failure_cost, availability_target) != (None, None, None):
                m.set_class_costs(position_class, planned_cost, failure_cost, availability_target)
            if replacement_cost is not None or clear_replacement_cost:
                m.set_class_replacement_cost(position_class, None if clear_replacement_cost else replacement_cost)
            return m.position_class(position_class)
        return run(go)

    @tool("fit_class_model", _WRITE, "Fit a life model for a position class")
    def fit_class_model(position_class: str, ctx: Context,
                        distribution: Literal["weibull", "best", "lognormal", "exponential", "gamma"] = "weibull"
                        ) -> dict[str, Any]:
        """Fit a life distribution (SurPyval) to every fitment of a class's positions (failures and
        suspensions, in days), save it as a model in the workspace, and propose task intervals from
        it and the class's costs. Needs at least 2 failures on record."""
        from backend import fitting

        m = m_for(ctx)
        try:
            return run(loop.fit_class_model, m, _db(), position_class, distribution)
        except fitting.FitError as err:
            raise ToolError(f"The fit didn't work: {err}") from None

    @tool("plan_economics", _READ, "Cost of a replacement plan")
    def plan_economics(position_class: str, ctx: Context, interval: float | None = None,
                       unit: Literal["days", "weeks", "months", "years"] = "months", horizon_years: float = 10,
                       discount_rate: float = 0.07) -> dict[str, Any]:
        """What a class's replacement plan costs a year: the current plan, the best interval, running to
        failure, and (with interval) a what-if; each with its net present cost over the horizon at the
        discount rate. Needs the class's fitted model and costs."""
        return run(loop.economics, m_for(ctx), position_class, interval, unit, horizon_years, discount_rate)

    @tool("review_updates", _READ, "List proposed changes")
    def review_updates(ctx: Context, status: Literal["pending", "accepted", "rejected", "superseded", "all"] = "pending"
                       ) -> dict[str, Any]:
        """Changes the life models propose to the plan (a task's interval, or retiring a task), each
        with its reason. Show them to the user and let them decide; accept_update or reject_update."""
        return {"proposals": run(m_for(ctx).proposals, None if status == "all" else status)}

    @tool("accept_update", _WRITE, "Accept a proposed change")
    def accept_update(proposal_id: str, ctx: Context, note: str = "") -> dict[str, Any]:
        """Apply a proposed change (only when the user says so)."""
        return run(m_for(ctx).decide_proposal, proposal_id, True, note)

    @tool("reject_update", _WRITE, "Reject a proposed change")
    def reject_update(proposal_id: str, ctx: Context, note: str = "") -> dict[str, Any]:
        """Turn down a proposed change, optionally saying why."""
        return run(m_for(ctx).decide_proposal, proposal_id, False, note)

    @tool("explain_task", _READ, "Explain a task's history")
    def explain_task(task_id: str, ctx: Context) -> dict[str, Any]:
        """Why a task is what it is: where it came from (RCM), every change, and the proposals
        behind them."""
        return run(m_for(ctx).explain_task, task_id)

    # ---- documents ---------------------------------------------------------------------

    @tool("add_document", _WRITE, "Link a document")
    def add_document(url: str, ctx: Context, target_id: str | None = None, position_class: str | None = None,
                     title: str = "",
                     kind: Literal["manual", "datasheet", "invoice", "drawing", "certificate", "other"] = "other"
                     ) -> dict[str, Any]:
        """Attach a link to a document (an owner's manual, a datasheet, an invoice, a drawing, a
        certificate) to an item or position (target_id), or to a class of position
        (position_class: e.g. the datasheet every pump of that model shares). The url must be an
        http(s) web address; use this rather than putting links in notes. The links show on
        get_item, get_position and list_position_classes."""
        return run(m_for(ctx).add_document, url, title, kind, target_id, position_class)

    @tool("remove_document", _WRITE, "Remove a document link")
    def remove_document(document_id: str, ctx: Context) -> dict[str, Any]:
        """Remove a document link (its id is in the documents of get_item, get_position or
        list_position_classes)."""
        return run(m_for(ctx).remove_document, document_id)

    # ---- photos ------------------------------------------------------------------------

    from mcp.server.mcpserver import Image

    from backend import config
    from backend.routers.maintenance import link_payload, photo_links, remove_photo, served_photo

    @tool("create_photo_link", _WRITE, "Get a link to add photos")
    def create_photo_link(target_id: str, ctx: Context, caption: str = "") -> dict[str, Any]:
        """A link for adding photos to a position, location, item or work order from a phone,
        with no sign-in: give the url to the user to open (you can't send a photo's file
        yourself, even one shared in this chat). They can take or choose up to 20 photos
        in the next 30 minutes. Photos are stored without location or camera details; if
        one carries a location, the page asks the user whether to save it as where the
        equipment is. Then call photo_link_status, and get_photo to look at them (read a
        nameplate's make, model and serial into the item's details)."""
        m = m_for(ctx)
        request = ctx.request_context.request
        base = config.PUBLIC_BASE_URL or str(request.base_url).rstrip("/")
        return run(lambda: link_payload(base, m, m.photo_target(target_id), caption[:200]))

    @tool("photo_link_status", _READ, "Check a photo link")
    def photo_link_status(link_id: str, ctx: Context) -> dict[str, Any]:
        """The photos added through a link so far, and any location a photo carried with the
        user's answer (saved / declined / null: not answered on the page). If unanswered,
        ask the user whether to save it with set_coordinates; never save it unasked."""
        m = m_for(ctx)
        doc = photo_links().get(link_id, org=m.org)
        if doc is None:
            raise ToolError("Photo link not found.")
        return photo_links().public(doc)

    @tool("list_photos", _READ, "List photos")
    def list_photos(target_id: str, ctx: Context) -> dict[str, Any]:
        """The photos of a position, location, item or work order (ids, captions, dates)."""
        m = m_for(ctx)
        return run(lambda: {"target": target_id, "photos": (m.photo_target(target_id), m.photos_of(target_id))[1]})

    @tool("get_photo", _READ, "Look at a photo")
    def get_photo(photo_id: str, ctx: Context, size: Literal["full", "thumb"] = "full") -> Image:
        """The photo itself, to look at: read a nameplate (make, model, serial, ratings; then
        update_item) or check a condition. 'full' is up to 1600 px; 'thumb' 400 px."""
        m = m_for(ctx)
        run(m.photo, photo_id)
        data = served_photo(m, photo_id, size)
        if data is None:
            raise ToolError("That photo was removed, or its file is missing.")
        return Image(data=data, format="jpeg")

    @tool("set_coordinates", _WRITE, "Set where equipment is")
    def set_coordinates(target_id: str, lat: float, lon: float, ctx: Context,
                        source: Literal["photo", "manual"] = "manual") -> dict[str, Any]:
        """Save a position's, item's or location's latitude and longitude (a work order's go
        on its position). Use a photo's location only when the user has said to."""
        return run(m_for(ctx).set_coordinates, target_id, lat, lon, source)

    @tool("remove_photo", _WRITE, "Remove a photo")
    def remove_photo(photo_id: str, ctx: Context) -> dict[str, Any]:
        """Remove a photo from what it shows (the history keeps that it was there; the
        image itself is deleted)."""
        return run(remove_photo, m_for(ctx), photo_id)

    # The tools are listed only to people who may use them: wrap the server's
    # tools/list handler to drop them for everyone else.
    handlers = mcp._lowlevel_server._request_handlers
    entry = handlers["tools/list"]
    _ORIGINAL["tools/list"] = entry
    hidden = set(TOOL_NAMES)

    async def list_tools(ctx, params):
        result = await entry.handler(ctx, params)
        user = getattr(getattr(getattr(ctx, "request", None), "state", None), "reliafy_user", None)
        if allowed(user):
            return result
        return result.model_copy(update={"tools": [t for t in result.tools if t.name not in hidden]})

    handlers["tools/list"] = dataclasses.replace(entry, handler=list_tools)

    mcp_server._FIT_TOOLS.update(PRO_FIT_TOOLS)
    mcp_server.PRO_ONLY_TOOLS.update(PRO_FIT_TOOLS)
    mcp_server.HEAVY_TOOLS.update(HEAVY_TOOLS)


def unregister() -> None:
    """Remove the maintenance tools again (for tests)."""
    from backend import mcp_server
    from backend.mcp_server import mcp

    mcp_server._FIT_TOOLS.difference_update(PRO_FIT_TOOLS)
    mcp_server.PRO_ONLY_TOOLS.difference_update(PRO_FIT_TOOLS)
    mcp_server.HEAVY_TOOLS.difference_update(HEAVY_TOOLS)
    for name in TOOL_NAMES:
        mcp.remove_tool(name)
    TOOL_NAMES.clear()
    if "tools/list" in _ORIGINAL:
        mcp._lowlevel_server._request_handlers["tools/list"] = _ORIGINAL.pop("tools/list")
