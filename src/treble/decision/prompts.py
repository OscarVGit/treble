"""State and option construction for Von routing calls.

Routing is decomposed into primitives Von is good at, all handled by the
model (never by string matching):

1. **Run gate (Noul)** — "is this a request to run/execute a procedure?"
   separates the dominant execution path from the control plane.
2. **Target (Choice)** — for a run, pick the procedure (by name) with
   descriptions as the option text.
3. **Control verb (Choice)** — for a non-run, pick the management verb
   (list/show/explain/test/remove/add), then a target Choice if targeted.

Option keys are bare procedure names / verbs, so the returned key is the
answer — no parsing of natural-language model output.
"""

from __future__ import annotations

from pathlib import Path

from treble.decision.actions import Action
from treble.registry.models import Procedure

NONE_OF_THE_ABOVE = "none-of-the-above"

# Stage-1: the run gate (Noul condition). Evaluated against the
# registry-grounded routing state. The wording is deliberate: short requests
# that name a procedure (including a single bare word) must read as execution
# requests, while explicit management verbs read as control-plane requests.
RUN_GATE_CONDITION = (
    "Is the developer asking to execute or run one of the listed procedures? "
    "Treat a short request that names a procedure — including a single word "
    "such as 'hello', 'build', or 'check' — as a request to run it. "
    "Answer no for requests to list, show, explain, test, remove, or add "
    "procedures, and for requests unrelated to running a command."
)

# Stage-2 (run path): which procedure to execute.
_RUN_TARGET_INSTRUCTIONS = (
    "Which registered procedure does this request refer to? Select the "
    "procedure exactly named or most clearly described by the request."
)

# Stage-2 (control path): which management verb.
CONTROL_VERB_DESCRIPTIONS: dict[str, str] = {
    "list": "List all registered procedures",
    "show": "Show the stored definition of one specific procedure",
    "explain": "Explain the execution plan of a procedure before running it",
    "test": "Run a procedure in test mode to check it works",
    "remove": "Remove, delete, or unregister an existing procedure",
    "add": "Add or register a new procedure",
    NONE_OF_THE_ABOVE: "None of these procedure-management actions fit",
}

_CONTROL_VERB_INSTRUCTIONS = (
    "The developer is managing command procedures, not running one. "
    "Which single management action are they asking for?"
)

# Map the control verb key to its finite action.
VERB_TO_ACTION: dict[str, Action] = {
    "list": Action.LIST,
    "show": Action.SHOW,
    "explain": Action.EXPLAIN,
    "test": Action.TEST,
    "remove": Action.REMOVE_PROCEDURE,
    "add": Action.ADD_PROCEDURE,
}

# Control verbs that operate on a specific procedure (need a target stage).
TARGETED_VERBS: frozenset[str] = frozenset({"show", "explain", "test", "remove"})

_CONTROL_TARGET_INSTRUCTIONS = (
    "Which registered procedure is the target of this request?"
)

# Folded routing (variant "folded"): one Choice over "run" plus the management
# verbs, replacing the Noul run gate + separate control-verb Choice. Von's
# Choice is its strongest primitive; the hypothesis is that a single decision
# over the full action space discriminates run-vs-inspect better than a binary
# Noul gate followed by a verb Choice.
RUN_ACTION = "run"

_ACTION_DESCRIPTIONS: dict[str, str] = {
    RUN_ACTION: "Run or execute one of the registered procedures",
    **CONTROL_VERB_DESCRIPTIONS,
}

_ACTION_INSTRUCTIONS = (
    "The developer either wants to run a registered procedure or to manage the "
    "registry. Choose 'run' to execute a procedure, or the matching management "
    "action (list, show, explain, test, remove, add)."
)


def build_action_options() -> dict[str, str]:
    return dict(_ACTION_DESCRIPTIONS)


def action_instructions() -> str:
    return _ACTION_INSTRUCTIONS


# -- Prompt variants (A/B measurement) -----------------------------------------
#
# A Variant swaps the exact strings the decision layer sends to Von. The
# default variant is the production behaviour; variants exist so evals can
# measure prompt changes as a recorded delta instead of a vibe. Keep variants
# minimal and named for the hypothesis they test.


from dataclasses import dataclass


@dataclass(frozen=True)
class Variant:
    """A named prompt configuration for A/B measurement."""

    name: str
    run_gate_condition: str = RUN_GATE_CONDITION
    run_gate_state_extra: str = ""
    run_target_instructions: str = _RUN_TARGET_INSTRUCTIONS
    folded: bool = False


VARIANTS: dict[str, Variant] = {}


def get_variant(name: str) -> Variant:
    """Return the named variant, or raise with the available names."""
    try:
        return VARIANTS[name]
    except KeyError:
        available = ", ".join(sorted(VARIANTS))
        raise ValueError(f"unknown prompt variant {name!r}; available: {available}") from None


DEFAULT_VARIANT = Variant(name="default")


VARIANTS[DEFAULT_VARIANT.name] = DEFAULT_VARIANT

# Hypothesis: the default run-gate condition is multi-clause policy prose —
# Von's weakest tier per its own model card. A short classifier instruction,
# with the domain rule ("bare name = run") moved into the state as a framing
# line, should improve gate accuracy and calibration.
VARIANTS["compact-gate"] = Variant(
    name="compact-gate",
    run_gate_condition="Is this a request to run a registered procedure?",
    run_gate_state_extra=(
        "Short requests that name a procedure count as run requests; "
        "list/show/explain/test/remove/add are management requests."
    ),
)

# Hypothesis: replace the Noul run gate + control-verb Choice with a single
# Choice over {run, list, show, explain, test, remove, add, none}. One decision
# over the full action space should separate run from inspect/management better
# than a binary Noul (Von's weakest tier) followed by a verb Choice.
# FALSIFIED (see EVALUATION.md): 'run' dominates the control/escalate cases.
VARIANTS["folded"] = Variant(name="folded", folded=True)

# Hypothesis: the default gate loses inspection requests that embed a
# procedure name ("show me the build procedure") because the bare-name rule
# dominates. This variant gives explicit inspection verbs precedence over an
# embedded name, so "show/explain/describe/display/list X" answers no even
# though it names a procedure.
RUN_GATE_CONDITION_VERB_FIRST = (
    "Is the developer asking to execute or run one of the listed procedures? "
    "If the request asks to show, explain, describe, display, list, or tell "
    "about a procedure — even when it names one — answer no: that is an "
    "inspection request, not execution. Treat a request as execution only when "
    "it asks to run or execute a procedure, or names one with no inspection "
    "verb. Answer no for requests unrelated to running a command."
)
VARIANTS["verb-first-gate"] = Variant(
    name="verb-first-gate",
    run_gate_condition=RUN_GATE_CONDITION_VERB_FIRST,
)


def build_state(tokens: list[str], cwd: Path | None = None) -> str:
    """The base state string handed to Von (control-verb classification)."""
    return f"Request: {' '.join(tokens)}\nWorking directory: {cwd or Path.cwd()}"


def describe_procedure(procedure: Procedure) -> str:
    """A self-contained, unambiguous description of one procedure.

    Von attests far more to option text than to option keys, so every
    signal that can disambiguate a procedure is folded into the text:
    name, description, and the exact command vector (plus aliases when
    present). Measured: including the argv fixed a bare-name miss that
    plain "name: description" loses on a crowded registry ("hello" split
    0.36/0.26 and clarified; with the command text it wins decisively).
    """
    parts = [f"{procedure.name}: {procedure.description}"]
    parts.append(f"command: {' '.join(procedure.invocation())}")
    if procedure.aliases:
        parts.append(f"aliases: {', '.join(procedure.aliases)}")
    return " — ".join(parts)


def _registry_summary(procedures: list[Procedure]) -> str:
    return "\n".join(f"- {describe_procedure(p)}" for p in procedures)


def build_routing_state(
    tokens: list[str],
    procedures: list[Procedure],
    cwd: Path | None = None,
    extra: str = "",
) -> str:
    """Registry-grounded state for the run gate and run-target stages.

    The registry summary here stays compact (name: description). The full
    command/alias context lives in the *option text*, not the state:
    repeating it in both diluted the model's probabilities (measured: hello
    dropped to 0.35 and clarified). Control-verb classification works better
    without the registry entirely. ``extra`` is an optional framing line used
    by prompt variants (e.g. compact-gate) and appended before the registry.
    """
    summaries = "\n".join(f"- {p.name}: {p.description}" for p in procedures)
    text = (
        f"Request: {' '.join(tokens)}\n"
        f"Working directory: {cwd or Path.cwd()}\n"
    )
    if extra:
        text += f"{extra}\n"
    text += f"\nRegistered procedures:\n{summaries}"
    return text


def run_gate_condition() -> str:
    return RUN_GATE_CONDITION


def build_run_target_options(procedures: list[Procedure]) -> dict[str, str]:
    """Run-path options: procedure name -> enriched description + escape hatch.

    Option text uses ``describe_procedure`` so Von sees the name,
    description and exact command vector; see ``describe_procedure`` for the
    rationale.
    """
    options = {p.name: describe_procedure(p) for p in procedures}
    options[NONE_OF_THE_ABOVE] = "None of the registered procedures fit the request"
    return options


def run_target_instructions() -> str:
    return _RUN_TARGET_INSTRUCTIONS


def build_control_verb_options() -> dict[str, str]:
    return dict(CONTROL_VERB_DESCRIPTIONS)


def control_verb_instructions() -> str:
    return _CONTROL_VERB_INSTRUCTIONS


def build_control_target_options(procedures: list[Procedure]) -> dict[str, str]:
    """Control-path target options: name + description + command text.

    Same rationale as the run-target options — Von needs the full procedure
    context in the option text, not just a bare description, to anchor a
    literal name in a management request like "remove the hello procedure".
    """
    options = {p.name: describe_procedure(p) for p in procedures}
    options[NONE_OF_THE_ABOVE] = "None of the registered procedures is the target"
    return options


def control_target_instructions() -> str:
    return _CONTROL_TARGET_INSTRUCTIONS


def control_target_state(
    tokens: list[str], verb: str, procedures: list[Procedure], cwd: Path | None = None
) -> str:
    summaries = "\n".join(f"- {p.name}: {p.description}" for p in procedures)
    return (
        f"The developer wants to {verb.upper()} a registered procedure.\n"
        f"Original request: {' '.join(tokens)}\n"
        f"Working directory: {cwd or Path.cwd()}\n\n"
        f"Registered procedures:\n{summaries}"
    )


def showdown_condition(
    request: str,
    top: str,
    top_description: str,
    runner_up: str,
    runner_up_description: str,
) -> str:
    """Noul condition for the showdown gate: is the top pick the right one?

    Used when the run-target Choice is nearly tied. The request is quoted so
    the model re-reads the original intent; both candidates are named so the
    answer discriminates rather than simply affirming the top option.
    """
    return (
        f"Treble is choosing which registered procedure to run for the request "
        f"{request!r}. The top candidate is {top!r} ({top_description}) and "
        f"the runner-up is {runner_up!r} ({runner_up_description}). "
        f"Does the request really refer to {top!r}?"
    )
