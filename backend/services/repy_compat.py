"""The few RePyability internals Reliafy reaches into, in one place.

RePyability's public API covers almost everything the app does. A handful of
features need a private helper (a repairable diagram's long-run actions per
component, the jobs its crews serve, a raw run of simulations, ...). Those
helpers move between releases: 0.14 split ``RepairableRBD`` into modules by
analysis, so its private methods became module functions taking the diagram.
Every call site imports them from here, so the next move is one edit, and
``backend/tests/test_repy_compat.py`` fails at once if one goes missing.

Code that "Download as Python" copies into its scripts can't import this
module, so it imports RePyability itself (``rbd_ccf``'s common-cause checks);
the test covers those names too.
"""
from __future__ import annotations

from typing import Any, Optional


def node_actions(rbd, node, availability: float) -> tuple[float, float]:
    """A repairable component's corrective and preventive actions per unit
    time in the long run, ``availability`` being its long-run availability."""
    from repyability.rbd._costs import _node_actions

    return _node_actions(rbd, node, availability)


def crew_served(rbd) -> list:
    """The jobs a repairable diagram's repair crews work on: its own
    components (not a nested diagram's) and each unit of a standby group."""
    from repyability.rbd._crews import _crew_served

    return _crew_served(rbd)


def run_simulations(rbd, *args, **kwargs):
    """A raw run of a repairable diagram's simulations, returning its tally
    (the arguments are RePyability's ``_run_alone``'s)."""
    from repyability.rbd._event_loop import _run

    return _run(rbd, *args, **kwargs)


def entropy_of(seed) -> int:
    """The entropy RePyability seeds a run's streams from, given its seed."""
    from repyability.rbd import _streams

    return _streams.entropy_of(seed)


def modular_reduction():
    """RePyability's modular-reduction class and its sink marker,
    ``(_Reduction, _SINK)``."""
    from repyability.rbd.modular import _SINK, _Reduction

    return _Reduction, _SINK


def parametric_spec(model) -> Optional[Any]:
    """A parametric life or repair model's parameters, or None where it has
    none RePyability can rebuild (a nested diagram, a non-parametric fit, a
    name, ...).

    The result has ``cls``, ``params``, ``names``, ``extras`` and ``bounds``
    and ``build(values)`` rebuilds the model. Since 0.14 ``params`` and
    ``names`` also carry the shares a limited-failure-population or
    zero-inflated model has (``lfp_p``, ``f0``), so rebuild with ``build``,
    never ``cls.from_params(params, **extras)``.
    """
    from repyability.rbd._model_utils import parametric_spec as _spec

    if model is None or isinstance(model, str):
        return None
    try:
        return _spec(model)
    except Exception:  # noqa: BLE001 - not a model RePyability rebuilds
        return None


def chain_probabilities(rbd, working_nodes, broken_nodes):
    """With limited repair crews: ``(availability of every node in each state
    of the crews' Markov chain, the states' long-run probabilities)``."""
    from repyability.rbd._crews import _chain_probabilities

    return _chain_probabilities(rbd, working_nodes, broken_nodes)


def block_cycle(rbd, node):
    """A block-replaced (or replaced-on-condition) component's renewal cycle."""
    from repyability.rbd._long_run import _block_cycle

    return _block_cycle(rbd, node)


def fault_tree_conditioned(tree, t):
    """``(top, occurred, not_occurred)`` for a fault tree at ``t``: the top
    event's probability, and for each event the top event's probability given
    that it has occurred and given that it has not (arrays over the times).

    0.14 put the probability the top event has not occurred first and the
    events' probabilities after (7 values where 0.13 gave 5), so the app's
    old unpacking failed and its importance was lost without a word. Any
    other shape raises here.
    """
    out = tree._conditioned(t)
    if len(out) == 7:  # works, top, occurred, not_occurred, p, q, shape
        _, top, occurred, not_occurred, _, _, _ = out
    else:
        raise TypeError(f"FaultTree._conditioned returned {len(out)} values; expected 5 or 7")
    if not isinstance(occurred, dict) or not isinstance(not_occurred, dict):
        raise TypeError("FaultTree._conditioned: unexpected result")
    return top, occurred, not_occurred
