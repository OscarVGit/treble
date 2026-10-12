"""The finite action space exposed by the decision layer.

Von never produces free-form shell. It answers a structured Choice question
over a fixed set of options, and Treble maps the chosen option onto one of
these actions. Every free-form request is routed through Von; there is no
deterministic short-circuit.

Safety boundary: Von *selects* an action and a target; the runtime
*enforces*. Mutating actions (``ADD_PROCEDURE``, ``REMOVE_PROCEDURE``) and
any destructive procedure still pass through the confirmation/policy gates
before anything is executed or changed.
"""

from __future__ import annotations

from enum import StrEnum


class Action(StrEnum):
    """What Treble may do after consulting the decision model."""

    # Procedure execution.
    SELECT_PROCEDURE = "select"      # run a registered procedure
    TEST = "test"                    # execute a named procedure directly
    # Read-only control plane.
    LIST = "list"                    # list all registered procedures
    SHOW = "show"                    # show one procedure's stored definition
    EXPLAIN = "explain"              # show the execution plan for a procedure
    # Mutating control plane (gated).
    ADD_PROCEDURE = "add"            # add a new procedure (never auto-authored)
    REMOVE_PROCEDURE = "remove"      # remove a named procedure (confirm first)
    # Non-executable outcomes.
    CLARIFY = "clarify"              # ask the user to disambiguate
    ESCALATE = "escalate"            # no suitable action / none-of-the-above
    REJECT = "reject"                # refuse (unsafe, or environment forbids)


# Actions that carry a procedure name as their target.
TARGETED_ACTIONS: frozenset[Action] = frozenset(
    {Action.SELECT_PROCEDURE, Action.TEST, Action.SHOW, Action.EXPLAIN, Action.REMOVE_PROCEDURE}
)

# Actions that change state and therefore honour --dry-run and confirmations.
MUTATING_ACTIONS: frozenset[Action] = frozenset(
    {Action.SELECT_PROCEDURE, Action.TEST, Action.REMOVE_PROCEDURE}
)
