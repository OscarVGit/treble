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
    build_control_target_options,
    build_control_verb_options,
    build_routing_state,
    build_run_target_options,
    build_state,
    control_target_instructions,
    control_target_state,
    control_verb_instructions,
    run_gate_condition,
    run_target_instructions,
)
from treble.decision.protocol import (
    ChoiceAnswer,
    ChoiceQuestion,
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


@dataclass(frozen=True)
class DecisionOutcome:
    """What the decision layer concluded for one request."""

    action: Action
    target_name: str | None = None
    confidence: float = 0.0
    probabilities: dict[str, float] = field(default_factory=dict)
    options: dict[str, str] = field(default_factory=dict)
    reason: str = ""


def decide(
    tokens: list[str],
    procedures: list[Procedure],
    client: SystemOneClient,
    *,
    cwd: Path | None = None,
    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
    ambiguity_margin: float = DEFAULT_AMBIGUITY_MARGIN,
) -> DecisionOutcome:
    """Route ``tokens`` through Von and return the chosen action/target.

    ``procedures`` must be the enabled set in neutral order. Raises
    ``httpx.HTTPError``/``httpx.RequestError`` if Von is unreachable; the
    caller fails closed.
    """
    state = build_routing_state(tokens, procedures, cwd)
    is_run = _run_gate(state, client)

    if is_run:
        return _select_run_target(
            tokens, procedures, client, cwd, confidence_threshold, ambiguity_margin
        )
    return _route_control(
        tokens, procedures, client, cwd, confidence_threshold, ambiguity_margin
    )


# -- stage 1: run gate (Noul) -------------------------------------------------


def _run_gate(state: str, client: SystemOneClient) -> bool:
    answer = client.judge(state, NoulQuestion(instructions=run_gate_condition()))
    return answer.probability >= RUN_GATE_THRESHOLD


# -- stage 2a: run target ------------------------------------------------------


def _select_run_target(
    tokens: list[str],
    procedures: list[Procedure],
    client: SystemOneClient,
    cwd: Path | None,
    confidence_threshold: float,
    ambiguity_margin: float,
) -> DecisionOutcome:
    if not procedures:
        return DecisionOutcome(
            action=Action.ESCALATE, reason="run request but no registered procedures"
        )
    options = build_run_target_options(procedures)
    answer = client.choose(
        build_routing_state(tokens, procedures, cwd),
        ChoiceQuestion(instructions=run_target_instructions(), criteria=options),
    )
    gated = _apply_gates(answer, options, confidence_threshold, ambiguity_margin)
    if gated is not None:
        return gated
    if answer.choice == NONE_OF_THE_ABOVE or answer.choice not in options:
        return _escalate(answer, options, "model found no matching procedure to run")
    return DecisionOutcome(
        action=Action.SELECT_PROCEDURE,
        target_name=answer.choice,
        confidence=answer.confidence,
        probabilities=answer.probabilities,
        options=options,
        reason="model selected a procedure to run",
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
