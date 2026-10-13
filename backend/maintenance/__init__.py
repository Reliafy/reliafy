"""Reliafy Maintenance: the plant as a graph, and the work done on it.

* :mod:`backend.maintenance.store` — the graph store. Every change is an
  event appended to a log; the nodes and edges are a projection of that log
  and can be rebuilt from it. This is the Python backend (SQLite in one
  file); a Neo4j backend will sit behind the same interface.
* :mod:`backend.maintenance.service` — the domain: positions, locations,
  items, fitments, placements, RCM failure modes and tasks, work orders and
  their actions, and the life data that fitments give.
* :mod:`backend.maintenance.schedule` — calendar arithmetic for tasks: on
  the calendar, and by use on an operating schedule.

The design is in the "Reliafy Maintenance plan" doc. Local only for now
(``MAINTENANCE_ENABLED``).
"""
