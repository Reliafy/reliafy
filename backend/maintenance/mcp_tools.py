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


def register() -> None:
    """Add the maintenance tools to the MCP server (idempotent)."""
    if TOOL_NAMES:
        return
    from mcp.server.mcpserver import Context
    from mcp.server.mcpserver.exceptions import ToolError

    from backend.maintenance.access import allowed
    from backend.maintenance.service import Invalid, Maintenance, NotFound, summary
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

    # ---- reading ---------------------------------------------------------------------

    @tool("maintenance_overview", _READ, "Maintenance overview")
    def maintenance_overview(ctx: Context) -> dict[str, Any]:
        """The maintenance workspace at a glance: counts, the tree of positions (the
        functional hierarchy, each with what's fitted, its task count, next due date
        and open work orders), tasks due in the next 30 days, and open work orders.
        Start here; use the ids with the other maintenance tools."""
        m = m_for(ctx)
        return run(lambda: {"summary": summary(m), "tree": m.tree(), "due": m.due_tasks(30),
                            "open_work_orders": m.work_orders("open")})

    @tool("get_position", _READ, "Read a maintenance position")
    def get_position(position_id: str, ctx: Context) -> dict[str, Any]:
        """One position: its path, the positions inside it, the item fitted now, every
        past fitment, its failure modes (from RCM), its tasks with last-done and next-due
        dates, its work orders, and its life data (one row per item fitted: days in
        service, c = 0 failed or 1 censored)."""
        return run(m_for(ctx).position, position_id)

    @tool("list_work_orders", _READ, "List work orders")
    def list_work_orders(ctx: Context, status: Literal["open", "closed"] | None = None) -> dict[str, Any]:
        """Work orders, newest first, optionally only open or closed ones."""
        return {"work_orders": run(m_for(ctx).work_orders, status)}

    @tool("get_work_order", _READ, "Read a work order")
    def get_work_order(work_order_id: str, ctx: Context) -> dict[str, Any]:
        """A work order: its position, task, status and dates, the actions recorded when
        it closed, and (for an open one) the item fitted now and the position's failure
        modes, which close_work_order's actions can name."""
        return run(m_for(ctx).work_order, work_order_id)

    @tool("list_maintenance_items", _READ, "List items")
    def list_maintenance_items(ctx: Context) -> dict[str, Any]:
        """Every physical item (serial-numbered thing), with the position it's fitted to
        and the location it's placed at, if any."""
        return {"items": run(m_for(ctx).items)}

    @tool("list_locations", _READ, "List locations")
    def list_locations(ctx: Context) -> dict[str, Any]:
        """Physical locations (sites, buildings, rooms, stores) as a tree, with how many items are
        placed in each."""
        return {"tree": run(m_for(ctx).location_tree)}

    # ---- building the plant ------------------------------------------------------------

    @tool("create_position", _WRITE, "Create a position")
    def create_position(name: str, ctx: Context, parent_id: str | None = None, tag: str = "",
                        position_class: str = "", description: str = "") -> dict[str, Any]:
        """A position: a job something does in the plant (the functional hierarchy),
        such as 'Hot water system' or 'Pump A'. Items are fitted to positions. Put it
        inside another position with parent_id, or inside an item (parent_id = an item id) for
        a position that travels with that item, like an engine's turbo. position_class groups
        like positions for comparison and pooled life data (e.g. 'Centrifugal pump')."""
        m = m_for(ctx)
        return run(lambda: m.position(m.create_position(name, tag, parent_id, position_class, description)["id"]))

    @tool("update_position", _WRITE, "Update a position")
    def update_position(position_id: str, ctx: Context, name: str | None = None, tag: str | None = None,
                        position_class: str | None = None, description: str | None = None,
                        parent_id: str | None = None, move_to_top_level: bool = False) -> dict[str, Any]:
        """Rename a position, change its tag, class or description, or move it inside
        another position (parent_id) or to the top level (move_to_top_level)."""
        m = m_for(ctx)
        changes = {k: v for k, v in (("name", name), ("tag", tag), ("position_class", position_class),
                                     ("description", description)) if v is not None}
        if parent_id or move_to_top_level:
            changes["parent_id"] = None if move_to_top_level else parent_id
        return run(lambda: (m.update_position(position_id, **changes), m.position(position_id))[1])

    @tool("copy_position", _WRITE, "Copy a position")
    def copy_position(position_id: str, name: str, ctx: Context, parent_id: str | None = None) -> dict[str, Any]:
        """Copy a position and everything inside it (the positions, their failure modes
        and tasks; not items or work orders) under a new name, optionally inside another
        position. Call it repeatedly to build many like structures."""
        return run(m_for(ctx).copy_position, position_id, name, parent_id)

    @tool("position_from_rcm", _WRITE, "Create a position from an RCM study")
    def position_from_rcm(study_id: str, ctx: Context, parent_id: str | None = None) -> dict[str, Any]:
        """Create a position named for an RCM study's system, with the study's failure
        modes and a scheduled task for every decision that has an interval. Find study
        ids with the RCM tools."""
        return run(m_for(ctx).position_from_rcm, study_for(ctx, study_id), parent_id)

    @tool("apply_rcm_to_position", _WRITE, "Apply an RCM study to a position")
    def apply_rcm_to_position(position_id: str, study_id: str, ctx: Context) -> dict[str, Any]:
        """Bring an RCM study's failure modes and scheduled tasks onto an existing
        position. Applying it again adds what's new and updates changed tasks."""
        m = m_for(ctx)
        return run(lambda: {**m.apply_rcm(position_id, study_for(ctx, study_id)), "position": m.position(position_id)})

    @tool("fit_item", _WRITE, "Fit an item to a position")
    def fit_item(position_id: str, ctx: Context, item_id: str | None = None, item_name: str | None = None,
                 serial: str = "", part_number: str = "", manufacturer: str = "", on: DateText = None) -> dict[str, Any]:
        """Fit an item to an empty position: an existing item (item_id), or a new one
        (item_name, with optional serial, part number and manufacturer). 'on' is the
        date it went in. A new item renews the position's tasks. To replace an item,
        close a work order with a replace action instead."""
        new_item = {"name": item_name, "serial": serial, "part_number": part_number,
                    "manufacturer": manufacturer} if item_name else None
        return run(m_for(ctx).fit, position_id, item_id, new_item, on)

    @tool("remove_item", _WRITE, "Remove a fitted item")
    def remove_item(position_id: str, ctx: Context, on: DateText = None,
                    reason: Literal["planned", "failure", "other"] = "planned",
                    failure_mode_id: str | None = None) -> dict[str, Any]:
        """Take the fitted item out of a position with no work order (a correction, or
        moving it). Work done on it belongs on a work order (close_work_order)."""
        return run(m_for(ctx).remove, position_id, on, reason, failure_mode_id)

    @tool("set_task_last_done", _WRITE, "Set when a task was last done")
    def set_task_last_done(task_id: str, on: str, ctx: Context) -> dict[str, Any]:
        """Record when a task was last done (before it was tracked here), so its next
        due date counts from then. Task ids are in get_position."""
        return run(m_for(ctx).set_last_done, task_id, on)

    @tool("create_location", _WRITE, "Create a location")
    def create_location(name: str, ctx: Context, parent_id: str | None = None, description: str = "") -> dict[str, Any]:
        """A physical place (site, building, room, store), optionally inside another."""
        return run(m_for(ctx).create_location, name, parent_id, description)

    @tool("place_item", _WRITE, "Place an item at a location")
    def place_item(item_id: str, location_id: str, ctx: Context, on: DateText = None) -> dict[str, Any]:
        """Record where an item physically is (a store, the workshop), separately
        from what job it's fitted to."""
        return run(m_for(ctx).place_item, item_id, location_id, on)

    # ---- work ---------------------------------------------------------------------------

    @tool("open_work_order", _WRITE, "Open a work order")
    def open_work_order(position_id: str, title: str, ctx: Context,
                        type: Literal["corrective", "preventive", "inspection", "other"] = "corrective",
                        task_id: str | None = None, due: DateText = None, notes: str = "") -> dict[str, Any]:
        """Open a work order on a position: corrective (something's wrong), preventive
        (usually for a task: task_id), inspection, or other."""
        return run(m_for(ctx).open_work_order, position_id, title, type, task_id, due, notes)

    @tool("generate_work_orders", _WRITE, "Create work orders for due tasks")
    def generate_work_orders(ctx: Context, horizon_days: int = 30) -> dict[str, Any]:
        """Open a preventive work order for every task due within horizon_days that
        doesn't already have an open one."""
        return {"work_orders": run(m_for(ctx).generate_work_orders, max(0, min(horizon_days, 366)))}

    @tool("close_work_order", _WRITE, "Close a work order")
    def close_work_order(work_order_id: str, ctx: Context,
                         actions: Annotated[list[dict], Field(description=(
                             "What was done, in order. Each: {kind: 'replace'|'repair'|'inspect'|'other', "
                             "failure_mode_id?: a failure mode on the position (for a replace, naming one "
                             "means it failed that way; none means a planned replacement), "
                             "finding?: 'ok'|'degraded'|'found_failed' (inspect only), "
                             "new_item?: {name, serial?, part_number?, manufacturer?} or item_id? "
                             "(replace: what went in), notes?}"))] = [],
                         on: DateText = None, notes: str = "",
                         readings: Annotated[list[dict], Field(description=(
                             "Meter readings taken during the work: [{meter_id, value}]."))] = []) -> dict[str, Any]:
        """Close a work order with what was done. A replacement ends the fitted item's
        time at the position (a failure if a failure mode is named, otherwise a planned
        removal) and fits the new item; that is what builds the life data. Get the
        position's failure-mode ids from get_work_order first. Nothing is saved if any
        action is invalid."""
        return run(m_for(ctx).close_work_order, work_order_id, actions, on, notes, readings)

    # ---- items, locations, classes and corrections --------------------------------------

    @tool("get_item", _READ, "Read an item")
    def get_item(item_id: str, ctx: Context) -> dict[str, Any]:
        """An item (a physical, serial-numbered thing): details and nameplate fields, where it's
        fitted and placed now, every position it has been fitted to, its own positions (an
        engine's turbos) and its photos."""
        return run(m_for(ctx).item, item_id)

    @tool("update_item", _WRITE, "Update an item's details")
    def update_item(item_id: str, ctx: Context, name: str | None = None, serial: str | None = None,
                    part_number: str | None = None, manufacturer: str | None = None, model: str | None = None,
                    notes: str | None = None,
                    nameplate: Annotated[dict[str, str] | None, Field(description=(
                        "Other fields from the nameplate, as label: value (e.g. {'Capacity': '315 L', "
                        "'Element': '3.6 kW', 'Year': '2019'}). Merged into what's there; a value of '' "
                        "removes that field."))] = None) -> dict[str, Any]:
        """Change an item's details. After reading a nameplate photo (get_photo), put the make in
        manufacturer, the model, the serial, and everything else on the plate in nameplate. Say
        what you read and what you couldn't."""
        return run(m_for(ctx).update_item, item_id, nameplate,
                   **{k: v for k, v in (("name", name), ("serial", serial), ("part_number", part_number),
                                        ("manufacturer", manufacturer), ("model", model), ("notes", notes))
                      if v is not None})

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
    def correct_fitment(fitment_id: str, ctx: Context, start: DateText = None, end: DateText = None) -> dict[str, Any]:
        """Correct the date an item went in (start) or came out (end) of a position."""
        return run(m_for(ctx).correct_fitment, fitment_id, start, end)

    @tool("update_work_order", _WRITE, "Update a work order")
    def update_work_order(work_order_id: str, ctx: Context, title: str | None = None, due: str | None = None,
                          notes: str | None = None,
                          type: Literal["corrective", "preventive", "inspection", "other"] | None = None
                          ) -> dict[str, Any]:
        """Change an open work order's title, due date (a date, or '' to clear it), notes or type."""
        return run(m_for(ctx).update_work_order, work_order_id, title, due, notes, type)

    @tool("cancel_work_order", _WRITE, "Cancel a work order")
    def cancel_work_order(work_order_id: str, ctx: Context, reason: str = "") -> dict[str, Any]:
        """Cancel an open work order that won't be done (a duplicate, raised by mistake). Use
        close_work_order for work that was done."""
        return run(m_for(ctx).cancel_work_order, work_order_id, reason)

    @tool("update_task", _WRITE, "Update a task")
    def update_task(task_id: str, ctx: Context, name: str | None = None, interval: float | None = None,
                    unit: str | None = None, also_interval: float | None = None, also_unit: str | None = None,
                    meter_id: str | None = None) -> dict[str, Any]:
        """Rename a task or change its interval (unit: days, weeks, months, years, or a unit of use
        such as hours, cycles, km, read from a meter on the position). also_interval + also_unit
        add a second limit, whichever comes first (every 500 hours or 6 months); also_interval 0
        removes it. meter_id picks a meter for a task by use."""
        return run(m_for(ctx).update_task, task_id, name, interval, unit, also_interval, also_unit, meter_id)

    @tool("add_meter", _WRITE, "Add a usage meter")
    def add_meter(position_id: str, unit: str, ctx: Context, name: str = "") -> dict[str, Any]:
        """A usage meter on a position (unit: hours, cycles, km, starts, ...). Tasks on the position
        that go by that unit fall due from its readings, projected at the recent rate."""
        return run(m_for(ctx).add_meter, position_id, name, unit)

    @tool("record_reading", _WRITE, "Record a meter reading")
    def record_reading(meter_id: str, value: float, ctx: Context, on: DateText = None, note: str = "") -> dict[str, Any]:
        """A meter reading (e.g. the pump's hour meter says 12,340). Readings only go up; a replaced
        meter is a new meter. Meter ids are in get_position (meters)."""
        return run(m_for(ctx).record_reading, meter_id, value, on, note)

    @tool("get_meter", _READ, "Read a meter")
    def get_meter(meter_id: str, ctx: Context) -> dict[str, Any]:
        """A meter: its latest reading, the rate per day, and its recent readings."""
        return run(m_for(ctx).meter, meter_id)

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
        """A location: its path, the locations inside it, the items placed there now, its
        coordinates and photos."""
        return run(m_for(ctx).location, location_id)

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
        failures: what can be compared and pooled."""
        return {"classes": run(m_for(ctx).position_classes)}

    @tool("class_life_data", _READ, "Life data for a position class")
    def class_life_data(position_class: str, ctx: Context) -> dict[str, Any]:
        """Every fitment at every position of a class, pooled: x = days in service, c = 0 failed
        or 1 censored (removed on purpose, or still fitted). Ready for fit_distribution."""
        return run(m_for(ctx).class_life_data, position_class)

    # ---- photos ------------------------------------------------------------------------

    from mcp.server.mcpserver import Image

    from backend import config
    from backend.routers.maintenance import get_photo_store, link_payload, photo_links

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
        data = get_photo_store().get(photo_id, size)
        if data is None:
            raise ToolError("That photo's file is missing.")
        return Image(data=data, format="jpeg")

    @tool("set_coordinates", _WRITE, "Set where equipment is")
    def set_coordinates(target_id: str, lat: float, lon: float, ctx: Context,
                        source: Literal["photo", "manual"] = "manual") -> dict[str, Any]:
        """Save a position's, item's or location's latitude and longitude (a work order's go
        on its position). Use a photo's location only when the user has said to."""
        return run(m_for(ctx).set_coordinates, target_id, lat, lon, source)

    @tool("remove_photo", _WRITE, "Remove a photo")
    def remove_photo(photo_id: str, ctx: Context) -> dict[str, Any]:
        """Remove a photo from what it shows (it stays in the history)."""
        m = m_for(ctx)
        return run(lambda: (m.remove_photo(photo_id), {"removed": photo_id})[1])

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


def unregister() -> None:
    """Remove the maintenance tools again (for tests)."""
    from backend.mcp_server import mcp

    for name in TOOL_NAMES:
        mcp.remove_tool(name)
    TOOL_NAMES.clear()
    if "tools/list" in _ORIGINAL:
        mcp._lowlevel_server._request_handlers["tools/list"] = _ORIGINAL.pop("tools/list")
