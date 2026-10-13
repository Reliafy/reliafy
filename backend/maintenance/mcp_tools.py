"""MCP tools for Reliafy Maintenance.

Registered on the MCP server only when ``MAINTENANCE_ENABLED`` (local only for
now), so production's tool list is unchanged. They act on the caller's
personal workspace, like the other MCP tools.
"""


from typing import Annotated, Any, Literal

from pydantic import Field

TOOL_NAMES: list[str] = []


def register() -> None:
    """Add the maintenance tools to the MCP server (idempotent)."""
    if TOOL_NAMES:
        return
    from mcp.server.mcpserver import Context
    from mcp.server.mcpserver.exceptions import ToolError

    from backend.maintenance.service import Invalid, Maintenance, NotFound, summary
    from backend.mcp_server import _READ, _WRITE, _caller, _db, _reader, _tool
    from backend.routers.maintenance import get_store
    from backend.schema import RcmStudy
    from backend.services import access as access_service

    def m_for(ctx: Context) -> Maintenance:
        user = _caller(ctx)
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
        """Physical locations (sites, buildings, stores) and their parents."""
        return {"locations": run(m_for(ctx).locations)}

    # ---- building the plant ------------------------------------------------------------

    @tool("create_position", _WRITE, "Create a position")
    def create_position(name: str, ctx: Context, parent_id: str | None = None, tag: str = "",
                        position_class: str = "", description: str = "") -> dict[str, Any]:
        """A position: a job something does in the plant (the functional hierarchy),
        such as 'Hot water system' or 'Pump A'. Items are fitted to positions. Put it
        inside another position with parent_id. position_class groups like positions
        for comparison (e.g. 'Centrifugal pump')."""
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
                         on: DateText = None, notes: str = "") -> dict[str, Any]:
        """Close a work order with what was done. A replacement ends the fitted item's
        time at the position (a failure if a failure mode is named, otherwise a planned
        removal) and fits the new item; that is what builds the life data. Get the
        position's failure-mode ids from get_work_order first. Nothing is saved if any
        action is invalid."""
        return run(m_for(ctx).close_work_order, work_order_id, actions, on, notes)


def unregister() -> None:
    """Remove the maintenance tools again (for tests)."""
    from backend.mcp_server import mcp

    for name in TOOL_NAMES:
        mcp.remove_tool(name)
    TOOL_NAMES.clear()
