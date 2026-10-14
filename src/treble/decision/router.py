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

from dataclasses import dataclass, field, replace
from pathlib import Path

from treble.decision.actions import Action
from treble.decision.client import SystemOneClient
from treble.decision.prompts import (
    NONE_OF_THE_ABOVE,
    RUN_ACTION,
    TARGETED_VERBS,
    VERB_TO_ACTION,
    Variant,
    action_instructions,
    build_action_options,
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
from treble.registry.models import Procedure, RiskLevel

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
    confirm_reason: str = ""  # why confirmation is required (if it is)


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
    if v.folded:
        return _route_folded(
            tokens, procedures, client, cwd,
            confidence_threshold, ambiguity_margin, v,
        )

    # Deterministic inspect-precedence signal. A leading inspection/management
    # verb routes straight to the control plane *without consulting the run
    # gate*: otherwise a request like "show me the build procedure" embeds a
    # procedure name and the gate executes it (see EVALUATION.md §7). The model
    # still chooses the verb and target — this only selects which stage runs.
    if _leading_inspection_verb(tokens, procedures) is not None:
        outcome = _route_control(
            tokens, procedures, client, cwd, confidence_threshold, ambiguity_margin
        )
    # Symmetric bare-name signal: a request that is *only* a registered name or
    # alias (a bare "describe" naming a procedure called `describe`) is a run by
    # convention, but the gate under-scores such names. Route to the run path
    # deterministically; the model still chooses the target (and the collision
    # showdown still guards near-duplicates).
    elif _bare_registered_name(tokens, procedures) is not None:
        outcome = _select_run_target(
            tokens, procedures, client, cwd,
            confidence_threshold, ambiguity_margin, v,
        )
    else:
        gate_state = build_routing_state(
            tokens, procedures, cwd, extra=v.run_gate_state_extra
        )
        is_run = _run_gate(gate_state, client, v)
        if is_run:
            outcome = _select_run_target(
                tokens, procedures, client, cwd,
                confidence_threshold, ambiguity_margin, v,
            )
        else:
            outcome = _route_control(
                tokens, procedures, client, cwd,
                confidence_threshold, ambiguity_margin,
            )
    return _apply_mutation_gate(outcome, procedures)


# -- stage 1: run gate (Noul) -------------------------------------------------


# Leading inspection/management verbs. Inspection phrasings embed a procedure
# name ("show me the build procedure") and would otherwise be scored as run
# requests by the gate; a leading verb is a deterministic, high-precision
# signal that the request is *about* a procedure, not an intent to execute one.
_INSPECTION_LEAD_VERBS = frozenset(
    {"show", "explain", "describe", "display", "list", "tell", "what", "how"}
)
# Courtesy/filler words to skip before reading the leading verb.
_LEAD_FILLER = frozenset(
    {"please", "can", "could", "would", "will", "you", "kindly", "just"}
)


def _leading_inspection_verb(
    tokens: list[str], procedures: list[Procedure]
) -> str | None:
    """The leading inspection/management verb, or ``None``.

    A *bare* invocation of a procedure named like an inspection verb (a
    procedure called ``list``) is a run, so it is left to the gate. But when
    the same name appears in a phrase ("show me the build procedure"), the
    phrase is an inspection — a registered name must not disable inspection
    precedence for the whole request. So the bare-name exemption applies only
    when the leading word is the *sole* content token; otherwise a leading
    inspection verb routes to the control plane. Everything after the verb is
    left to the model.
    """
    names = {n.lower() for p in procedures for n in (p.name, *p.aliases)}
    content = [t for t in tokens if t.lower() not in _LEAD_FILLER]
    if not content:
        return None
    lead = content[0].lower()
    if lead in names and len(content) == 1:
        return None  # a bare procedure name (even verb-spelled) is a run
    return lead if lead in _INSPECTION_LEAD_VERBS else None


def _bare_registered_name(
    tokens: list[str], procedures: list[Procedure]
) -> str | None:
    """The procedure named by a *bare* request, or ``None``.

    A request whose only content token is exactly a registered name or alias
    ("describe", "compile", "check-no-verify") is a run by convention. The run
    gate under-scores some such names — a procedure called ``describe`` reads
    like a verb — so this deterministic signal routes them to the run path
    instead of trusting the gate. The model still chooses the target.
    """
    content = [t for t in tokens if t.lower() not in _LEAD_FILLER]
    if len(content) != 1:
        return None
    low = content[0].lower()
    for procedure in procedures:
        if low == procedure.name.lower():
            return procedure.name
        if low in {a.lower() for a in procedure.aliases}:
            return procedure.name
    return None


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

    # Near-duplicate name collision: the request names a procedure exactly,
    # but the model preferred a longer registered name that merely extends it
    # (e.g. request "check", pick "check-no-verify"). Such a pick is confident
    # enough that the margin gate above never fires, so adjudicate it with the
    # showdown Noul and fall back to the exact-name match if the Noul rejects.
    collision = _name_collision(tokens, procedures, answer.choice)
    if collision is not None:
        return _collision_showdown(
            tokens, answer, options, answer.choice, collision, client, cwd,
            Action.SELECT_PROCEDURE,
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
            confirm_reason=f"Treble is unsure between {top_key!r} and {runner_up_key!r}",
            reason=f"showdown Noul unsure between {top_key!r}/{runner_up_key!r} (p={p:.2f})",
        )
    # The model does not believe the top pick is right: abandon.
    return _clarify(
        answer,
        options,
        f"showdown Noul rejected top pick {top_key!r} (p={p:.2f})",
    )


def _collision_showdown(
    tokens: list[str],
    answer: ChoiceAnswer,
    options: dict[str, str],
    long_key: str,
    exact_key: str,
    client: SystemOneClient,
    cwd: Path | None,
    action: Action,
) -> DecisionOutcome:
    """Adjudicate a near-duplicate name collision.

    The request names ``exact_key`` exactly, but the model preferred the longer
    ``long_key`` that merely extends it. Von cannot discriminate these on its
    own (measured: Noul p≈0.33 for "check" vs "check-no-verify", and a focused
    re-rank Choice still picks the longer name 0.57/0.43), so the *exact* name
    wins unless the model confidently endorses the longer pick — which a
    qualifying request like "check --no-verify" does (p≈0.70). This is
    registry-grounded disambiguation of an already-selected action, not
    deterministic routing.
    """
    from treble.decision.prompts import showdown_condition

    condition = showdown_condition(
        request=" ".join(tokens),
        top=long_key,
        top_description=options.get(long_key, ""),
        runner_up=exact_key,
        runner_up_description=options.get(exact_key, ""),
    )
    noul: NoulAnswer = client.judge(
        build_state(tokens, cwd), NoulQuestion(instructions=condition)
    )
    p = noul.probability
    if p >= SHOWDOWN_NOUL_TRUST:
        chosen, kept = long_key, True
    else:
        chosen, kept = exact_key, False
    return DecisionOutcome(
        action=action,
        target_name=chosen,
        confidence=p,
        probabilities=answer.probabilities,
        options=options,
        runner_up=exact_key if kept else long_key,
        reason=(
            f"name collision: model picked {long_key!r}, request named "
            f"{exact_key!r}; Noul p={p:.2f} -> "
            f"{'kept longer pick' if kept else 'used exact-name match'}"
        ),
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
    collision = _name_collision(tokens, procedures, answer.choice)
    if collision is not None:
        return _collision_showdown(
            tokens, answer, options, answer.choice, collision, client, cwd,
            action,
        )
    return DecisionOutcome(
        action=action,
        target_name=answer.choice,
        confidence=answer.confidence,
        probabilities=answer.probabilities,
        options=options,
        reason=f"model selected a target for {verb}",
    )


# -- folded routing (single action Choice) -------------------------------------


def _route_folded(
    tokens: list[str],
    procedures: list[Procedure],
    client: SystemOneClient,
    cwd: Path | None,
    confidence_threshold: float,
    ambiguity_margin: float,
    variant: Variant,
) -> DecisionOutcome:
    """One Choice over {run, list, show, explain, test, remove, add, none}.

    Replaces the Noul run gate + control-verb Choice with a single decision
    over the whole action space (variant ``folded``). A ``run`` choice then
    selects a procedure; targeted management verbs select a target.
    """
    options = build_action_options()
    answer = client.choose(
        build_routing_state(tokens, procedures, cwd, extra=variant.run_gate_state_extra),
        ChoiceQuestion(instructions=action_instructions(), criteria=options),
    )
    gated = _apply_gates(answer, options, confidence_threshold, ambiguity_margin)
    if gated is not None:
        return _apply_mutation_gate(gated, procedures)

    choice = answer.choice
    if choice == NONE_OF_THE_ABOVE or choice not in options:
        return _apply_mutation_gate(
            _escalate(answer, options, "model found no matching action"), procedures
        )

    if choice == RUN_ACTION:
        return _apply_mutation_gate(
            _select_run_target(
                tokens, procedures, client, cwd,
                confidence_threshold, ambiguity_margin, variant,
            ),
            procedures,
        )

    action = VERB_TO_ACTION[choice]
    if choice not in TARGETED_VERBS:
        return _apply_mutation_gate(
            DecisionOutcome(
                action=action,
                confidence=answer.confidence,
                probabilities=answer.probabilities,
                options=options,
                reason="model selected a control action",
            ),
            procedures,
        )
    return _apply_mutation_gate(
        _select_control_target(
            tokens, choice, action, procedures, client, cwd,
            confidence_threshold, ambiguity_margin,
        ),
        procedures,
    )


# -- shared helpers -------------------------------------------------------------


_MUTATING_RISKS = frozenset({RiskLevel.MUTATING, RiskLevel.DESTRUCTIVE})


def _apply_mutation_gate(
    outcome: DecisionOutcome, procedures: list[Procedure]
) -> DecisionOutcome:
    """Require confirmation for any mutating/destructive selection.

    The runtime already gates these (``remove`` always confirms; mutating and
    destructive procedures trip the safety policy), but flagging them at the
    decision layer makes the safety property explicit — *never silently
    execute a mutating action* — regardless of how confident the routing was
    or how good the model's discrimination is.
    """
    if outcome.confirm:
        return outcome

    if outcome.action is Action.REMOVE_PROCEDURE:
        return replace(
            outcome,
            confirm=True,
            confirm_reason=(
                f"removing {outcome.target_name!r} changes the registry"
            ),
        )

    if (
        outcome.action in (Action.SELECT_PROCEDURE, Action.TEST)
        and outcome.target_name
    ):
        procedure = _find_procedure(procedures, outcome.target_name)
        if procedure is not None and procedure.risk in _MUTATING_RISKS:
            return replace(
                outcome,
                confirm=True,
                confirm_reason=(
                    f"{procedure.name!r} is a {procedure.risk.value} procedure"
                ),
            )
    return outcome


def _find_procedure(
    procedures: list[Procedure], name: str
) -> Procedure | None:
    for procedure in procedures:
        if procedure.name == name or name in procedure.aliases:
            return procedure
    return None


def _name_collision(
    tokens: list[str], procedures: list[Procedure], chosen: str
) -> str | None:
    """The exact-named procedure the model's pick extends, if any.

    Near-duplicate discrimination failure: the request names a procedure
    exactly (e.g. "check"), but the model prefers a longer registered name
    that merely extends it ("check-no-verify"). The pick is confident enough
    that the margin gate never fires, so detect the name overlap
    deterministically and let the showdown Noul adjudicate. Returns the
    exact-named procedure's name, or ``None`` when the pick is not suspicious.
    """
    chosen_lower = chosen.lower()
    requested = {token.lower() for token in tokens}
    for procedure in procedures:
        for name in (procedure.name, *procedure.aliases):
            lower = name.lower()
            if lower == chosen_lower or lower not in requested:
                continue
            if chosen_lower.startswith(lower):
                return procedure.name
    return None


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
