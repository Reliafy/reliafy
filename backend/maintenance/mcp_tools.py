"""MCP tools for Reliafy Maintenance.

Registered on the MCP server only when ``MAINTENANCE_ENABLED``, and listed only
to people who may use Maintenance. They act on the caller's personal workspace,
like the other MCP tools.

A few tools, each doing one area's work (Anthropic's guidance for tools agents
use: fewer, namespaced, well described):

* reads: ``maintenance_overview`` (start here), ``maintenance_guide`` (how-tos
  by topic), ``maintenance_get`` / ``maintenance_list`` (any kind of record, by
  ``kind``) and ``maintenance_view_photo`` (an image, which can't share the
  others' structured output);
* writes: ``maintenance_<area>(action, ...)``, one per area;
* graph queries in Cypher (#423): ``maintenance_graph_schema`` and
  ``maintenance_graph_query``, listed and answered only for the people
  ``access.graph_query_allowed`` lets run them (everyone else is told there's no
  such tool), as is the guide's ``graph`` topic.

Reads and writes are separate tools: Claude approves a tool, not an action, and
an API token's scope follows the tool's read / write annotation. Each tool's
arguments are the union of its actions'; :func:`check` holds every call to its
action's own (the tables below, which also write the tool's description).
Gating, the heavy slots and the usage log go by ``tool.action`` (see
``mcp_server._tool``'s ``call_key``).
"""


import dataclasses
import functools
from typing import Annotated, Any, Literal

from pydantic import Field

from backend.maintenance import mcp_guide
from backend.mcp_actions import Table, check, describe
from backend.mcp_actions import choice as _choice

TOOL_NAMES: list[str] = []
# The graph query tools: a narrower audience than the rest (graph_query_allowed).
GRAPH_TOOL_NAMES: list[str] = []
_ORIGINAL: dict = {}
# Calls (tool.action) that fit a non-repairable model on the server: Pro only, like the MCP
# server's other fitting tools (added to its plan gating when registered).
PRO_FIT_CALLS = ("maintenance_reliability.fit_class_model",)
# Calls that can take a while: they share the MCP server's heavy-call slots.
HEAVY_CALLS = ("maintenance_reliability.fit_class_model", "maintenance_workspace.import_history",
               "maintenance_parts.import_bom", "maintenance_parts.positions_from_structure",
               "maintenance_get.plan_economics", "maintenance_get.class_forecast", "maintenance_get.spares_plan",
               "maintenance_topology.generate_rbd", "maintenance_graph_query", "maintenance_graph_schema")


# ---- actions: what each takes -------------------------------------------------------
#
# action: (required arguments, optional arguments, what it does). "Required"
# means not null; everything else a call gives must be one of the optional ones
# (backend/mcp_actions.py checks every call and writes the descriptions).


def _d(value, default):
    return default if value is None else value


GET_KINDS: Table = {
    "position": ("id", "", """Its path, positions inside it, the item fitted now, every past fitment (with
        from_precision / to_precision for rough dates), failure modes (from RCM, by hand or ad hoc),
        class_failure_modes (seen at other positions of its class), tasks with last-done / next-due and trade,
        work orders, item_tasks (the fitted item's own), documents, parts_list (replacement part first, with
        stock, supersession, alternatives, critical minimums, notes), connections, life_data (one row per item
        fitted: days in service, c = 0 failed / 1 censored / 2 within xl..xr) and location (display, inherited,
        inherited_from; null when none is set on it or above it)."""),
    "item": ("id", "", """A serial-numbered thing: details, nameplate, notes with note_history, purchase /
        in-service / manufacture dates (precision, source), replacement cost, warranty (with a summary),
        documents, where it's fitted and where it is (location: how = fitted or placed; or last_at), every
        position it was fitted to, placements, its own positions (an engine's turbos), photos, its own tasks
        (they follow it; while_stored), work orders, measurements (its own meters), item_class (via its own or
        its part's, with attributes), part and manufacturer_entry."""),
    "work_order": ("id", "", """Subject (position, item or location), task, status, dates, trade, notes
        with note_history, close actions / close_notes or cancel_reason; for an open one the item fitted now
        and the position's failure modes (close actions name them), suggested_parts (the parts list,
        replacement first, with stock by location: pick parts from it), warranty (check coverage before paying),
        checklist (a round's: a line per position there), can_replace, and its labour / part / cost entries."""),
    "location": ("id", "", """A place in the physical tree: path, locations inside it (with counts), the
        positions there (set or inherited, here or deeper) grouped by system, each with its fitted item, direct
        or inherited_from and open work orders; items placed there (spares, repairs); counts; its own tasks and
        work orders (rounds). At most 500 positions listed (positions_truncated). For all the work there:
        maintenance_list kind work_orders with location_id."""),
    "part": ("id", "", """A catalogue part: stock by location, what supersedes it, what it's interchangeable
        with, and used_at (each position whose parts list names it: role, quantity per job, critical
        minimum); its indenture level and components (one level down)."""),
    "part_structure": ("id", "", "A part's structure as a tree, and every part below it with its total quantity "
                                 "in one (rollup)."),
    "where_used": ("id", "", "The parts a part is in (with the quantity in one), and the positions and items "
                             "using it."),
    "measurement_point": ("id", "", """Kind, source and tag, latest reading, rate (counter) or trend and the
        date it should reach an alarm limit (condition), status, recent readings (each with status ok,
        correction, voided or replaced; reading ids for maintenance_measurements void / correct)."""),
    "item_class": ("id", "", """Path, code, level, description, the classes inside it, attributes
        (inherited first, each with the class it's from), and the items and parts in it or a class inside
        it."""),
    "manufacturer": ("id", "", "Its aliases and the items and parts linked to it."),
    "conditions": ("id", "", """id = a location, position, item or connection: the conditions that apply, each
        with value, note and source (own or where it's inherited from), and those excluded."""),
    "task": ("id", "", """Why a task is what it is: where it came from (RCM), every change, and the proposals
        behind them."""),
    "class_life_data": ("id", "", """id = a position class's name. Every fitment at every position of the
        class, pooled: x = days in service, c = 0 failed or 1 censored; rough dates add xl / xr (a failure is
        then c = 2, interval censored)."""),
    "plan_economics": ("id", "interval unit horizon_years discount_rate", """id = a position class's name.
        What its replacement plan costs a year: the current plan, the best interval, running to failure and
        (with interval) a what-if, each with its net present cost over horizon_years (default 10) at
        discount_rate (default 0.07). Needs the class's fitted model and costs. unit: days, weeks, months
        (default), years."""),
    "class_forecast": ("id", "period periods service_level lead_time_days review_days", """id = a position
        class's name. Its failure forecast from the register, with each spare's stock levels (guide topic
        decide)."""),
    "spares_plan": ("id", "period periods service_level lead_time_days review_days", """id = a position class's
        name. Each spare's stock levels per period, and the risk at any stock."""),
    "impact": ("id", "", """id = a position. If it fails, what loses its supply downstream (through
        connections), and whether redundancy covers it."""),
    "photo_link": ("id", "", """id = a link_id from maintenance_attachments photo_link. The photos added
        through it so far, and any location a photo carried with the user's answer (saved / declined / null =
        not answered). Unanswered: ask the user before set_coordinates; never save it unasked."""),
    "document": ("id", "", """A document on an item, position or class. A stored PDF has open_url and
        download_url: no sign-in, for 15 minutes; read it again for new ones."""),
    "manufacturer_match": ("text", "", """Which register entry a maker as written ('K.S.B.', 'KSB AG') is:
        by name or alias, case, accents, punctuation and company form (AG, Ltd) aside. match is null when none
        is certain; candidates are near misses to ask the user about. Use before maintenance_manufacturers
        create."""),
}

LIST_KINDS: Table = {
    "work_orders": ("", "status location_id", """Newest first, each with subject, position (where the work
        is) and location. status 'open' (every one not done: open, planned, in_progress, waiting) or one
        status exactly (closed, cancelled...). location_id: only work in that area (positions there, set or
        inherited, items there now, the location itself)."""),
    "items": ("", "item_class_id manufacturer_id", """Every item with the position it's fitted to and where
        it is (location: fitted or placed; or last_at), item_class and manufacturer_entry. item_class_id (that
        class or one inside it) and manufacturer_id filter; 'none' for items with none."""),
    "parts": ("", "item_class_id manufacturer_id", """The catalogue: stock by location, reorder points (low =
        at or below), a year's use and months of cover, used_at, critical_short, item_class and
        manufacturer_entry. Filters as items."""),
    "locations": ("", "", """The physical tree, each with positions (located there, set or inherited) and
        items (placed there), and all_positions / all_items counting the locations inside it."""),
    "places": ("", "", """The assets: each top-level location with the positions, items, open work orders
        and tasks due in 30 days inside it; not_placed: the same for positions with no location."""),
    "position_classes": ("", "", """Each position class with its positions, fitments and failures, costs,
        default replacement cost and document links."""),
    "item_classes": ("", "format", """format tree (default): the item class tree with code, level,
        attributes and item / part counts (empty = not used). format json or csv: the taxonomy as
        maintenance_item_classes import reads it."""),
    "manufacturers": ("", "", "The manufacturer register: each maker, its aliases and how many items and parts."),
    "conditions": ("", "format", """The condition register as a tree, with where each is applied (format json or
        csv: for import)."""),
    "photos": ("target_id", "", "The photos of a position, location, item or work order (ids, captions, dates)."),
    "proposals": ("", "status", """Changes the non-repairable models propose (a task's interval, or retiring a task),
        each with its reason; status pending (default), accepted, rejected, superseded or all. Show them to the
        user and let them decide (maintenance_proposals)."""),
    "spares_cover": ("", "include_unlisted", """Where the spares don't cover the plant: short (critical spares
        below their position's minimum, counting supersessions and alternatives in every store), no_spare
        (positions whose critical replacement part has none usable); include_unlisted adds
        without_parts_list."""),
}

POSITIONS: Table = {
    "create": ("name", "parent_id tag position_class description location_id", """A position: the job something
        does ('Hot water system', 'MCC-3', 'Pump A'). parent_id: inside another position, or inside an item (a
        position that travels with it, like an engine's turbo). position_class: like positions to compare and
        pool. location_id: where it physically is; leave it out to inherit its parent's. Returns the
        position."""),
    "update": ("position_id", "name tag position_class description parent_id move_to_top_level location_id "
               "clear_location", """Rename, change tag / class / description, move it (parent_id, or
        move_to_top_level true), set where it is (location_id: positions inside without their own follow) or
        clear_location true to inherit its parent's again."""),
    "copy": ("position_id name", "parent_id", """Copy a position and everything inside it (positions, failure
        modes, tasks, parts lists, locations set on them; not items, stock or work orders) under a new name.
        Repeat it to build many like structures; then update the copy's location_id if it's elsewhere."""),
    "retire": ("position_id", "reason", """Take it out of the plant (kept in the history). Nothing fitted, no
        position inside it in use, no work order open."""),
    "from_rcm": ("study_id", "parent_id", """A new position named for an RCM study's system, with its failure
        modes and a task for every decision with an interval (list kind rcm_studies / rcm create)."""),
    "apply_rcm": ("position_id study_id", "", """Bring a study's failure modes and tasks onto an existing
        position; again later adds what's new and updates changed tasks."""),
    "adopt_placements": ("", "dry_run", """One-off tidy-up for a workspace that placed fitted items at
        locations: each such placement becomes its position's location where it has none. dry_run (default
        true) lists the changes: show them, then run with dry_run false."""),
}

FITMENTS: Table = {
    "fit": ("position_id", "item_id item_name serial part_number manufacturer model part_id on from_precision",
            """Fit
        an item to an empty position: an existing one (item_id) or a new one (item_name with serial, part
        number, manufacturer, model; or part_id, the catalogue make and model, which fills in what isn't given). on: the
        date it went in, rough if need be ('2022', or a day with from_precision 'estimated'). A new item renews
        the position's tasks. To replace an item, close a work order with a replace action instead."""),
    "remove": ("position_id", "on reason failure_mode_id failure_mode_text to_precision", """Take the fitted
        item out with no work order (a correction). If it failed, name how: failure_mode_id, or
        failure_mode_text in words (a new ad-hoc mode if the position has none of that name); a mode with no
        reason is a failure, no mode a planned removal. reason: planned, failure or other."""),
    "move": ("item_id position_id", "on", """Move an item from wherever it's fitted to an empty position,
        keeping its one history: a rotable going round, a pump swapped to standby."""),
    "add_past": ("position_id start end", "reason item_id item_name serial part_number manufacturer model "
                 "failure_mode_id failure_mode_text from_precision to_precision note", """Put an earlier item
        into a position's history (migrating records): in on start, out on end. reason failure (name the mode),
        planned or other. Must not overlap another fitment at the position or of the item. Returns the
        position."""),
    "void": ("fitment_id", "reason", """Strike out a fitment recorded by mistake (wrong item or position): it
        leaves the history and life data (the event log keeps it). reason: why. Fitment ids are on the
        position (fitments, life_data)."""),
    "correct": ("fitment_id", "start end from_precision to_precision", """Correct the date an item went in
        (start) or came out (end), and how well each is known. A precision alone re-reads the date there
        (from_precision year turns 2022-07-01 into 2022)."""),
}

ITEMS: Table = {
    "update": ("item_id", "name serial part_number manufacturer model notes append_note nameplate purchase_date "
               "in_service_date manufacture_date replacement_cost warranty clear", """Change an item's details.
        After reading a nameplate: make in manufacturer, the model, the serial, everything else on the plate in
        nameplate. append_note adds a dated line (notes replaces the whole note). Dates, replacement cost and
        warranty go in their own fields; clear removes them."""),
    "place": ("item_id location_id", "on", """Where an item that ISN'T fitted is: a spare in a store, one away at
        a repairer. A fitted item is refused: it is where its position is (set the position's location)."""),
    "set_part": ("item_id part_id", "", """Link an item to its catalogue part (make and model): it then takes
        the part's item class and manufacturer unless it has its own. part_id 'none' unlinks it."""),
    "set_attributes": ("item_id values", "", """Fill in its structured attributes, checked against its item
        class (its own, else its part's; maintenance_get kind item lists them). Anything else from the
        nameplate goes in update's nameplate."""),
}

FAILURE_MODES: Table = {
    "add": ("position_id text", "function failure consequence", """A failure mode on a position without RCM:
        how it fails ('Bearing worn'), optionally the function, the functional failure ('No flow') and the
        consequence. Failures and tasks then name it by id."""),
    "update": ("failure_mode_id", "text function failure consequence", """Edit one added by hand or typed in at
        a failure (editing an ad-hoc mode confirms it). An RCM study's modes change in the study."""),
    "merge": ("failure_mode_id into_failure_mode_id", "", """Fold a mode into another on the same position (a
        duplicate, an ad-hoc one): its failures, findings and tasks move across. To link an ad-hoc mode to an
        RCM study's, apply the study, then merge into the study's. Returns the position."""),
}

TASKS: Table = {
    "create": ("name interval", "position_id item_id location_id unit outcome also_interval also_unit point_id "
               "instructions checklist source reference failure_mode_id last_done trade while_stored "
               "include_positions", """A scheduled task without an RCM study, on exactly one subject:
        position_id (the job: lubricate the pump), item_id (follows the serial number: calibration,
        certification, a rotable's overhaul, preserving a stored spare) or location_id (a round; calendar units
        only). unit (default months): days, weeks, months, years, or hours / cycles / km from a counter
        (point_id). also_interval + also_unit: whichever comes first. outcome: fixed_interval, failure_finding,
        on_condition or none. source: manual (default), oem, statutory, other, with reference.
        failure_mode_id: a position's mode. last_done if known. trade: who may do it. while_stored (item):
        run or pause. include_positions (location): list the positions there. maintenance_guide topic plan has
        examples."""),
    "update": ("task_id", "name interval unit also_interval also_unit point_id instructions checklist "
               "failure_mode_id unlink_failure_mode source reference outcome clear_outcome trade while_stored "
               "include_positions", """Rename it or change its interval, second limit (also_interval 0 removes
        it), counter, instructions, checklist, trade ('' clears), failure mode link (unlink_failure_mode
        true removes it), source / reference / outcome (clear_outcome true) of a hand-made task, while_stored
        or include_positions. Its subject can't change: retire it and create another."""),
    "retire": ("task_id", "reason", "Stop scheduling it (it stays in the history)."),
    "set_last_done": ("task_id on", "", """When it was last done before it was tracked here, so its next due
        date counts from then."""),
}

PROPOSALS: Table = {
    "accept": ("proposal_id", "note", """Apply a change the non-repairable models proposed (maintenance_list kind
        proposals). Only when the user says so."""),
    "reject": ("proposal_id", "note", "Turn a proposed change down, optionally saying why."),
}

WORK_ORDERS: Table = {
    "open": ("title", "position_id item_id location_id type task_id due notes trade include_positions", """A
        work order on exactly one of position_id (the job and whatever's fitted), item_id (follows the serial
        number) or location_id (a round); with task_id alone, on the task's subject. type: corrective (default),
        preventive, inspection, other. trade: the licence or competency it needs (a task's by default).
        include_positions: a location's checklist lists the positions there. Flags warranty."""),
    "update": ("work_order_id", "title due notes type assignee planned_for append_note trade", """Change an open
        one's title, due ('' clears), notes (replaces the whole note), type, assignee, planned_for or trade
        ('' clears). append_note adds a dated line, also on closed and cancelled ones."""),
    "status": ("work_order_id status", "note", "Move an open one along: planned, in_progress, waiting, or open."),
    "close": ("work_order_id", "actions on notes readings", """Close it with what was done (actions, in order).
        A replace ends the fitted item's time at the position (a failure if a failure mode is named, else
        planned) and fits the new one: that builds the life data. Get the failure-mode ids from maintenance_get
        kind work_order first; if none fits, use failure_mode_text, never a failure as planned. An item's work
        order acts at the position it's fitted to now; a location's (a round) takes repair, inspect and other
        only. Nothing is saved if any action is invalid."""),
    "cancel": ("work_order_id", "reason", """Cancel one that won't be done (a duplicate, raised by mistake);
        reason kept as cancel_reason. Work that was done: close."""),
    "generate": ("", "horizon_days", """Open a preventive work order for every task due within horizon_days
        (default 30, at most 366) that has none open, on the task's subject; skipped: any it couldn't, and why."""),
    "labour": ("work_order_id hours", "who rate on note", "Hours worked, by whom, at an hourly rate if known."),
    "part_used": ("work_order_id", "part quantity unit_cost part_number note part_id from_location_id", """A part
        or consumable used: free text (part) or a catalogue part (part_id, from the work order's
        suggested_parts first; its cost fills in), taken from stock at from_location_id if given. quantity
        default 1."""),
    "cost": ("work_order_id description amount", "", "Any other cost (a contractor, hire, call-out)."),
    "remove_entry": ("entry_id", "", "Remove a labour, part or cost entry made by mistake (ids on the work order)."),
    "check": ("work_order_id index", "done", "Tick (done true, default) or untick a checklist line, numbered from 0."),
}

MEASUREMENTS: Table = {
    "add_point": ("", "position_id item_id name kind unit source tag alarm_above alarm_below", """Something
        measured on a position (position_id) or an item (item_id: a meter it carries; its tasks by use go by
        it). kind counter (default condition): use, only goes up (run hours, cycles, km); condition: vibration,
        temperature, wear, with alarm limits (a reading past one opens an inspection). source manual (default:
        someone reads it) or automated (a feed sends readings under tag to POST /api/ingest/maintenance/readings
        with an ingest-scope token)."""),
    "update_point": ("point_id", "name alarm_above alarm_below clear_alarm_above clear_alarm_below tag", """Rename
        a point, set or clear its alarm limits, or change an automated point's tag."""),
    "record": ("point_id value", "at on note precision", """A manual reading (the hour meter says 12,340).
        Counters only go up. at is when it was read, to the minute or finer (or on, a day); a time of day orders
        readings taken the same day. Returns the point: latest, rate or trend, status, any alarm work order."""),
    "void": ("reading_id reason", "", """Strike out a reading entered by mistake (a duplicate, the wrong meter),
        saying why; rates, due dates and alarms leave it out. Returns the point."""),
    "correct": ("reading_id reason", "value at on precision note", """Correct a reading's value (a typo),
        time (at, or on for a day) or note: the original is struck out and the correction recorded in its place.
        Returns the point."""),
}

LOCATIONS: Table = {
    "create": ("name", "parent_id description", """A physical place (site, area, building, room, substation,
        store), optionally inside another. Don't mirror the positions here: make the places, then give positions
        a location_id."""),
    "update": ("location_id", "name description parent_id move_to_top_level", """Rename it, change its
        description, or move it inside another (parent_id) or to the top level."""),
}

PARTS: Table = {
    "create": ("part_number name", "manufacturer unit unit_cost notes item_class_id manufacturer_id", """A part in
        the catalogue, by part number (unique): a spare (a bearing, a seal kit) or a make and model of equipment
        (part_number = the model number). item_class_id: what kind of thing it is; manufacturer_id: its maker in
        the register (manufacturer_match first). unit default 'each'."""),
    "stock": ("part_id location_id quantity", "reason on",
              "Receive (positive quantity) or issue / write off (negative) at a location."),
    "reorder": ("part_id location_id reorder_point", "",
                "Stock at or below reorder_point at the location counts as low."),
    "link": ("part_id other_part_id", "relation", """part_id is superseded_by other_part_id, or the two are
        interchangeable (default)."""),
    "add_to_position": ("position_id part_id", "role quantity critical min_on_hand notes", """Put a catalogue part
        on a position's parts list (its bill of materials). role: replacement (replaces what's fitted, one per
        position), component (default: used in its maintenance) or consumable. quantity: per job (default 1).
        critical true: a critical spare, min_on_hand the least to keep (default one job's worth). notes:
        compatibility ('fits from serial 4000 on'). Returns the parts list."""),
    "update": ("part_id", "name manufacturer unit unit_cost notes lead_time_days service_level repairable "
               "turnaround_days", """Change a catalogue part. For its stock levels: lead_time_days to replenish,
        service_level (chance of no stock-out to plan for, e.g. 0.95), repairable with turnaround_days (repaired
        and sent back)."""),
    "update_on_position": ("listing_id", "role quantity critical min_on_hand notes", """Change a parts-list entry
        (ids in the position's parts_list); critical false drops the minimum. For a different part, remove it and
        add the other."""),
    "remove_from_position": ("listing_id", "",
                             "Take an entry off a position's parts list (the part stays in the catalogue)."),
    # Product structure (#435): how-to in the guide's structure topic.
    "add_component": ("part_id component_id", "quantity ref",
                      "Put component_id in part_id's structure (quantity in one, default 1); loops are refused."),
    "update_component": ("part_id component_id", "quantity ref", "Change a structure line's quantity or ref."),
    "remove_component": ("part_id component_id", "", "Take component_id out of part_id's structure."),
    "set_level": ("part_id", "level", "Set a part's indenture level from the workspace's list ('' clears it)."),
    "set_levels": ("levels", "renamed", "Replace the workspace's indenture level list, top first."),
    "import_bom": ("rows", "dry_run", "Import a BOM, one row per parent-child line (dry_run default true)."),
    "positions_from_structure": ("part_id", "position_id levels dry_run",
                                 "Make positions from a part's structure under position_id (dry_run default true)."),
}

STRUCTURE_ACTIONS = ("add_component", "update_component", "remove_component", "set_level", "set_levels",
                     "import_bom", "positions_from_structure")

RELIABILITY: Table = {
    "set_class_costs": ("position_class", "planned_cost failure_cost availability_target replacement_cost "
                        "clear_replacement_cost", """What a planned replacement and a failure cost for a position
        class (same currency), and the availability a hidden function must reach (e.g. 0.99): proposed
        intervals are optimised against them. replacement_cost: the default for items with none of their
        own. Returns the class."""),
    "fit_class_model": ("position_class", "distribution", """Pro. Fit a life distribution (weibull default, best,
        lognormal, exponential, gamma) to every fitment of the class's positions, save it as a model and
        propose task intervals from it and the costs. Needs at least 2 failures (exponential: 1, a constant
        failure rate while there's little history). Then generate_rbd uses it for the class's blocks."""),
}

TOPOLOGY: Table = {
    "connect": ("from_id to_id", "kind medium name rating realised_by", """Something passes from one position to
        another (water tank -> pump, 240 V switchboard -> motor). kind: flow (default), electrical, mechanical,
        signal, data, other. realised_by: a position for the connection itself when it's maintainable (a hose, a
        cable)."""),
    "disconnect": ("interface_id", "", "Remove a connection (its id is in the position's connections)."),
    "create_group": ("member_ids", "name k mode standby", """Positions doing the same job where k of them are
        enough (two pumps, either will do: k = 1, the default; duty and standby: mode standby). Record it while
        building the register: generate_rbd and impact depend on it. mode active (default) or standby (the others
        wait; standby cold, warm or hot)."""),
    "update_group": ("group_id", "name k mode standby add remove",
                     "Rename it, change k or mode, add / remove members."),
    "set_duty": ("group_id position_id", "", "Which member of a standby group runs now (a duty / standby swap)."),
    "generate_rbd": ("position_id", "", """Generate (or regenerate) an RBD for a system position from the
        positions inside it: connections wire the blocks, groups become k of n, blocks take their class's
        fitted model (placeholders otherwise, listed in notes). Saved as a normal RBD: rbd_analysis analyze."""),
}

ITEM_CLASSES: Table = {
    "create": ("name", "parent_id code level description attributes", """Add a kind of thing to the item class
        tree, inside parent_id or at the top. code: the user's own (never invent one). level: their name for
        it (class, type, subunit). Reuse a class that's there rather than make a near duplicate."""),
    "update": ("item_class_id", "name code level description parent_id move_to_top_level", """Rename it or
        change code, level or description, or move it (never inside itself); its items, parts and classes go
        with it."""),
    "set_attributes": ("item_class_id attributes", "", """Replace the class's OWN attributes (the whole list).
        Values items have for one taken off stay on them."""),
    "retire": ("item_class_id", "reason", "Take an empty class out of use (kept in the history)."),
    "assign": ("target_id item_class_id", "", """Give an item or a catalogue part a class; item_class_id 'none'
        takes it away. Prefer the part: its items follow."""),
    "import": ("", "classes csv dry_run source", """Load a taxonomy the user has (their company's, or a standard
        they hold a licence for; never type one from memory: ISO 14224 and OREDA are copyrighted) as classes
        (JSON) or csv, one of them. Matched by path, so it can run again; conflicts are listed and left alone.
        dry_run (default true) reports what would change; nothing is written if any row is wrong."""),
    "load_starter": ("", "dry_run", """Reliafy's own starter taxonomy (pumps, motors, valves, instruments, HVAC
        and more, with typical attributes). Only when the user asks. dry_run default true."""),
    "create_condition": ("name", "parent_id kind unit code description",
                         "Add a condition to the register (maintenance_guide topic conditions)."),
    "update_condition": ("condition_id", "name kind unit code description parent_id move_to_top_level",
                         "Rename, change or move a condition."),
    "retire_condition": ("condition_id", "reason", "Retire a condition: it stops applying anywhere."),
    "apply_condition": ("target_id condition_id", "value note",
                        "Record that a location, position, item or connection is exposed to it."),
    "exclude_condition": ("target_id condition_id", "note", "Stop an inherited condition there and below."),
    "remove_condition": ("target_id condition_id", "", "Take a condition or exclusion off the target."),
    "import_conditions": ("", "conditions csv dry_run source", "Load a register by path, like import."),
}

MANUFACTURERS: Table = {
    "create": ("name", "aliases", """Add a maker with the other names it goes by. Refused if a name is already
        another entry's: add an alias there instead."""),
    "update": ("manufacturer_id", "name add_aliases remove_aliases", "Rename it, or add or take off aliases."),
    "merge": ("manufacturer_id into_manufacturer_id", "", """Fold a duplicate into another: its items and parts
        move, its names become aliases. Confirm with the user first."""),
    "link": ("target_id manufacturer_id", "", """Link an item or (preferably) a part to its maker; manufacturer_id
        'none' unlinks. Its typed manufacturer text stays (or takes the register's name if it had none)."""),
    "link_by_name": ("", "dry_run", """Link every item and part whose typed manufacturer matches an entry and has
        no link yet; unmatched lists the texts that matched nothing, most used first. dry_run default true."""),
}

ATTACHMENTS: Table = {
    "photo_link": ("target_id", "caption", """A link for the user to add up to 20 photos of a position, location,
        item or work order from a phone in the next 30 minutes, with no sign-in. Give them the url (you can't
        send a photo file yourself). Then maintenance_get kind photo_link, and maintenance_view_photo."""),
    "set_coordinates": ("target_id lat lon", "source", """Save a position's, item's or location's latitude and
        longitude (a work order's go on its position). source manual (default) or photo: use a photo's location
        only when the user has said to."""),
    "remove_photo": ("photo_id", "", "Remove a photo (the history keeps that it was there; the image is deleted)."),
    "link_photo": ("photo_id target_id", "", """Show a photo on another position, location, item or work order too
        (a nameplate from a work order, on its position)."""),
    "unlink_photo": ("photo_id target_id", "", "Take a photo off one place it shows (not its last: move or remove it)."),
    "move_photo": ("photo_id target_id", "from_id", "Move a photo to target_id: off from_id, or else off everywhere else."),
    "add_document": ("", "url upload_id target_id position_class title kind", """Add a document (a manual,
        datasheet, invoice, drawing, certificate) to an item or position (target_id), or to a position class
        (one datasheet every pump of that model shares): a link (url, http(s)) or a PDF to keep here (upload_id
        from uploads create, purpose document). Use this rather than links in notes. kind: manual, datasheet,
        invoice, drawing, certificate, other (default)."""),
    "remove_document": ("document_id", "",
                        "Remove a document (ids in the documents on the item, position or class); a kept PDF is "
                        "deleted."),
}

WORKSPACE: Table = {
    "set_time_zone": ("time_zone", "", """Where the workspace is, so today, due dates and overdue follow its
        local calendar: an IANA name ('Australia/Brisbane', 'Europe/London'); '' clears it (UTC). Ask the user
        rather than guessing."""),
    "import_history": ("rows", "dry_run", """Bring an existing history in: positions (made from their paths),
        items, when they were fitted and removed and whether they failed. Every row is checked first; with any
        error nothing is written. dry_run (default true) reports what would be made: show it, then run with
        dry_run false. At most 5000 rows; for a file, the user can import it on the Maintenance page."""),
}


# Each tool that does several things: the argument choosing what, and its table.
TABLES: dict[str, tuple[str, Table]] = {
    "maintenance_get": ("kind", GET_KINDS), "maintenance_list": ("kind", LIST_KINDS),
    "maintenance_positions": ("action", POSITIONS), "maintenance_fitments": ("action", FITMENTS),
    "maintenance_items": ("action", ITEMS), "maintenance_failure_modes": ("action", FAILURE_MODES),
    "maintenance_tasks": ("action", TASKS), "maintenance_proposals": ("action", PROPOSALS),
    "maintenance_work_orders": ("action", WORK_ORDERS), "maintenance_measurements": ("action", MEASUREMENTS),
    "maintenance_locations": ("action", LOCATIONS), "maintenance_parts": ("action", PARTS),
    "maintenance_reliability": ("action", RELIABILITY), "maintenance_topology": ("action", TOPOLOGY),
    "maintenance_item_classes": ("action", ITEM_CLASSES), "maintenance_manufacturers": ("action", MANUFACTURERS),
    "maintenance_attachments": ("action", ATTACHMENTS), "maintenance_workspace": ("action", WORKSPACE),
}


def register() -> None:
    """Add the maintenance tools to the MCP server (idempotent)."""
    if TOOL_NAMES:
        return
    from mcp.server.mcpserver import Context, Image
    from mcp.server.mcpserver.exceptions import ToolError

    from backend import config, mcp_server
    from backend.maintenance import bom, forecast, importer, loop, rbd_derive, taxonomy
    from backend.maintenance import conditions as register_io
    from backend.maintenance import graph_cypher
    from backend.maintenance.access import allowed, graph_query_allowed
    from backend.maintenance.service import Invalid, Maintenance, NotFound, summary
    from backend.mcp_server import _READ, _WRITE, _caller, _db, _reader, _tool, mcp
    from backend.routers.maintenance import (document_link, get_store, ingest_document, link_payload, photo_links,
                                             remove_document, remove_photo, served_photo)
    from backend.schema import RcmStudy
    from backend.services import access as access_service
    from backend.services import time_zones

    def m_for(ctx: Context) -> Maintenance:
        user = _caller(ctx)
        if not allowed(user):
            raise ToolError("Reliafy Maintenance isn't available on your account yet.")
        return Maintenance(get_store(), user["uid"], user["uid"], time_zone=time_zones.of_owner(_db(), user["uid"]))

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

    def tool(name, annotations, title, table: Table | None = None, selector: str = "action"):
        """Register one tool; with a table, its description lists the actions and
        each call is keyed tool.action for gating, heavy slots and the usage log."""
        TOOL_NAMES.append(name)

        def decorator(fn):
            if table is None:
                return _tool(name, annotations, title)(fn)
            fn.__doc__ = describe(fn.__doc__ or "", selector, table)

            @functools.wraps(fn)
            def checked(*args, **kwargs):
                check(selector, kwargs[selector], table,
                      {k: v for k, v in kwargs.items() if k != selector and not isinstance(v, Context)})
                return fn(*args, **kwargs)
            return _tool(name, annotations, title, call_key=lambda kwargs: f"{name}.{kwargs[selector]}")(checked)
        return decorator

    def base_url(ctx: Context) -> str:
        return config.PUBLIC_BASE_URL or str(ctx.request_context.request.base_url).rstrip("/")

    def none_is_null(value):
        """'none' (or '') for an id that can be taken away: null."""
        return None if value in ("none", "") else value

    DateText = Annotated[str | None, Field(description=(
        "A date like 2026-10-13. Default: today (the workspace's, in its time zone)."))]
    Precision = Literal["exact", "month", "year", "estimated"]
    RoughDate = Annotated[str | None, Field(description=(
        "A date like 2026-10-13, or 2022-03 / 2022 when only the month or year is known "
        "(the precision follows). Default: today (the workspace's)."))]
    ItemDate = Annotated[dict[str, str] | None, Field(description=(
        "{date: '2022' | '2022-03' | '2022-03-15', precision?: exact|month|year|estimated (from the "
        "date's form if left out; estimated = a guess, e.g. 'about 6 months ago'), source?: where it "
        "came from, e.g. 'receipt', 'serial date code', \"owner's estimate\"}. Never invent a day: give "
        "'2022' with precision year rather than 2022-07-01."))]
    ReplacementCost = Annotated[dict[str, Any] | None, Field(description=(
        "{amount, currency?: 3-letter code (AUD), source?: e.g. 'supplier quote', as_of?: date of the "
        "price (default today)}."))]
    WholeNote = Annotated[str | None, Field(description="Replaces the WHOLE note. To add to it, use append_note.")]
    AppendNote = Annotated[str | None, Field(description=(
        "A line to add to the end of the notes, dated today; the rest is kept."))]

    # ---- reading ---------------------------------------------------------------------

    @tool("maintenance_overview", _READ, "Maintenance overview")
    def maintenance_overview(ctx: Context) -> dict[str, Any]:
        """The maintenance workspace at a glance: counts, the tree of positions (the functional
        hierarchy, each with what's fitted, its task count, next due date and open work orders),
        tasks due in the next 30 days, open work orders, critical_spares (critical spares below the
        minimum their position keeps on hand), time_zone (IANA name; null = UTC, unset) and today (the
        workspace's: a date left out anywhere defaults to it). Start here; use the ids with
        maintenance_get and the other maintenance tools.

        The model in brief: a position is a functional location (SAP's FLOC): the slot, by what it
        does (Electrical > MCC-3 > Feeder 12). A location is a physical place (Site > Substation 2;
        Store A). The two are separate trees, so build each once: never copy one into the other; link
        them with a position's location_id. An item fitted to a position is where its position is and
        needs no placement. Tasks and work orders are on a position, an item or a location (subject).
        For how-tos (building the register, planning, running work, learning from failures, the data
        rules) read maintenance_guide."""
        m = m_for(ctx)
        return run(lambda: {"summary": summary(m), "time_zone": m.time_zone, "today": m.today(),
                            "tree": m.tree(), "due": m.due_tasks(30),
                            "open_work_orders": m.work_orders("open"), "critical_spares": m.critical_spares_short()})

    # "graph" is a topic only for the people who may run graph queries: listed
    # tools hide it from everyone else's schema (list_tools below), and the call
    # refuses it.
    Topic = Literal[(*mcp_guide.TOPICS, "graph")]  # type: ignore[valid-type]

    @tool("maintenance_guide", _READ, "How to use Reliafy Maintenance")
    def maintenance_guide(ctx: Context, topic: Annotated[Topic | None, Field(description=(
            "The how-to to read; leave it out for the list of topics."))] = None) -> dict[str, Any]:
        """Short how-tos for Reliafy Maintenance, one topic at a time, naming the tools and actions
        to use. Topics: model (the four structures: positions, locations, classes, connections, and the
        items moving through them), register (locations, positions, fitting items, the nameplate flow),
        plan (RCM or tasks directly; tasks on a position, an item or a location), run (generate and
        close work orders: failure modes, parts, labour, corrections), learn (class life data, fitting a
        class model, proposals the user accepts), decide (plan economics, generated RBDs, impact, spares
        cover), data (rough dates, placement, time zone, notes, dry runs), classes (position classes vs
        item classes, taxonomies, manufacturers), conditions (what things are exposed to, inherited),
        structure (parts made of parts: BOMs, indenture levels, where used).
        Read the one you need before a task you haven't done here yet."""
        m_for(ctx)  # Maintenance is on for this account
        pages = dict(mcp_guide.TOPICS)
        if graph_query_allowed(_caller(ctx)):
            pages["graph"] = mcp_guide.GRAPH_TOPIC
        topics = {name: summary_ for name, (summary_, _) in pages.items()}
        if topic is None:
            return {"topics": topics}
        if topic not in pages:
            raise ToolError(f"Unknown topic {topic!r}: the topics are {', '.join(pages)}.")
        return {"topic": topic, "guide": pages[topic][1], "topics": topics}

    @tool("maintenance_get", _READ, "Read one maintenance record", GET_KINDS, "kind")
    def maintenance_get(kind: _choice(GET_KINDS), ctx: Context,
                        id: Annotated[str | None, Field(description=(
                            "The record's id (for class_life_data and plan_economics: the position class's "
                            "name)."))] = None,
                        text: Annotated[str | None, Field(description=(
                            "manufacturer_match: the maker as written."))] = None,
                        interval: Annotated[float | None, Field(
                            description="plan_economics: a what-if interval.")] = None,
                        unit: Literal["days", "weeks", "months", "years"] | None = None,
                        horizon_years: float | None = None, discount_rate: float | None = None,
                        period: Literal["month", "quarter", "year"] | None = None,
                        periods: int | None = None,
                        service_level: Annotated[float | None, Field(description=(
                            "Chance of no stock-out for every spare (default: each part's own, else 0.95)."))]
                        = None,
                        lead_time_days: Annotated[float | None, Field(description=(
                            "A lead time for every spare (default: each part's own, else 30)."))] = None,
                        review_days: Annotated[float | None, Field(description=(
                            "How often stock is checked (default 0)."))] = None) -> dict[str, Any]:
        """One maintenance record, or one answer about a record, by kind and id. Ids come from
        maintenance_overview, maintenance_list and the records themselves."""
        m = m_for(ctx)
        rid = id
        if kind == "photo_link":
            doc = photo_links().get(rid, org=m.org)
            if doc is None:
                raise ToolError("Photo link not found.")
            return photo_links().public(doc)
        if kind == "plan_economics":
            return run(loop.economics, m, rid, interval, _d(unit, "months"), _d(horizon_years, 10),
                       _d(discount_rate, 0.07))
        if kind in ("class_forecast", "spares_plan"):
            def go():
                fc = forecast.class_forecast(m, rid, _d(period, "month"), _d(periods, 12), service_level,
                                             lead_time_days, review_days)
                return forecast.spares_plan(fc) if kind == "spares_plan" else forecast.without_plans(fc)
            return run(go)
        if kind == "manufacturer_match":
            return run(m.match_manufacturer, text)
        if kind == "document":
            return run(document_link, base_url(ctx), m, rid)
        read = {"position": m.position, "item": m.item, "work_order": m.work_order, "location": m.location,
                "part": m.part, "measurement_point": m.point, "item_class": m.item_class,
                "manufacturer": m.manufacturer, "task": m.explain_task, "class_life_data": m.class_life_data,
                "impact": m.impact, "conditions": m.conditions_of, "part_structure": m.part_structure,
                "where_used": m.where_used}[kind]
        return run(read, rid)

    @tool("maintenance_list", _READ, "List maintenance records", LIST_KINDS, "kind")
    def maintenance_list(kind: _choice(LIST_KINDS), ctx: Context,
                         status: Annotated[Literal["open", "planned", "in_progress", "waiting", "closed", "cancelled",
                                                   "pending", "accepted", "rejected", "superseded", "all"] | None,
                                           Field(description=(
                                               "work_orders: open (every one not done), planned, in_progress, "
                                               "waiting, closed or cancelled. proposals: pending (default), "
                                               "accepted, rejected, superseded or all."))] = None,
                         location_id: str | None = None,
                         item_class_id: Annotated[str | None, Field(description=(
                             "Only this item class or one inside it; 'none' for those with no class."))] = None,
                         manufacturer_id: Annotated[str | None, Field(description=(
                             "Only this manufacturer's; 'none' for those with no manufacturer linked."))] = None,
                         target_id: str | None = None, include_unlisted: bool | None = None,
                         format: Literal["tree", "json", "csv"] | None = None) -> dict[str, Any]:
        """Lists and reports across the maintenance workspace, by kind."""
        m = m_for(ctx)
        statuses = {"work_orders": ("open", "planned", "in_progress", "waiting", "closed", "cancelled"),
                    "proposals": ("pending", "accepted", "rejected", "superseded", "all")}
        if status is not None and status not in statuses[kind]:
            raise ToolError(f"kind '{kind}' takes status {', '.join(statuses[kind])}.")
        if kind == "work_orders":
            return {"work_orders": run(m.work_orders, status, location_id)}
        if kind == "items":
            return {"items": run(m.items, item_class_id, manufacturer_id)}
        if kind == "parts":
            return {"parts": run(m.parts, item_class_id, manufacturer_id)}
        if kind == "locations":
            return {"tree": run(m.location_tree)}
        if kind == "places":
            found = run(m.places)
            # Counts only: the app's filter needs the ids, an agent can find them by name.
            found["not_placed"].pop("position_ids", None)
            return found
        if kind == "position_classes":
            return {"classes": run(m.position_classes)}
        if kind == "item_classes":
            if format in (None, "tree"):
                return run(m.item_class_tree)
            return run(lambda: taxonomy.export_json(m) if format == "json" else {"csv": taxonomy.export_csv(m)})
        if kind == "manufacturers":
            return {"manufacturers": run(m.manufacturers)}
        if kind == "conditions":
            if format in (None, "tree"):
                return run(m.condition_tree)
            return run(lambda: register_io.export_json(m) if format == "json" else {"csv": register_io.export_csv(m)})
        if kind == "photos":
            return run(lambda: {"target": target_id, "photos": (m.photo_target(target_id), m.photos_of(target_id))[1]})
        if kind == "proposals":
            status_ = _d(status, "pending")
            return {"proposals": run(m.proposals, None if status_ == "all" else status_)}
        return run(m.spares_cover, bool(include_unlisted))

    @tool("maintenance_view_photo", _READ, "Look at a maintenance photo")
    def maintenance_view_photo(photo_id: str, ctx: Context, size: Literal["full", "thumb"] = "full") -> Image:
        """The photo itself, to look at: read a nameplate (make, model, serial, ratings; then
        maintenance_items update / set_attributes) or check a condition. 'full' is up to 1600 px;
        'thumb' 400 px. Photo ids: maintenance_list kind photos, or maintenance_get kind photo_link."""
        m = m_for(ctx)
        run(m.photo, photo_id)
        data = served_photo(m, photo_id, size)
        if data is None:
            raise ToolError("That photo was removed, or its file is missing.")
        return Image(data=data, format="jpeg")

    # ---- graph queries in Cypher (#423): only for graph_query_allowed -------------------

    def graph_tool(name: str, title: str):
        GRAPH_TOOL_NAMES.append(name)
        return _tool(name, _READ, title)

    def graph_caller(ctx: Context, name: str) -> tuple[dict, list[str]]:
        """The caller, and the workspaces they may read (their own, their teams'),
        or the same refusal as a tool that isn't there."""
        user = _caller(ctx)
        if not graph_query_allowed(user):
            raise ToolError(f"Unknown tool: {name}")
        teams = access_service.user_teams(_db(), user["uid"])
        return user, [user["uid"], *(access_service.team_principal(t["_id"]) for t in teams)]

    def graph_run(fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except graph_cypher.GraphQueryError as err:
            raise ToolError(str(err)) from None

    @graph_tool("maintenance_graph_schema", "The maintenance graph's schema, for Cypher")
    def maintenance_graph_schema(ctx: Context) -> dict[str, Any]:
        """The maintenance graph as maintenance_graph_query sees it, for this workspace: each node label
        with its count and property keys (type, how many have it), each relationship type with its
        count and the labels it connects, the conventions (dates are ISO text, open statuses, retired
        flags, how the structures link), worked example queries that run as they are, the limits, and
        how current the copy is. Read it before writing a query."""
        user, readable = graph_caller(ctx, "maintenance_graph_schema")
        return graph_run(graph_cypher.graph_schema, get_store(), user["uid"], readable)

    @graph_tool("maintenance_graph_query", "Query the maintenance graph in Cypher")
    def maintenance_graph_query(
            cypher: Annotated[str, Field(description=(
                "One read-only Cypher statement. Match on {ns: $ns, org: $org} (passed for you). No CREATE, "
                "MERGE, SET, DELETE, REMOVE, CALL, procedures or plugin functions."))],
            ctx: Context,
            params: Annotated[dict[str, Any] | None, Field(description=(
                "Values for the query's other $parameters, e.g. {\"id\": \"...\"}. Not org or ns."))] = None,
            limit: Annotated[int | None, Field(ge=1, le=graph_cypher.HARD_MAX_ROWS, description=(
                "Most rows to return (default 1000, at most 5000)."))] = None,
            include_props: Annotated[bool | None, Field(description=(
                "Also give each node's whole stored record (nested values: checklists, stock moves, "
                "nameplates) as props."))] = None) -> dict[str, Any]:
        """Your own read-only Cypher on this workspace's maintenance graph (a copy in Neo4j kept up
        to date in the background), for questions the other tools don't answer in one call: what's
        downstream of a position, items of a class fitted in an area, open work with no redundancy,
        failures by class, spares short. Read maintenance_graph_schema first (labels, relationships,
        worked examples) and maintenance_guide topic graph. Returns columns and rows (nodes as label,
        id and plain properties; dates as ISO text), truncated with a note past the limits, and
        freshness: how current the copy is."""
        user, readable = graph_caller(ctx, "maintenance_graph_query")
        return graph_run(graph_cypher.run_query, get_store(), user["uid"], cypher, params, limit,
                         bool(include_props), readable)

    # ---- building the plant --------------------------------------------------------------

    @tool("maintenance_positions", _WRITE, "Create and change positions", POSITIONS)
    def maintenance_positions(action: _choice(POSITIONS), ctx: Context, position_id: str | None = None,
                              name: str | None = None,
                              parent_id: Annotated[str | None, Field(description=(
                                  "create / update / copy: the position (or, for create, the item) it goes "
                                  "inside. from_rcm: the position to make it in."))] = None,
                              tag: str | None = None, position_class: str | None = None,
                              description: str | None = None, location_id: str | None = None,
                              move_to_top_level: bool | None = None, clear_location: bool | None = None,
                              reason: str | None = None, study_id: str | None = None,
                              dry_run: bool | None = None) -> dict[str, Any]:
        """Positions: the functional tree (functional locations, SAP's FLOC): the slot, by what it does.
        Items are fitted to them; tasks, failure modes, parts lists and life data belong to them."""
        m = m_for(ctx)
        if action == "create":
            return run(lambda: m.position(m.create_position(name, tag or "", parent_id, position_class or "",
                                                            description or "", location_id)["id"]))
        if action == "update":
            changes = {k: v for k, v in (("name", name), ("tag", tag), ("position_class", position_class),
                                         ("description", description)) if v is not None}
            if parent_id or move_to_top_level:
                changes["parent_id"] = None if move_to_top_level else parent_id
            if location_id or clear_location:
                changes["location_id"] = None if clear_location else location_id
            return run(lambda: (m.update_position(position_id, **changes), m.position(position_id))[1])
        if action == "copy":
            return run(m.copy_position, position_id, name, parent_id)
        if action == "retire":
            return run(lambda: (m.retire_position(position_id, reason or ""), {"retired": position_id})[1])
        if action == "from_rcm":
            return run(m.position_from_rcm, study_for(ctx, study_id), parent_id)
        if action == "apply_rcm":
            return run(lambda: {**m.apply_rcm(position_id, study_for(ctx, study_id)),
                                "position": m.position(position_id)})
        return run(m.adopt_placements, _d(dry_run, True))

    @tool("maintenance_fitments", _WRITE, "Fit, remove and correct items in positions", FITMENTS)
    def maintenance_fitments(action: _choice(FITMENTS), ctx: Context, position_id: str | None = None,
                             item_id: str | None = None, item_name: str | None = None, serial: str | None = None,
                             part_number: str | None = None, manufacturer: str | None = None,
                             model: str | None = None, part_id: str | None = None, on: RoughDate = None,
                             start: RoughDate = None, end: RoughDate = None,
                             from_precision: Precision | None = None, to_precision: Precision | None = None,
                             reason: Annotated[str | None, Field(description=(
                                 "remove / add_past: planned, failure or other. void: why it was a "
                                 "mistake."))] = None,
                             failure_mode_id: str | None = None,
                             failure_mode_text: Annotated[str | None, Field(description=(
                                 "How it failed, in words: the position's mode of that name, else a new "
                                 "ad-hoc one."))] = None,
                             fitment_id: str | None = None, note: str | None = None) -> dict[str, Any]:
        """Fitments: an item in a position from one date to another, and how it ended. They are the
        history every non-repairable model is fitted to, so name a failure mode whenever an item failed:
        recording a failure as planned corrupts the life data. Replacing an item as part of work goes
        through maintenance_work_orders close (a replace action), not here. Example, a pump fitted
        sometime in 2022: {action: 'fit', position_id: '<id>', item_name: 'Pool pump', manufacturer:
        'Astral', serial: 'AX-1', on: '2022'}."""
        m = m_for(ctx)
        if action == "fit":
            new_item = {"name": item_name, "serial": serial or "", "part_number": part_number or "",
                        "manufacturer": manufacturer or "", "model": model or "",
                        "part_id": part_id} if item_name or part_id else None
            return run(m.fit, position_id, item_id, new_item, on, from_precision)
        if action == "remove":
            return run(m.remove, position_id, on, reason, failure_mode_id, failure_mode_text, to_precision)
        if action == "move":
            return run(m.move_item, item_id, position_id, on)
        if action == "add_past":
            new_item = {"name": item_name, "serial": serial or "", "part_number": part_number or "",
                        "manufacturer": manufacturer or "", "model": model or ""} if item_name else None
            return run(m.add_past_fitment, position_id, start, end, reason, item_id, new_item,
                       failure_mode_id, failure_mode_text, from_precision, to_precision, note or "")
        if action == "void":
            return run(lambda: (m.void_fitment(fitment_id, reason or ""), {"voided": fitment_id})[1])
        return run(m.correct_fitment, fitment_id, start, end, from_precision, to_precision)

    @tool("maintenance_items", _WRITE, "Change items' details", ITEMS)
    def maintenance_items(action: _choice(ITEMS), ctx: Context, item_id: str | None = None,
                          name: str | None = None, serial: str | None = None, part_number: str | None = None,
                          manufacturer: str | None = None, model: str | None = None,
                          notes: WholeNote = None, append_note: AppendNote = None,
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
                                           Field(description="Details to remove.")] = None,
                          location_id: str | None = None, on: DateText = None,
                          part_id: Annotated[str | None, Field(description=(
                              "The catalogue part (make and model); 'none' unlinks it."))] = None,
                          values: Annotated[dict[str, Any] | None, Field(description=(
                              "{attribute name: value}, e.g. {'Flow': 45, 'Head': '32 m', 'Shaft seal': "
                              "'mechanical seal'}. Numbers in the attribute's unit (convert first); '' or "
                              "null clears one."))] = None) -> dict[str, Any]:
        """Items: the physical, serial-numbered things. Their details, nameplate, dates, warranty and
        attributes, which catalogue part (make and model) they are, and where an unfitted one is. To
        fit, remove or move one: maintenance_fitments. The nameplate flow is in maintenance_guide topic
        register. Say what you read from a plate and what you couldn't."""
        m = m_for(ctx)
        if action == "update":
            details = {k: v for k, v in (("purchase_date", purchase_date), ("in_service_date", in_service_date),
                                         ("manufacture_date", manufacture_date),
                                         ("replacement_cost", replacement_cost), ("warranty", warranty))
                       if v is not None}
            details |= {k: None for k in clear or []}
            return run(m.update_item, item_id, nameplate, append_note,
                       **{k: v for k, v in (("name", name), ("serial", serial), ("part_number", part_number),
                                            ("manufacturer", manufacturer), ("model", model), ("notes", notes))
                          if v is not None}, **details)
        if action == "place":
            return run(m.place_item, item_id, location_id, on)
        if action == "set_part":
            return run(m.set_item_part, item_id, none_is_null(part_id))
        return run(m.set_item_attributes, item_id, values)

    @tool("maintenance_failure_modes", _WRITE, "Add and edit failure modes", FAILURE_MODES)
    def maintenance_failure_modes(action: _choice(FAILURE_MODES), ctx: Context, position_id: str | None = None,
                                  failure_mode_id: str | None = None, into_failure_mode_id: str | None = None,
                                  text: str | None = None, function: str | None = None, failure: str | None = None,
                                  consequence: str | None = None) -> dict[str, Any]:
        """Failure modes: how a position fails. They come from RCM studies, are added here, or are typed
        in at a failure (ad hoc). Failures (maintenance_fitments remove / add_past, maintenance_work_orders
        close) and tasks name them by id."""
        m = m_for(ctx)
        if action == "add":
            return run(m.add_failure_mode, position_id, text, function or "", failure or "", consequence or "")
        if action == "update":
            return run(m.update_failure_mode, failure_mode_id, text, function, failure, consequence)
        return run(m.merge_failure_mode, failure_mode_id, into_failure_mode_id)

    Outcome = Literal["fixed_interval", "failure_finding", "on_condition"]

    @tool("maintenance_tasks", _WRITE, "Create and change scheduled tasks", TASKS)
    def maintenance_tasks(action: _choice(TASKS), ctx: Context, task_id: str | None = None,
                          name: str | None = None, interval: float | None = None, unit: str | None = None,
                          position_id: str | None = None, item_id: str | None = None,
                          location_id: str | None = None, outcome: Outcome | None = None,
                          clear_outcome: bool | None = None, also_interval: float | None = None,
                          also_unit: str | None = None, point_id: str | None = None,
                          instructions: str | None = None, checklist: list[str] | None = None,
                          source: Literal["manual", "oem", "statutory", "other"] | None = None,
                          reference: str | None = None, failure_mode_id: str | None = None,
                          unlink_failure_mode: bool | None = None, last_done: DateText = None,
                          trade: str | None = None, while_stored: Literal["run", "pause"] | None = None,
                          include_positions: bool | None = None,
                          on: Annotated[str | None, Field(description="set_last_done: a date like 2026-10-13.")] = None,
                          reason: str | None = None) -> dict[str, Any]:
        """Scheduled tasks: they fall due and raise work orders (maintenance_work_orders generate). A task
        is on a position (the job; it counts again from each new item fitted), an item (follows the serial
        number, into a store too) or a location (a round). Tasks from RCM come with maintenance_positions
        from_rcm / apply_rcm. Example: {action: 'create', position_id: '<id>', name: 'Grease bearings',
        interval: 500, unit: 'hours', also_interval: 6, also_unit: 'months', source: 'oem', reference:
        'Manual 7.2'}."""
        m = m_for(ctx)
        if action == "create":
            return run(m.create_task, position_id, name, interval, _d(unit, "months"), outcome, also_interval,
                       also_unit, point_id, instructions or "", checklist, _d(source, "manual"), reference or "",
                       failure_mode_id, last_done, trade or "", item_id=item_id, location_id=location_id,
                       while_stored=while_stored, include_positions=include_positions)
        if action == "update":
            mode = "" if unlink_failure_mode else failure_mode_id
            return run(m.update_task, task_id, name, interval, unit, also_interval, also_unit, point_id,
                       instructions, checklist, mode, source, reference,
                       None if clear_outcome else outcome if outcome is not None else ..., trade, while_stored,
                       include_positions)
        if action == "retire":
            return run(lambda: (m.retire_task(task_id, reason or ""), {"retired": task_id})[1])
        return run(m.set_last_done, task_id, on)

    @tool("maintenance_proposals", _WRITE, "Accept or reject a proposed plan change", PROPOSALS)
    def maintenance_proposals(action: _choice(PROPOSALS), proposal_id: str, ctx: Context,
                              note: str | None = None) -> dict[str, Any]:
        """Decide a change the non-repairable models proposed to the maintenance plan (a task's interval, or
        retiring a task): maintenance_list kind proposals shows them with their reasons. The user
        decides: accept only when they have said so."""
        return run(m_for(ctx).decide_proposal, proposal_id, action == "accept", note or "")

    # ---- work ---------------------------------------------------------------------------

    @tool("maintenance_work_orders", _WRITE, "Open, progress and close work orders", WORK_ORDERS)
    def maintenance_work_orders(
            action: _choice(WORK_ORDERS), ctx: Context, work_order_id: str | None = None, title: str | None = None,
            position_id: str | None = None, item_id: str | None = None, location_id: str | None = None,
            type: Literal["corrective", "preventive", "inspection", "other"] | None = None,
            task_id: str | None = None, due: Annotated[str | None, Field(description=(
                "open: a date (default: none). update: a date, or '' to clear it."))] = None,
            notes: Annotated[str | None, Field(description=(
                "open / close: notes. update: replaces the WHOLE note (to add, use append_note)."))] = None,
            append_note: AppendNote = None, trade: str | None = None, include_positions: bool | None = None,
            assignee: str | None = None, planned_for: str | None = None,
            status: Literal["open", "planned", "in_progress", "waiting"] | None = None,
            note: str | None = None,
            actions: Annotated[list[dict] | None, Field(description=(
                "close: what was done, in order. Each: {kind: 'replace'|'repair'|'inspect'|'other', "
                "failure_mode_id?: a failure mode on the position, or failure_mode_text?: one in "
                "words (the position's mode of that name, else a new ad-hoc one) (for a replace, "
                "naming one means it failed that way; none means a planned replacement), "
                "finding?: 'ok'|'degraded'|'found_failed' (inspect only), "
                "new_item?: {name, serial?, part_number?, manufacturer?} or item_id? "
                "(replace: what went in), part_id?: a catalogue part used doing it (from "
                "the work order's suggested_parts; for a replace with no new_item / item_id, the new "
                "item is made from it), quantity? (default: the parts list's quantity per job, "
                "else 1), from_location_id? (issue it from stock there), notes?}"))] = None,
            on: DateText = None,
            readings: Annotated[list[dict] | None, Field(description=(
                "close: manual readings taken during the work: [{point_id, value}]."))] = None,
            reason: str | None = None, horizon_days: int | None = None, hours: float | None = None,
            who: str | None = None, rate: float | None = None, part: str | None = None,
            quantity: float | None = None, unit_cost: float | None = None, part_number: str | None = None,
            part_id: str | None = None, from_location_id: str | None = None, description: str | None = None,
            amount: float | None = None, entry_id: str | None = None,
            index: int | None = None, done: bool | None = None) -> dict[str, Any]:
        """Work orders: the work itself, on a position, an item or a location, from open to closed with
        its labour, parts and costs. Closing one with a replace is what builds the life data. The whole
        flow is in maintenance_guide topic run. Example, a pump that failed and was replaced:
        {action: 'close', work_order_id: '<id>', actions: [{kind: 'replace', failure_mode_id: '<the
        position's 'Bearing worn' mode>', new_item: {name: 'Pump', serial: 'N2'}}]}."""
        m = m_for(ctx)
        if action == "open":
            return run(m.open_work_order, position_id, title, _d(type, "corrective"), task_id, due, notes or "",
                       trade, item_id, location_id, include_positions)
        if action == "update":
            return run(m.update_work_order, work_order_id, title, due, notes, type, assignee, planned_for,
                       append_note, trade)
        if action == "status":
            return run(m.set_work_status, work_order_id, status, note or "")
        if action == "close":
            return run(m.close_work_order, work_order_id, actions or [], on, notes or "", readings or [])
        if action == "cancel":
            return run(m.cancel_work_order, work_order_id, reason or "")
        if action == "generate":
            return run(m.generate, max(0, min(_d(horizon_days, 30), 366)))
        if action == "labour":
            return run(m.log_labour, work_order_id, hours, who or "", rate, on, note or "")
        if action == "part_used":
            return run(m.add_part_used, work_order_id, part, _d(quantity, 1), unit_cost, part_number or "",
                       note or "", part_id, from_location_id)
        if action == "cost":
            return run(m.add_cost, work_order_id, description, amount)
        if action == "remove_entry":
            return run(m.remove_entry, entry_id)
        return run(m.check_item, work_order_id, index, _d(done, True))

    @tool("maintenance_measurements", _WRITE, "Measurement points and readings", MEASUREMENTS)
    def maintenance_measurements(action: _choice(MEASUREMENTS), ctx: Context, point_id: str | None = None,
                                 position_id: str | None = None, item_id: str | None = None,
                                 name: str | None = None, kind: Literal["counter", "condition"] | None = None,
                                 unit: str | None = None, source: Literal["manual", "automated"] | None = None,
                                 tag: str | None = None, alarm_above: float | None = None,
                                 alarm_below: float | None = None, clear_alarm_above: bool | None = None,
                                 clear_alarm_below: bool | None = None, value: float | None = None,
                                 on: Annotated[str | None, Field(description=(
                                     "record: the day it was read (default today; a past date backdates it). "
                                     "correct: the date it was really read (default unchanged)."))] = None,
                                 note: str | None = None, reading_id: str | None = None,
                                 reason: str | None = None,
                                 at: Annotated[str | None, Field(description=(
                                     "When it was read: 2026-10-19T10:14 (seconds and up to nine decimals "
                                     "allowed; Z or an offset, else the workspace's time zone), or a coarser "
                                     "2026-10-19, 2026-10 or 2026."))] = None,
                                 precision: Annotated[
                                     Literal["year", "month", "day", "hour", "minute", "second", "us", "ns"] | None,
                                     Field(description="How precisely the time is known (default: as given)."),
                                 ] = None) -> dict[str, Any]:
        """Measurement points (counters such as run hours, and condition measures with alarm limits) on a
        position or an item, and their manual readings. Counters drive tasks by use; condition alarms
        open inspections. Reading ids are in maintenance_get kind measurement_point."""
        m = m_for(ctx)
        if action == "add_point":
            return run(m.add_point, position_id, name or "", _d(kind, "condition"), unit or "",
                       _d(source, "manual"), tag or "", alarm_above, alarm_below, item_id=item_id)
        if action == "update_point":
            kwargs = {}
            if name is not None:
                kwargs["name"] = name
            if alarm_above is not None or clear_alarm_above:
                kwargs["alarm_above"] = None if clear_alarm_above else alarm_above
            if alarm_below is not None or clear_alarm_below:
                kwargs["alarm_below"] = None if clear_alarm_below else alarm_below
            if tag is not None:
                kwargs["tag"] = tag
            return run(m.update_point, point_id, **kwargs)
        if action == "record":
            return run(m.record_reading, point_id, value, on, note or "", at, precision)
        if action == "void":
            return run(m.void_reading, reading_id, reason)
        return run(m.correct_reading, reading_id, value, on, reason, at, precision, note)

    @tool("maintenance_locations", _WRITE, "Create and change locations", LOCATIONS)
    def maintenance_locations(action: _choice(LOCATIONS), ctx: Context, location_id: str | None = None,
                              name: str | None = None, parent_id: str | None = None,
                              description: str | None = None, move_to_top_level: bool | None = None
                              ) -> dict[str, Any]:
        """Locations: the physical tree (sites, areas, buildings, rooms, substations, stores), separate
        from the positions (the functional tree). Positions get a location_id; unfitted items are placed
        at one (maintenance_items place)."""
        m = m_for(ctx)
        if action == "create":
            return run(m.create_location, name, parent_id, description or "")
        kwargs = {k: v for k, v in (("name", name), ("description", description)) if v is not None}
        if parent_id or move_to_top_level:
            kwargs["parent_id"] = None if move_to_top_level else parent_id
        return run(m.update_location, location_id, **kwargs)

    PartRole = Literal["replacement", "component", "consumable"]

    def parts_structure(m, action, part_id, component_id, quantity, ref, level, levels, renamed, rows, dry_run,
                        position_id):
        """maintenance_parts' product structure actions (#435)."""
        if action == "add_component":
            return run(m.add_component, part_id, component_id, _d(quantity, 1), ref or "")
        if action == "update_component":
            return run(m.update_component, part_id, component_id, quantity, ref)
        if action == "remove_component":
            return run(m.remove_component, part_id, component_id)
        if action == "set_level":
            return run(m.set_part_level, part_id, level or "")
        if action == "set_levels":
            return run(m.set_part_levels, levels, renamed)
        if action == "import_bom":
            def go():
                header, table = bom.table_from_rows(rows)
                return bom.run(m, header, table, _d(dry_run, True))
            return run(go)
        return run(m.positions_from_structure, part_id, position_id, levels, _d(dry_run, True))

    @tool("maintenance_parts", _WRITE, "Parts catalogue, stock and parts lists", PARTS)
    def maintenance_parts(action: _choice(PARTS), ctx: Context, part_id: str | None = None,
                          part_number: str | None = None, name: str | None = None,
                          manufacturer: str | None = None, unit: str | None = None,
                          unit_cost: float | None = None, notes: str | None = None,
                          item_class_id: str | None = None, manufacturer_id: str | None = None,
                          location_id: str | None = None, quantity: float | None = None,
                          reason: str | None = None, on: DateText = None, reorder_point: float | None = None,
                          other_part_id: str | None = None,
                          relation: Literal["superseded_by", "interchangeable"] | None = None,
                          position_id: str | None = None, role: PartRole | None = None,
                          critical: bool | None = None, min_on_hand: float | None = None,
                          listing_id: str | None = None, component_id: str | None = None,
                          ref: Annotated[str | None, Field(description=(
                              "A reference designator or position-in-assembly label: 'B1' ('B1, B2' for 2)."))] = None,
                          level: str | None = None, levels: list[str] | None = None,
                          renamed: Annotated[dict[str, str] | None, Field(description=(
                              "set_levels: {old name: new name}; parts at a renamed level follow."))] = None,
                          rows: Annotated[list[dict[str, str]] | None, Field(description=(
                              "import_bom: [{'parent part number', 'part number', quantity?, nomenclature?, "
                              "'indenture level'?, manufacturer?, reference?}]; names matched loosely."))] = None,
                          dry_run: bool | None = None, lead_time_days: float | None = None,
                          service_level: float | None = None, repairable: bool | None = None,
                          turnaround_days: float | None = None) -> dict[str, Any]:
        """The parts catalogue (spares, and makes and models of equipment), stock at locations, and each
        position's parts list (its bill of materials, with critical spares). Supersession and
        interchangeable parts belong to the catalogue (link), not the parts list. Parts made of parts
        (product structure): guide topic structure."""
        m = m_for(ctx)
        if action in STRUCTURE_ACTIONS:
            return parts_structure(m, action, part_id, component_id, quantity, ref, level, levels, renamed, rows,
                                   dry_run, position_id)
        if action == "create":
            return run(m.create_part, part_number, name, manufacturer or "", _d(unit, "each"), unit_cost,
                       notes or "", item_class_id, manufacturer_id)
        if action == "update":
            changes = {"name": name, "manufacturer": manufacturer, "unit": unit, "unit_cost": unit_cost,
                       "notes": notes, "lead_time_days": lead_time_days, "service_level": service_level,
                       "repairable": repairable, "turnaround_days": turnaround_days}
            return run(m.update_part, part_id, **{k: v for k, v in changes.items() if v is not None})
        if action == "stock":
            return run(m.adjust_stock, part_id, location_id, quantity, reason or "", on)
        if action == "reorder":
            return run(m.set_reorder_point, part_id, location_id, reorder_point)
        if action == "link":
            if relation == "superseded_by":
                return run(m.supersede_part, part_id, other_part_id)
            return run(m.mark_interchangeable, part_id, other_part_id)
        if action == "add_to_position":
            return run(m.add_position_part, position_id, part_id, _d(role, "component"), _d(quantity, 1),
                       bool(critical), min_on_hand, notes or "")
        if action == "update_on_position":
            return run(m.update_position_part, listing_id, role, quantity, critical,
                       ... if min_on_hand is None else min_on_hand, notes)
        return run(m.remove_position_part, listing_id)

    # ---- closing the loop -------------------------------------------------------------

    @tool("maintenance_reliability", _WRITE, "Position class costs and non-repairable models", RELIABILITY)
    def maintenance_reliability(action: _choice(RELIABILITY), position_class: str, ctx: Context,
                                planned_cost: float | None = None, failure_cost: float | None = None,
                                availability_target: float | None = None, replacement_cost: ReplacementCost = None,
                                clear_replacement_cost: bool | None = None,
                                distribution: Literal["weibull", "best", "lognormal", "exponential", "gamma"] | None
                                = None) -> dict[str, Any]:
        """A position class's costs and its fitted non-repairable model: what turns the history into proposed task
        intervals (maintenance_guide topic learn). Read the pooled data first with maintenance_get kind
        class_life_data; plan_economics there costs the plan."""
        m = m_for(ctx)
        if action == "set_class_costs":
            def go():
                if (planned_cost, failure_cost, availability_target) != (None, None, None):
                    m.set_class_costs(position_class, planned_cost, failure_cost, availability_target)
                if replacement_cost is not None or clear_replacement_cost:
                    m.set_class_replacement_cost(position_class, None if clear_replacement_cost else replacement_cost)
                return m.position_class(position_class)
            return run(go)
        from backend import fitting

        try:
            return run(loop.fit_class_model, m, _db(), position_class, _d(distribution, "weibull"))
        except fitting.FitError as err:
            raise ToolError(f"The fit didn't work: {err}") from None

    @tool("maintenance_topology", _WRITE, "Connections, redundancy and the generated RBD", TOPOLOGY)
    def maintenance_topology(action: _choice(TOPOLOGY), ctx: Context, from_id: str | None = None,
                             to_id: str | None = None,
                             kind: Literal["flow", "electrical", "mechanical", "signal", "data", "other"] | None = None,
                             medium: str | None = None, name: str | None = None, rating: str | None = None,
                             realised_by: str | None = None, interface_id: str | None = None,
                             member_ids: list[str] | None = None, k: int | None = None,
                             mode: Literal["active", "standby"] | None = None,
                             standby: Literal["cold", "warm", "hot"] | None = None,
                             group_id: str | None = None, add: list[str] | None = None,
                             remove: list[str] | None = None, position_id: str | None = None) -> dict[str, Any]:
        """How positions depend on each other: connections (what passes from one to another) and
        redundancy groups (k of n will do). They drive impact (maintenance_get kind impact) and the RBD
        generate_rbd makes from a system."""
        m = m_for(ctx)
        if action == "connect":
            return run(m.connect, from_id, to_id, _d(kind, "flow"), medium or "", name or "", rating or "",
                       realised_by)
        if action == "disconnect":
            return run(lambda: (m.disconnect(interface_id), {"removed": interface_id})[1])
        if action == "create_group":
            return run(m.create_group, name or "", member_ids, _d(k, 1), _d(mode, "active"), _d(standby, "cold"))
        if action == "update_group":
            return run(m.update_group, group_id, name, k, mode, standby, add or [], remove or [])
        if action == "set_duty":
            return run(m.set_duty, group_id, position_id)
        return run(rbd_derive.save, m, _db(), position_id)

    # ---- item classes and the manufacturer register (optional) --------------------------

    Attributes = Annotated[list[dict[str, Any]] | None, Field(description=(
        "The class's own attributes: [{name, unit?, kind?: number | text | choice, options?: [..] for a "
        "choice}], e.g. [{name: 'Flow', unit: 'm3/h'}, {name: 'Shaft seal', kind: 'choice', options: "
        "['mechanical seal', 'packing']}]. kind defaults to number when there's a unit, else text. Classes "
        "inside it inherit them; never repeat an inherited one."))]

    def item_condition(m, action, condition_id, name, parent_id, kind, unit, code, description, move_to_top_level,
                       reason, target_id, value, note, conditions, csv, dry_run, source):
        """maintenance_item_classes' condition actions."""
        if action == "create_condition":
            return run(m.create_condition, name, parent_id, kind, unit or "", code or "", description or "")
        if action == "update_condition":
            kwargs = {k: v for k, v in (("name", name), ("kind", kind), ("unit", unit), ("code", code),
                                        ("description", description)) if v is not None}
            if parent_id or move_to_top_level:
                kwargs["parent_id"] = None if move_to_top_level else parent_id
            return run(m.update_condition, condition_id, **kwargs)
        if action == "retire_condition":
            return run(lambda: (m.retire_condition(condition_id, reason or ""), {"retired": condition_id})[1])
        if action == "apply_condition":
            return run(m.apply_condition, target_id, condition_id, value, note or "")
        if action == "exclude_condition":
            return run(m.exclude_condition, target_id, condition_id, note or "")
        if action == "remove_condition":
            return run(m.remove_condition, target_id, condition_id)
        if (conditions is None) == (csv is None):
            raise ToolError("Give the conditions as JSON (conditions) or CSV text (csv), one of them.")

        def go():
            rows = register_io.rows_from_json(conditions) if conditions is not None else register_io.rows_from_csv(csv)
            return register_io.run(m, rows, _d(dry_run, True), _d(source, "imported"))
        return run(go)

    @tool("maintenance_item_classes", _WRITE, "Item classes and conditions", ITEM_CLASSES)
    def maintenance_item_classes(action: _choice(ITEM_CLASSES), ctx: Context, item_class_id: Annotated[
                                     str | None, Field(description=(
                                         "The class; for assign, 'none' takes the target's class away."))] = None,
                                 name: str | None = None, parent_id: str | None = None, code: str | None = None,
                                 level: Annotated[str | None, Field(description=(
                                     "The user's name for its level, e.g. class, type, subunit, maintainable "
                                     "item."))] = None,
                                 description: str | None = None, attributes: Attributes = None,
                                 move_to_top_level: bool | None = None, reason: str | None = None,
                                 target_id: Annotated[str | None, Field(description=(
                                     "assign: an item or a catalogue part. *_condition: a location, position, "
                                     "item or connection."))] = None,
                                 condition_id: str | None = None,
                                 kind: Annotated[Literal["presence", "value"] | None, Field(description=(
                                     "A condition: presence (default) or value (a number in unit)."))] = None,
                                 unit: str | None = None, value: float | str | None = None,
                                 note: str | None = None,
                                 conditions: Annotated[list[dict[str, Any]] | None, Field(description=(
                                     "import_conditions: [{path: 'Hazardous area > Zone 1', kind?, unit?, code?, "
                                     "description?}]."))] = None,
                                 classes: Annotated[list[dict[str, Any]] | None, Field(description=(
                                     "import, as JSON: [{path: 'Rotating equipment > Pump > Centrifugal', code?, "
                                     "level?, description?, attributes?: [{name, unit?, kind?, options?}]}], or "
                                     "{name, parent?: path} for path, or nested with children: [...]."))] = None,
                                 csv: Annotated[str | None, Field(description=(
                                     "import, as CSV text with a header: path (or name, parent), code, level, "
                                     "description, attributes ('Flow (m3/h); Stages [number]; Seal [choice: "
                                     "mechanical | packing]')."))] = None,
                                 dry_run: bool | None = None, source: str | None = None) -> dict[str, Any]:
        """Item classes (optional): what KIND OF THING items and parts are, as a tree with attributes
        inherited down it (Rotating equipment > Pump > Centrifugal). Not a position's position_class,
        which is the duty and pools life data. Read it with maintenance_list kind item_classes. Also the
        condition register (Outdoor, Seawater, Zone 1) and what things are exposed to."""
        m = m_for(ctx)
        if action.endswith("_condition") or action == "import_conditions":
            return item_condition(m, action, condition_id, name, parent_id, kind, unit, code, description,
                                  move_to_top_level, reason, target_id, value, note, conditions, csv, dry_run, source)
        if action == "create":
            return run(m.create_item_class, name, parent_id, code or "", level or "", description or "", attributes)
        if action == "update":
            kwargs = {k: v for k, v in (("name", name), ("code", code), ("level", level),
                                        ("description", description)) if v is not None}
            if parent_id or move_to_top_level:
                kwargs["parent_id"] = None if move_to_top_level else parent_id
            return run(m.update_item_class, item_class_id, **kwargs)
        if action == "set_attributes":
            return run(m.set_item_class_attributes, item_class_id, attributes or [])
        if action == "retire":
            return run(lambda: (m.retire_item_class(item_class_id, reason or ""), {"retired": item_class_id})[1])
        if action == "assign":
            return run(m.assign_item_class, target_id, none_is_null(item_class_id))
        if action == "import":
            if (classes is None) == (csv is None):
                raise ToolError("Give the classes as JSON (classes) or CSV text (csv), one of them.")

            def go():
                rows = taxonomy.rows_from_json(classes) if classes is not None else taxonomy.rows_from_csv(csv)
                return taxonomy.run(m, rows, _d(dry_run, True), _d(source, "imported"))
            return run(go)
        return run(taxonomy.load_starter, m, _d(dry_run, True))

    @tool("maintenance_manufacturers", _WRITE, "The manufacturer register", MANUFACTURERS)
    def maintenance_manufacturers(action: _choice(MANUFACTURERS), ctx: Context,
                                  manufacturer_id: Annotated[str | None, Field(description=(
                                      "The register entry; for link, 'none' unlinks the target."))] = None,
                                  name: str | None = None, aliases: list[str] | None = None,
                                  add_aliases: list[str] | None = None, remove_aliases: list[str] | None = None,
                                  into_manufacturer_id: str | None = None,
                                  target_id: Annotated[str | None, Field(description=(
                                      "link: an item or a catalogue part."))] = None,
                                  dry_run: bool | None = None) -> dict[str, Any]:
        """The manufacturer register: one entry per maker, tying its spellings together ('KSB',
        'K.S.B.', 'KSB SE & Co. KGaA'). Items and parts keep their typed manufacturer text and link to an
        entry. Find one first with maintenance_get kind manufacturer_match."""
        m = m_for(ctx)
        if action == "create":
            return run(m.create_manufacturer, name, aliases or [])
        if action == "update":
            return run(m.update_manufacturer, manufacturer_id, name, add_aliases or [], remove_aliases or [])
        if action == "merge":
            return run(m.merge_manufacturers, manufacturer_id, into_manufacturer_id)
        if action == "link":
            return run(m.link_manufacturer, target_id, none_is_null(manufacturer_id))
        return run(m.link_manufacturers_by_name, _d(dry_run, True))

    # ---- photos, documents and the workspace -------------------------------------------

    @tool("maintenance_attachments", _WRITE, "Photos, coordinates and documents", ATTACHMENTS)
    def maintenance_attachments(action: _choice(ATTACHMENTS), ctx: Context,
                                target_id: Annotated[str | None, Field(description=(
                                    "photo_link, link_photo, unlink_photo, move_photo: a position, location, "
                                    "item or work order. set_coordinates: a "
                                    "position, item, location or work order. add_document: an item or "
                                    "position."))] = None,
                                upload_id: Annotated[str | None, Field(max_length=64, description=(
                                    "add_document: a PDF sent with uploads create (purpose document)."))] = None,
                                caption: str | None = None, lat: float | None = None, lon: float | None = None,
                                source: Literal["photo", "manual"] | None = None, photo_id: str | None = None,
                                url: str | None = None, title: str | None = None,
                                kind: Literal["manual", "datasheet", "invoice", "drawing", "certificate",
                                              "other"] | None = None,
                                position_class: str | None = None, document_id: str | None = None,
                                from_id: str | None = None) -> dict[str, Any]:
        """What's attached to the register: photos (added by the user from a phone through a link;
        stored without location or camera details), coordinates, and documents (links or PDFs). To look at a
        photo: maintenance_view_photo."""
        m = m_for(ctx)
        if action == "photo_link":
            return run(lambda: link_payload(base_url(ctx), m, m.photo_target(target_id), (caption or "")[:200]))
        if action == "set_coordinates":
            return run(m.set_coordinates, target_id, lat, lon, _d(source, "manual"))
        if action == "remove_photo":
            return run(remove_photo, m, photo_id)
        if action == "link_photo":
            return run(m.link_photo, photo_id, target_id)
        if action == "unlink_photo":
            return run(m.unlink_photo, photo_id, target_id)
        if action == "move_photo":
            return run(m.move_photo, photo_id, target_id, from_id)
        if action == "add_document":
            if bool(url) == bool(upload_id):
                raise ToolError("Give either url (a web address to link) or upload_id (a PDF sent with uploads "
                                "create, purpose document): exactly one.")
            if url:
                return run(m.add_document, url, title or "", _d(kind, "other"), target_id, position_class)
            from backend.services import uploads as uploads_service

            db, uid = _db(), _caller(ctx)["uid"]
            try:
                upload, data = uploads_service.read(db, upload_id, uid)
            except uploads_service.UploadError as err:
                raise ToolError(str(err)) from None
            saved = run(ingest_document, m, data, upload.get("filename") or "", title or "", _d(kind, "other"),
                        target_id, position_class)
            uploads_service.delete(db, upload["_id"])
            return saved
        return run(remove_document, m, document_id)

    @tool("maintenance_workspace", _WRITE, "Workspace settings and history import", WORKSPACE)
    def maintenance_workspace(action: _choice(WORKSPACE), ctx: Context,
                              time_zone: Annotated[str | None, Field(description=(
                                  "An IANA name such as 'Australia/Brisbane'; '' clears it (UTC)."))] = None,
                              rows: Annotated[list[dict[str, str]] | None, Field(description=(
                                  "import_history: one row per item per position: {position: 'House > Pool > "
                                  "Pump', class?, item?, serial?, manufacturer?, model?, part number?, fitted?: "
                                  "date, removed?: date, failed?: yes/no, failure mode?}. Column names are "
                                  "matched loosely."))] = None,
                              dry_run: bool | None = None) -> dict[str, Any]:
        """The maintenance workspace as a whole: its time zone, and bringing an existing history in."""
        if action == "set_time_zone":
            user = _caller(ctx)
            m_for(ctx)  # Maintenance is on for this account
            try:
                return {"time_zone": time_zones.set_personal(_db(), user["uid"], time_zone)}
            except time_zones.BadTimeZone as err:
                raise ToolError(str(err)) from None
        if len(rows) > importer.MAX_ROWS:
            raise ToolError(f"At most {importer.MAX_ROWS} rows at a time.")
        return run(importer.run, m_for(ctx), [{str(k): str(v) for k, v in r.items()} for r in rows],
                   _d(dry_run, True))

    # The tools are listed only to people who may use them: wrap the server's
    # tools/list handler to drop them for everyone else.
    lowlevel = mcp._lowlevel_server
    handlers = lowlevel._request_handlers
    entry = handlers["tools/list"]
    _ORIGINAL["tools/list"] = entry
    hidden = set(TOOL_NAMES) | set(GRAPH_TOOL_NAMES)
    graph_only = set(GRAPH_TOOL_NAMES)

    def user_of(ctx):
        return getattr(getattr(getattr(ctx, "request", None), "state", None), "reliafy_user", None)

    async def list_tools(ctx, params):
        result = await entry.handler(ctx, params)
        user = user_of(ctx)
        if not allowed(user):
            return result.model_copy(update={"tools": [t for t in result.tools if t.name not in hidden]})
        if graph_query_allowed(user):
            return result
        tools = [_without_graph_topic(t) if t.name == "maintenance_guide" else t
                 for t in result.tools if t.name not in graph_only]
        return result.model_copy(update={"tools": tools})

    handlers["tools/list"] = dataclasses.replace(entry, handler=list_tools)

    # ... and the server's instructions gain the maintenance section only for
    # them. initialize is built by the SDK's runner (it can't be replaced), so a
    # server middleware adds the section to its result (and server/discover's,
    # the newer protocol's equivalent).
    async def instructions(ctx, call_next):
        result = await call_next(ctx)
        if ctx.method in ("initialize", "server/discover") and isinstance(result, dict) \
                and allowed(user_of(ctx)):
            section = mcp_guide.INSTRUCTIONS
            if graph_query_allowed(user_of(ctx)):
                section = f"{section}{mcp_guide.GRAPH_INSTRUCTIONS}"
            base = result.get("instructions") or ""
            result = {**result, "instructions": f"{base}\n{section}" if base else section}
        return result

    _ORIGINAL["middleware"] = instructions
    lowlevel.middleware.append(instructions)

    mcp_server._FIT_TOOLS.update(PRO_FIT_CALLS)
    mcp_server.PRO_ONLY_TOOLS.update(PRO_FIT_CALLS)
    mcp_server.HEAVY_TOOLS.update(HEAVY_CALLS)


def _without_graph_topic(tool):
    """maintenance_guide as listed to someone who may not run graph queries: its
    topic choices without "graph"."""
    import copy

    schema = copy.deepcopy(tool.input_schema)

    def strip(node):
        if isinstance(node, dict):
            if isinstance(node.get("enum"), list):
                node["enum"] = [v for v in node["enum"] if v != "graph"]
            for v in node.values():
                strip(v)
        elif isinstance(node, list):
            for v in node:
                strip(v)

    strip(schema.get("properties", {}).get("topic"))
    return tool.model_copy(update={"input_schema": schema})


def unregister() -> None:
    """Remove the maintenance tools again (for tests)."""
    from backend import mcp_server
    from backend.mcp_server import mcp

    mcp_server._FIT_TOOLS.difference_update(PRO_FIT_CALLS)
    mcp_server.PRO_ONLY_TOOLS.difference_update(PRO_FIT_CALLS)
    mcp_server.HEAVY_TOOLS.difference_update(HEAVY_CALLS)
    for name in TOOL_NAMES + GRAPH_TOOL_NAMES:
        mcp.remove_tool(name)
    TOOL_NAMES.clear()
    GRAPH_TOOL_NAMES.clear()
    lowlevel = mcp._lowlevel_server
    if "tools/list" in _ORIGINAL:
        lowlevel._request_handlers["tools/list"] = _ORIGINAL.pop("tools/list")
    if "middleware" in _ORIGINAL:
        middleware = _ORIGINAL.pop("middleware")
        if middleware in lowlevel.middleware:
            lowlevel.middleware.remove(middleware)
