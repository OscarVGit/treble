"""Run routing scenarios against the decision model and report a matrix.

Each scenario declares an ``intent`` (the raw tokens a user typed), a fixture
``procedures`` registry, and the expected routing outcome. The harness reports
four-way classification per case:

- **correct**   — action (and target, when named) matches the expectation
- **clarified** — the system asked (CLARIFY) instead of acting
- **escalated** — the system punted (ESCALATE) instead of acting
- **wrong**     — the system acted on something other than the expectation

plus two derived safety properties:

- **safe**        — no case classified ``wrong`` on a mutating procedure
- **actionable**  — no case silently executed the wrong thing (``wrong``)

Run against a live Von server by default, or a scripted client offline with
``--fake``. Results are captured to JSONL (``--results``) for regression
diffing and CI gating; the process exits non-zero (2) if any case is
classified ``wrong``.
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import yaml

from treble.config import TrebleConfig
from treble.decision import Action, decide
from treble.decision.protocol import ChoiceAnswer, ChoiceQuestion, NoulAnswer, NoulQuestion
from treble.registry.models import Procedure

_PREFIX_TO_ACTION = {
    "select": Action.SELECT_PROCEDURE,
    "remove": Action.REMOVE_PROCEDURE,
    "show": Action.SHOW,
    "test": Action.TEST,
    "explain": Action.EXPLAIN,
}
_ACTION_TO_VERB = {  # control verbs as they appear in the option keys
    Action.REMOVE_PROCEDURE: "remove",
    Action.SHOW: "show",
    Action.TEST: "test",
    Action.EXPLAIN: "explain",
}

CONCRETE_ACTIONS = {
    Action.SELECT_PROCEDURE,
    Action.REMOVE_PROCEDURE,
    Action.SHOW,
    Action.TEST,
    Action.EXPLAIN,
    Action.LIST,
    Action.ADD_PROCEDURE,
}


@dataclass(frozen=True)
class ScenarioCase:
    """One routing scenario with its expectation."""

    name: str
    intent: list[str]
    procedures: list[Procedure]
    expect_action: Action
    expect_target: str | None
    mutating: bool = False


@dataclass
class CaseResult:
    """Measured outcome for one scenario."""

    name: str
    expected: str
    got: str
    classification: str
    safe: bool
    probabilities: dict[str, float] = field(default_factory=dict)
    latency_ms: float = 0.0
    model_calls: int = 0
    result: str = "ok"
    error: str | None = None

    def to_json(self) -> str:
        return json.dumps(
            {
                "case": self.name,
                "expected": self.expected,
                "got": self.got,
                "classification": self.classification,
                "safe": self.safe,
                "probabilities": self.probabilities,
                "latency_ms": self.latency_ms,
                "model_calls": self.model_calls,
                "result": self.result,
                "error": self.error,
            },
            sort_keys=True,
        )


class CountingClient:
    """Wrap a SystemOneClient and count model calls for the metrics."""

    def __init__(self, inner: object) -> None:
        self._inner = inner
        self.calls = 0

    def judge(self, state: str, question: NoulQuestion) -> NoulAnswer:
        self.calls += 1
        return self._inner.judge(state, question)  # type: ignore[attr-defined]

    def choose(self, state: str, question: ChoiceQuestion) -> ChoiceAnswer:
        self.calls += 1
        return self._inner.choose(state, question)  # type: ignore[attr-defined]


def _load_cases(path: Path) -> list[ScenarioCase]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "cases" not in data:
        msg = f"scenario file {path} must contain a top-level 'cases' list"
        raise SystemExit(msg)
    cases: list[ScenarioCase] = []
    for raw in data["cases"]:
        action, target = _expected(str(raw["expect"]))
        cases.append(
            ScenarioCase(
                name=str(raw["name"]),
                intent=[str(t) for t in raw["intent"]],
                procedures=[Procedure.model_validate(p) for p in raw["procedures"]],
                expect_action=action,
                expect_target=target,
                mutating=bool(raw.get("mutating", False)),
            )
        )
    return cases


def _expected(expect: str) -> tuple[Action, str | None]:
    if expect in ("clarify", "escalate", "list", "add"):
        return {
            "clarify": Action.CLARIFY,
            "escalate": Action.ESCALATE,
            "list": Action.LIST,
            "add": Action.ADD_PROCEDURE,
        }[expect], None
    prefix, _, name = expect.partition(":")
    action = _PREFIX_TO_ACTION.get(prefix)
    if action is None or not name:
        msg = f"unrecognised expectation {expect!r}"
        raise SystemExit(msg)
    return action, name


def _classify(case: ScenarioCase, outcome: object) -> str:
    """Classify one scenario outcome into correct/clarified/escalated/wrong."""
    action = outcome.action  # type: ignore[attr-defined]
    target = outcome.target_name  # type: ignore[attr-defined]
    if action == case.expect_action and (
        case.expect_target is None or target == case.expect_target
    ):
        return "correct"
    if action == Action.CLARIFY:
        return "clarified"
    if action == Action.ESCALATE:
        return "escalated"
    return "wrong"


def _evaluate_case(case: ScenarioCase, client: object, variant: str) -> CaseResult:
    counting = CountingClient(client)
    expected = (
        f"{case.expect_action.value}:{case.expect_target}"
        if case.expect_target
        else case.expect_action.value
    )
    start = time.perf_counter()
    try:
        outcome = decide(case.intent, case.procedures, counting, variant=variant)
    except (httpx.HTTPError, httpx.RequestError, OSError, ValueError) as exc:
        # Model unreachable, or a bad variant/response: record as an error
        # case instead of crashing the whole eval run.
        latency = (time.perf_counter() - start) * 1000
        return CaseResult(
            name=case.name,
            expected=expected,
            got="error",
            classification="error",
            safe=False,
            latency_ms=latency,
            model_calls=counting.calls,
            result="error",
            error=f"{exc.__class__.__name__}: {exc}",
        )
    latency = (time.perf_counter() - start) * 1000

    got_action = outcome.action.value
    got = f"{got_action}:{outcome.target_name}" if outcome.target_name else got_action
    classification = _classify(case, outcome)
    safe = not (classification == "wrong" and case.mutating)
    return CaseResult(
        name=case.name,
        expected=expected,
        got=got,
        classification=classification,
        safe=safe,
        probabilities=dict(outcome.probabilities),
        latency_ms=latency,
        model_calls=counting.calls,
    )


def run(
    path: Path,
    *,
    use_fake: bool,
    variant: str = "default",
    results_path: Path | None = None,
) -> int:
    """Run one scenario file; print a matrix + summary; return an exit code."""
    cases = _load_cases(path)
    results: list[CaseResult] = [
        _evaluate_case(case, _make_client(case, use_fake), variant) for case in cases
    ]

    matrix = {"correct": 0, "clarified": 0, "escalated": 0, "wrong": 0, "error": 0}
    for r in results:
        matrix[r.classification] = matrix.get(r.classification, 0) + 1

    total = len(results)
    safe = all(r.safe for r in results)
    actionable = not any(r.classification == "wrong" for r in results)
    errored = any(r.classification == "error" for r in results)
    total_model_calls = sum(r.model_calls for r in results)
    total_latency = sum(r.latency_ms for r in results)

    # --- stdout summary -----------------------------------------------------
    print(f"[{variant}] {matrix['correct']}/{total} correct  "
          f"(clarified={matrix['clarified']} escalated={matrix['escalated']} "
          f"wrong={matrix['wrong']} error={matrix['error']})")
    print(f"  safe={safe} actionable={actionable} "
          f"model_calls={total_model_calls} avg_latency_ms={total_latency/total:.1f}")
    for r in results:
        tag = {"correct": "PASS", "clarified": "CLAR", "escalated": "ESC",
               "wrong": "WRNG", "error": "ERR "}[r.classification]
        line = f"  {tag} {r.name}: want {r.expected}, got {r.got}"
        if r.classification == "error" and r.error:
            line += f" ({r.error})"
        print(line)

    if results_path is not None:
        results_path.parent.mkdir(parents=True, exist_ok=True)
        with results_path.open("a", encoding="utf-8") as fh:
            for r in results:
                fh.write(json.dumps({"variant": variant, **json.loads(r.to_json())}) + "\n")
        print(f"  wrote {results_path}")

    if matrix["wrong"] > 0:
        return 2
    if errored:
        return 1
    return 0


def _make_client(case: ScenarioCase, use_fake: bool):
    if not use_fake:
        from treble.decision import default_client

        return default_client(TrebleConfig.load())

    from treble.decision.testing import FakeSystemOneClient, make_answer

    def spread(options: dict[str, str], winner: str, p: float = 0.95) -> dict[str, float]:
        probs = {k: 0.001 for k in options}
        probs[winner] = p
        return probs

    run_path = case.expect_action is Action.SELECT_PROCEDURE

    if case.expect_action is Action.CLARIFY:
        options = _gate_options(case)
        first = next(iter(options))
        probs = {k: 0.2 for k in options}
        return FakeSystemOneClient(noul_probability=0.9, answer=make_answer(first, probs))

    if case.expect_action is Action.ESCALATE:
        # A real escalate happens on the run path: the gate says "run", and the
        # run-target Choice returns none-of-the-above. With an empty registry
        # the gate short-circuits before the Choice, so the answer is unused.
        from treble.decision.prompts import NONE_OF_THE_ABOVE, build_run_target_options

        options = build_run_target_options(case.procedures)
        return FakeSystemOneClient(
            noul_probability=0.9,
            answer=make_answer(NONE_OF_THE_ABOVE, spread(options, NONE_OF_THE_ABOVE)),
        )

    if run_path:
        from treble.decision.prompts import build_run_target_options

        options = build_run_target_options(case.procedures)
        return FakeSystemOneClient(
            noul_probability=0.9,
            answer=make_answer(case.expect_target, spread(options, str(case.expect_target))),
        )

    # Control path: verb Choice, then target Choice if targeted.
    from treble.decision.prompts import NONE_OF_THE_ABOVE, build_control_verb_options

    verb_opts = build_control_verb_options()
    verb = (
        case.expect_action.value
        if case.expect_target is None
        else _ACTION_TO_VERB[case.expect_action]
    )
    answers = [make_answer(verb, spread(verb_opts, verb))]
    if case.expect_target is not None:
        target_opts = {p.name: p.description for p in case.procedures}
        target_opts[NONE_OF_THE_ABOVE] = "none"
        answers.append(make_answer(case.expect_target, spread(target_opts, case.expect_target)))
    return FakeSystemOneClient(noul_probability=0.1, answers=answers)


def _gate_options(case: ScenarioCase) -> dict[str, str]:
    """The option set the gate path would consult for a clarify/escalate."""
    from treble.decision.prompts import build_control_verb_options, build_run_target_options

    if case.expect_action is Action.SELECT_PROCEDURE:
        return build_run_target_options(case.procedures)
    return build_control_verb_options()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", type=Path)
    parser.add_argument("--fake", action="store_true", help="use a scripted client (offline)")
    parser.add_argument("--variant", default="default", help="prompt variant to run")
    parser.add_argument("--results", type=Path, default=None, help="append JSONL here")
    args = parser.parse_args()
    raise SystemExit(
        run(
            args.scenario,
            use_fake=args.fake,
            variant=args.variant,
            results_path=args.results,
        )
    )
