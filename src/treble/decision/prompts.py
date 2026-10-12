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
    "The developer wants to run one of the registered procedures listed in "
    "the state. Which one should run? Choose 'none-of-the-above' if none of "
    "them fit the request."
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


def build_state(tokens: list[str], cwd: Path | None = None) -> str:
    """The base state string handed to Von (control-verb classification)."""
    return f"Request: {' '.join(tokens)}\nWorking directory: {cwd or Path.cwd()}"


def build_routing_state(
    tokens: list[str], procedures: list[Procedure], cwd: Path | None = None
) -> str:
    """Registry-grounded state for the run gate and run-target stages.

    Grounding the request against the registry lets Von resolve bare or
    partial names against real descriptions; control-verb classification
    works better without it.
    """
    summaries = "\n".join(f"- {p.name}: {p.description}" for p in procedures)
    return (
        f"Request: {' '.join(tokens)}\n"
        f"Working directory: {cwd or Path.cwd()}\n\n"
        f"Registered procedures:\n{summaries}"
    )


def run_gate_condition() -> str:
    return RUN_GATE_CONDITION


def build_run_target_options(procedures: list[Procedure]) -> dict[str, str]:
    """Run-path options: procedure name -> description, plus the escape hatch.

    The name is embedded in the description text: Von attends far more to
    option descriptions than to option keys, so repeating the name grounds a
    literal name in the request ("hello") against the right procedure instead
    of losing it to a verbose neighbouring description. Measured: without the
    embed, "hello" split 0.40/0.43 between two procedures and clarified; with
    it, the literal match wins decisively.
    """
    options = {p.name: f"{p.name}: {p.description}" for p in procedures}
    options[NONE_OF_THE_ABOVE] = "None of the registered procedures fit the request"
    return options


def run_target_instructions() -> str:
    return _RUN_TARGET_INSTRUCTIONS


def build_control_verb_options() -> dict[str, str]:
    return dict(CONTROL_VERB_DESCRIPTIONS)


def control_verb_instructions() -> str:
    return _CONTROL_VERB_INSTRUCTIONS


def build_control_target_options(procedures: list[Procedure]) -> dict[str, str]:
    options = {p.name: p.description for p in procedures}
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
