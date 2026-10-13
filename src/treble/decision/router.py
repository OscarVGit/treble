"""Route a request through the Von decision model.

Every free-form request goes through Von — there is no deterministic
regex/exact-match short-circuit. Routing is decomposed into the primitives
Von is best at:

1. **Run gate (Noul)** — is this a request to run a procedure, or to manage
   procedures (list/show/explain/test/remove/add)?
2. **Run target (Choice)** — for a run, which procedure to execute.
3. **Control verb (Choice)** — for a management request, which verb; targeted
   verbs (show/explain/test/remove) then get a further target Choice.

Each Choice is gated on the winning option's probability and on the margin
between the top two; trips produce ``CLARIFY``. ``none-of-the-above``
produces ``ESCALATE``. Client connection/HTTP errors propagate so the caller
fails closed — there is no deterministic fallback.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from treble.decision.actions import Action
from treble.decision.client import SystemOneClient
from treble.decision.prompts import (
    NONE_OF_THE_ABOVE,
    TARGETED_VERBS,
    VERB_TO_ACTION,
    Variant,
    build_control_target_options,
    build_control_verb_options,
    build_routing_state,
    build_run_target_options,
    build_state,
    control_target_instructions,
    control_target_state,
    control_verb_instructions,
    get_variant,
)
from treble.decision.protocol import (
    ChoiceAnswer,
    ChoiceQuestion,
    NoulAnswer,
    NoulQuestion,
)
from treble.registry.models import Procedure

DEFAULT_CONFIDENCE_THRESHOLD: float = 0.4
DEFAULT_AMBIGUITY_MARGIN: float = 0.08
# Noul run-gate threshold on the calibrated (raw) probability. With the
# registry-grounded gate wording, clear management verbs score ~0.12-0.32 and
# run intents (including bare procedure names) score ~0.52-0.86. We bias the
# gate toward run: it is the dominant convention for a command harness, and
# the safety gates (confirmation for mutating/destructive procedures) cover a
# borderline run that the user meant as a read-only inspection.
RUN_GATE_THRESHOLD: float = 0.35
# Showdown Noul: when the run-target Choice lands within the ambiguity margin,
# the router asks Von whether the request is really about the top pick (and
# not the runner-up). Above this (raw) probability the pick is trusted and
# runs normally; below it, the pick is marked for user confirmation. Below
# the abandon threshold the pick is dropped for clarification instead.
SHOWDOWN_NOUL_TRUST: float = 0.6
SHOWDOWN_ABANDON: float = 0.3


@dataclass(frozen=True)
class DecisionOutcome:
    """What the decision layer concluded for one request."""

    action: Action
    target_name: str | None = None
    confidence: float = 0.0
    probabilities: dict[str, float] = field(default_factory=dict)
    options: dict[str, str] = field(default_factory=dict)
    reason: str = ""
    runner_up: str | None = None  # the second-best candidate, if contested
    confirm: bool = False  # ask the user to confirm before executing


def decide(
    tokens: list[str],
    procedures: list[Procedure],
    client: SystemOneClient,
    *,
    cwd: Path | None = None,
    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
    ambiguity_margin: float = DEFAULT_AMBIGUITY_MARGIN,
    variant: str = "default",
) -> DecisionOutcome:
    """Route ``tokens`` through Von and return the chosen action/target.

    ``procedures`` must be the enabled set in neutral order. ``variant``
    selects the prompt configuration (see ``decision.prompts.VARIANTS``).
    Raises ``httpx.HTTPError``/``httpx.RequestError`` if Von is unreachable;
    the caller fails closed.
    """
    v = get_variant(variant)
    gate_state = build_routing_state(
        tokens, procedures, cwd, extra=v.run_gate_state_extra
    )
    is_run = _run_gate(gate_state, client, v)

    if is_run:
        return _select_run_target(
            tokens, procedures, client, cwd,
            confidence_threshold, ambiguity_margin, v,
        )
    return _route_control(
        tokens, procedures, client, cwd, confidence_threshold, ambiguity_margin
    )


# -- stage 1: run gate (Noul) -------------------------------------------------


def _run_gate(state: str, client: SystemOneClient, variant: Variant) -> bool:
    answer = client.judge(state, NoulQuestion(instructions=variant.run_gate_condition))
    return answer.probability >= RUN_GATE_THRESHOLD


# -- stage 2a: run target ------------------------------------------------------


def _select_run_target(
    tokens: list[str],
    procedures: list[Procedure],
    client: SystemOneClient,
    cwd: Path | None,
    confidence_threshold: float,
    ambiguity_margin: float,
    variant: Variant,
) -> DecisionOutcome:
    if not procedures:
        return DecisionOutcome(
            action=Action.ESCALATE, reason="run request but no registered procedures"
        )
    options = build_run_target_options(procedures)
    answer = client.choose(
        build_routing_state(tokens, procedures, cwd),
        ChoiceQuestion(
            instructions=variant.run_target_instructions, criteria=options
        ),
    )

    # Low-confidence pick: abandon to clarification.
    if answer.winning_probability < confidence_threshold:
        return _clarify(
            answer,
            options,
            f"winning probability {answer.winning_probability:.2f} below "
            f"threshold {confidence_threshold:.2f}",
        )

    if answer.choice == NONE_OF_THE_ABOVE or answer.choice not in options:
        return _escalate(answer, options, "model found no matching procedure to run")

    # Near-tied top two: run the showdown Noul before trusting the pick.
    top = answer.top_two()
    if top is not None:
        (_top_key, _top_p), (runner_key, _runner_p) = top
        margin = _top_p - _runner_p
        if margin < ambiguity_margin:
            return _showdown(
                tokens, answer, options, _top_key, runner_key, client, cwd
            )

    return DecisionOutcome(
        action=Action.SELECT_PROCEDURE,
        target_name=answer.choice,
        confidence=answer.confidence,
        probabilities=answer.probabilities,
        options=options,
        reason="model selected a procedure to run",
    )


def _showdown(
    tokens: list[str],
    answer: ChoiceAnswer,
    options: dict[str, str],
    top_key: str,
    runner_up_key: str,
    client: SystemOneClient,
    cwd: Path | None,
) -> DecisionOutcome:
    """Resolve a near-tied run pick with a Noul; confirm with the user if unsure."""
    from treble.decision.prompts import showdown_condition

    condition = showdown_condition(
        request=" ".join(tokens),
        top=top_key,
        top_description=options.get(top_key, ""),
        runner_up=runner_up_key,
        runner_up_description=options.get(runner_up_key, ""),
    )
    noul: NoulAnswer = client.judge(build_state(tokens, cwd), NoulQuestion(instructions=condition))
    p = noul.probability

    if p >= SHOWDOWN_NOUL_TRUST:
        # The model confidently confirms the top pick: run it normally.
        return DecisionOutcome(
            action=Action.SELECT_PROCEDURE,
            target_name=top_key,
            confidence=p,
            probabilities=answer.probabilities,
            options=options,
            runner_up=runner_up_key,
            reason=f"showdown Noul confirmed {top_key!r} (p={p:.2f})",
        )
    if p >= SHOWDOWN_ABANDON:
        # Unsure: keep the pick but ask the user to confirm before executing.
        return DecisionOutcome(
            action=Action.SELECT_PROCEDURE,
            target_name=top_key,
            confidence=p,
            probabilities=answer.probabilities,
            options=options,
            runner_up=runner_up_key,
            confirm=True,
            reason=f"showdown Noul unsure between {top_key!r}/{runner_up_key!r} (p={p:.2f})",
        )
    # The model does not believe the top pick is right: abandon.
    return _clarify(
        answer,
        options,
        f"showdown Noul rejected top pick {top_key!r} (p={p:.2f})",
    )


# -- stage 2b: control verb (+ optional target) --------------------------------


def _route_control(
    tokens: list[str],
    procedures: list[Procedure],
    client: SystemOneClient,
    cwd: Path | None,
    confidence_threshold: float,
    ambiguity_margin: float,
) -> DecisionOutcome:
    options = build_control_verb_options()
    answer = client.choose(
        build_state(tokens, cwd),
        ChoiceQuestion(instructions=control_verb_instructions(), criteria=options),
    )
    gated = _apply_gates(answer, options, confidence_threshold, ambiguity_margin)
    if gated is not None:
        return gated

    verb = answer.choice
    if verb == NONE_OF_THE_ABOVE or verb not in VERB_TO_ACTION:
        return _escalate(answer, options, "model found no matching management action")
    action = VERB_TO_ACTION[verb]

    if verb not in TARGETED_VERBS:
        return DecisionOutcome(
            action=action,
            confidence=answer.confidence,
            probabilities=answer.probabilities,
            options=options,
            reason="model selected a control action",
        )
    return _select_control_target(
        tokens, verb, action, procedures, client, cwd,
        confidence_threshold, ambiguity_margin,
    )


def _select_control_target(
    tokens: list[str],
    verb: str,
    action: Action,
    procedures: list[Procedure],
    client: SystemOneClient,
    cwd: Path | None,
    confidence_threshold: float,
    ambiguity_margin: float,
) -> DecisionOutcome:
    if not procedures:
        return DecisionOutcome(
            action=Action.ESCALATE, reason=f"{verb} request but no registered procedures"
        )
    options = build_control_target_options(procedures)
    answer = client.choose(
        control_target_state(tokens, verb, procedures, cwd),
        ChoiceQuestion(instructions=control_target_instructions(), criteria=options),
    )
    gated = _apply_gates(answer, options, confidence_threshold, ambiguity_margin)
    if gated is not None:
        return gated
    if answer.choice == NONE_OF_THE_ABOVE or answer.choice not in options:
        return _escalate(answer, options, f"model found no target procedure for {verb}")
    return DecisionOutcome(
        action=action,
        target_name=answer.choice,
        confidence=answer.confidence,
        probabilities=answer.probabilities,
        options=options,
        reason=f"model selected a target for {verb}",
    )


# -- shared helpers -------------------------------------------------------------


def _apply_gates(
    answer: ChoiceAnswer,
    options: dict[str, str],
    confidence_threshold: float,
    ambiguity_margin: float,
) -> DecisionOutcome | None:
    """Return a CLARIFY outcome if the gates trip, else None.

    Gating uses the winning option's probability rather than the raw
    ``confidence`` field: Von's ``confidence`` is deliberately conservative
    for many-way choices, while the probability of the chosen option is the
    actionable routing signal.
    """
    winning = answer.winning_probability
    if winning < confidence_threshold:
        return _clarify(
            answer,
            options,
            f"winning probability {winning:.2f} below threshold {confidence_threshold:.2f}",
        )
    top = answer.top_two()
    if top is not None:
        (_k1, p1), (_k2, p2) = top
        if (p1 - p2) < ambiguity_margin:
            return _clarify(answer, options, "top two options within ambiguity margin")
    return None


def _clarify(answer: ChoiceAnswer, options: dict[str, str], reason: str) -> DecisionOutcome:
    return DecisionOutcome(
        action=Action.CLARIFY,
        confidence=answer.confidence,
        probabilities=answer.probabilities,
        options=options,
        reason=reason,
    )


def _escalate(answer: ChoiceAnswer, options: dict[str, str], reason: str) -> DecisionOutcome:
    return DecisionOutcome(
        action=Action.ESCALATE,
        confidence=answer.confidence,
        probabilities=answer.probabilities,
        options=options,
        reason=reason,
    )
