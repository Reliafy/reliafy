"""Common-cause groups in repairable diagrams (#226).

Since RePyability 0.12 a ``RepairableRBD``'s common-cause groups are followed
over time (#158 there): the long-run figures and importance, A(t) and the
window's events and costs, the simulation and the allocations take them in,
each group a Markov chain of which members are down together. Since 0.13
(#220 there) proof-tested members' tests and repairs may take time — none, a
fixed time or an exponential one — so the most common SIL case, a 1oo2 or
2oo3 with a β and a mean repair time, is followed too. Where its chain or its
simulation can't take a group — a member whose life isn't exponential, one
with scheduled maintenance, imperfect repair or a maintenance group, revealed
failures with non-exponential repairs, tests or repairs of another length,
limited repair crews, a member pinned working or failed, or one started from
a current state — it refuses, with the reason.

Reliafy's rule: a repairable diagram's common cause is in **every** figure or
in **none**. :func:`common_cause_refusal` asks RePyability whether its long
run, its values over time from new and its simulation all take the groups;
when one doesn't, the diagram is analysed without them (as before #226) and
the reason is said beside the figures, so the exact figures, the simulation
and the costs never mix a with-common-cause value with one without. A safety
function's PFDavg needs only the long run (:func:`long_run_refusal`), so it
keeps its groups wherever the long-run chain covers them (#136).

One figure is the exception (#328): RePyability 0.13 doesn't work out the
exact long-run failure frequency (nor the mean up and down times built on
it) with groups whose members' proof tests — or other blocks' block
replacements — take time. Every other figure takes the groups there, so they
stay in, and only that figure is left out, with its reason
(:func:`frequency_refusal`); the simulation's estimate of it, which takes the
groups, still stands.

With limited repair crews RePyability 0.13 refuses the groups itself, in
every exact figure (#251 there; 0.12's crew chain dropped them), and the
long-run check below refuses there too.

The functions take an RBD and its pins only, so "Download as Python" copies
them into its script (:func:`export_source`) and decides as the app does.
"""

from __future__ import annotations

import inspect


def long_run_refusal(rbd, working_nodes=(), broken_nodes=()):
    """None when RePyability's long-run values take ``rbd``'s common-cause
    groups in (with these blocks pinned), else its reason."""
    if not getattr(rbd, "ccf_groups", None):
        return None
    try:
        rbd._require_free_members(set(working_nodes or ()), set(broken_nodes or ()))
        rbd._require_ccf_long_run()
    except NotImplementedError as exc:
        return str(exc)
    return None


def common_cause_refusal(rbd, working_nodes=(), broken_nodes=(), state=None):
    """None when RePyability takes ``rbd``'s common-cause groups into every
    figure of a repairable diagram — the long run, the values over time and
    the simulation, from ``state`` (node -> NodeState; None: every block new)
    with these blocks pinned — else the reason it doesn't. The exact
    long-run failure frequency is :func:`frequency_refusal`'s (#328)."""
    reason = long_run_refusal(rbd, working_nodes, broken_nodes)
    if reason is not None or not getattr(rbd, "ccf_groups", None):
        return reason
    try:
        rbd._require_groups_over_time(dict(state or {}))
        rbd._require_groups_simulated(state or None)
    except NotImplementedError as exc:
        return str(exc)
    return None


def frequency_refusal(rbd):
    """None when RePyability works out ``rbd``'s exact long-run failure
    frequency (and so its mean up and down times) with its common-cause
    groups, else its reason: planned outages at tests or block replacements
    that take time aren't worked out with the groups yet (#328)."""
    if not getattr(rbd, "ccf_groups", None):
        return None
    try:
        rbd._require_ccf_frequencies()
    except NotImplementedError as exc:
        return str(exc)
    return None


_EXPORTED = (long_run_refusal, common_cause_refusal, frequency_refusal)


def export_source() -> str:
    """The functions above, as "Download as Python" copies them."""
    return "\n\n".join(inspect.getsource(f).rstrip() for f in _EXPORTED) + "\n"
