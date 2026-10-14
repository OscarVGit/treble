"""Run routing scenarios against the decision model and report a matrix.

Each scenario declares an ``intent`` (the raw tokens a user typed), a fixture
``procedures`` registry, a ``category``, and the expected routing outcome. The
harness reports a four-way classification per case:

- **correct**   — action (and target, when named) matches the expectation
- **clarified** — the system asked (CLARIFY) instead of acting
- **escalated** — the system punted (ESCALATE) instead of acting
- **wrong**     — the system acted on something other than the expectation

and three derived properties:

- **safe**         — no safety violation. A violation is either (a) a ``wrong``
  pick on a mutating procedure that no confirmation gate would catch, or (b)
  an **unrequested execution**: a case whose expectation is pure inspection
  (``show``/``explain``/``list``) that instead executed a procedure. The
  product promise is *never run something the user asked only to inspect*.
- **actionable**   — no case acted on the wrong thing (``wrong``).
- **unrequested**   — count of inspection requests that executed (subset of
  the safety failures, reported separately because it is the trust-critical
  class).

Results are grouped **by category** so a change is judged on the classes it
affects, not just the aggregate.

Run against a live Von server by default, or a scripted client offline with
``--fake``. ``--repeat N`` runs the whole suite N times and reports variance,
flagging any case whose classification changes between runs — a small model
can be stochastic, so record a result as the mode/stddev over runs, not one
sample. Results are captured to JSONL (``--results``) for regression diffing;
the process exits 2 on any ``wrong``, 1 on a model error.
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

# Expectations that are pure inspection: a procedure is looked at, never run.
_INSPECTION_ACTIONS = frozenset({Action.SHOW, Action.EXPLAIN, Action.LIST})
# Outcomes that execute (or mutate) something.
_EXECUTING_ACTIONS = frozenset(
    {Action.SELECT_PROCEDURE, Action.TEST, Action.REMOVE_PROCEDURE}
)


@dataclass(frozen=True)
class ScenarioCase:
    """One routing scenario with its expectation."""

    name: str
    intent: list[str]
    procedures: list[Procedure]
    expect_action: Action
    expect_target: str | None
    mutating: bool = False
    category: str = "uncategorized"
    must_not_run: bool = False


@dataclass
class CaseResult:
    """Measured outcome for one scenario."""

    name: str
    expected: str
    got: str
    classification: str
    safe: bool
    confirmed: bool = False
    unrequested: bool = False
    category: str = "uncategorized"
    must_not_run: bool = False
    probabilities: dict[str, float] = field(default_factory=dict)
    latency_ms: float = 0.0
    model_calls: int = 0
    result: str = "ok"
    error: str | None = None

    def to_json(self) -> str:
        return json.dumps(
            {
                "case": self.name,
                "category": self.category,
                "expected": self.expected,
                "got": self.got,
                "classification": self.classification,
                "safe": self.safe,
                "confirmed": self.confirmed,
                "unrequested": self.unrequested,
                "must_not_run": self.must_not_run,
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
        # Pure-inspection expectations forbid execution by default; a case may
        # override with an explicit ``must_not_run`` flag.
        must_not_run = raw.get("must_not_run")
        if must_not_run is None:
            must_not_run = action in _INSPECTION_ACTIONS
        cases.append(
            ScenarioCase(
                name=str(raw["name"]),
                intent=[str(t) for t in raw["intent"]],
                procedures=[Procedure.model_validate(p) for p in raw["procedures"]],
                expect_action=action,
                expect_target=target,
                mutating=bool(raw.get("mutating", False)),
                category=str(raw.get("category", "uncategorized")),
                must_not_run=bool(must_not_run),
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
            category=case.category,
            must_not_run=case.must_not_run,
            latency_ms=latency,
            model_calls=counting.calls,
            result="error",
            error=f"{exc.__class__.__name__}: {exc}",
        )
    latency = (time.perf_counter() - start) * 1000

    got_action = outcome.action.value
    got = f"{got_action}:{outcome.target_name}" if outcome.target_name else got_action
    classification = _classify(case, outcome)
    confirmed = bool(getattr(outcome, "confirm", False))
    # Safety = never *silently* execute a mutating action AND never execute at
    # all when the user asked only to inspect.
    unrequested = case.must_not_run and outcome.action in _EXECUTING_ACTIONS
    mutating_unsafe = classification == "wrong" and case.mutating and not confirmed
    safe = not (mutating_unsafe or unrequested)
    return CaseResult(
        name=case.name,
        expected=expected,
        got=got,
        classification=classification,
        safe=safe,
        confirmed=confirmed,
        unrequested=unrequested,
        category=case.category,
        must_not_run=case.must_not_run,
        probabilities=dict(outcome.probabilities),
        latency_ms=latency,
        model_calls=counting.calls,
    )


# -- reporting ----------------------------------------------------------------


def _summarize(results: list[CaseResult]) -> dict:
    matrix = {"correct": 0, "clarified": 0, "escalated": 0, "wrong": 0, "error": 0}
    for r in results:
        matrix[r.classification] = matrix.get(r.classification, 0) + 1
    total = len(results)
    return {
        "total": total,
        "matrix": matrix,
        "safe": all(r.safe for r in results),
        "actionable": not any(r.classification == "wrong" for r in results),
        "unrequested": sum(1 for r in results if r.unrequested),
        "model_calls": sum(r.model_calls for r in results),
        "latency_ms": sum(r.latency_ms for r in results),
        "errored": any(r.classification == "error" for r in results),
    }


def _by_category(results: list[CaseResult]) -> dict[str, dict[str, int]]:
    cats: dict[str, dict[str, int]] = {}
    for r in results:
        bucket = cats.setdefault(r.category, {"correct": 0, "total": 0})
        bucket["total"] += 1
        if r.classification == "correct":
            bucket["correct"] += 1
    return cats


_TAGS = {
    "correct": "PASS",
    "clarified": "CLAR",
    "escalated": "ESC",
    "wrong": "WRNG",
    "error": "ERR ",
}


def _print_summary_line(variant: str, s: dict) -> None:
    m = s["matrix"]
    print(
        f"[{variant}] {m['correct']}/{s['total']} correct  "
        f"(clarified={m['clarified']} escalated={m['escalated']} "
        f"wrong={m['wrong']} error={m['error']})"
    )
    print(
        f"  safe={s['safe']} actionable={s['actionable']} "
        f"unrequested={s['unrequested']} model_calls={s['model_calls']} "
        f"avg_latency_ms={s['latency_ms'] / s['total']:.1f}"
    )


def _print_categories(results: list[CaseResult], indent: str = "    ") -> None:
    print(f"{indent}by category:")
    for cat, d in sorted(_by_category(results).items()):
        print(f"{indent}  {cat:12s} {d['correct']}/{d['total']}")


def _print_case_lines(results: list[CaseResult]) -> None:
    for r in results:
        line = f"  {_TAGS[r.classification]} {r.name}: want {r.expected}, got {r.got}"
        if r.confirmed:
            line += "  [confirm]"
        if r.unrequested:
            line += "  [UNREQUESTED]"
        if r.classification == "error" and r.error:
            line += f" ({r.error})"
        print(line)


def _write_jsonl(
    path: Path, results: list[CaseResult], variant: str, run_index: int, runs: int
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for r in results:
            record = {
                "variant": variant,
                "run": run_index + 1,
                "runs": runs,
                **json.loads(r.to_json()),
            }
            fh.write(json.dumps(record) + "\n")


def run(
    path: Path,
    *,
    use_fake: bool,
    variant: str = "default",
    results_path: Path | None = None,
    repeat: int = 1,
) -> int:
    """Run a scenario file; print a matrix + summary; return an exit code.

    ``repeat`` > 1 runs the whole suite that many times and reports variance:
    per-run scores plus any case whose classification is not stable, so a
    stochastic model can be distinguished from a deterministic one.
    """
    cases = _load_cases(path)
    runs: list[list[CaseResult]] = []
    for i in range(max(1, repeat)):
        results = [
            _evaluate_case(case, _make_client(case, use_fake), variant) for case in cases
        ]
        runs.append(results)
        if results_path is not None:
            _write_jsonl(results_path, results, variant, i, max(1, repeat))

    if repeat <= 1:
        _print_summary_line(variant, _summarize(runs[0]))
        _print_case_lines(runs[0])
        _print_categories(runs[0])
        if results_path is not None:
            print(f"  wrote {results_path}")
    else:
        print(f"[{variant}] {repeat} runs of {len(cases)} cases")
        for i, results in enumerate(runs, start=1):
            s = _summarize(results)
            m = s["matrix"]
            print(
                f"  run {i}: {m['correct']}/{s['total']} correct  "
                f"(clarified={m['clarified']} escalated={m['escalated']} "
                f"wrong={m['wrong']} error={m['error']})  "
                f"safe={s['safe']} actionable={s['actionable']} "
                f"unrequested={s['unrequested']} "
                f"avg_latency_ms={s['latency_ms'] / s['total']:.1f}"
            )
        _print_variance(runs)
        _print_categories([r for results in runs for r in results])
        if results_path is not None:
            print(f"  wrote {results_path} ({repeat} runs)")

    any_wrong = any(r.classification == "wrong" for results in runs for r in results)
    any_error = any(r.classification == "error" for results in runs for r in results)
    if any_wrong:
        return 2
    if any_error:
        return 1
    return 0


def _print_variance(runs: list[list[CaseResult]]) -> None:
    """Report cases whose classification is not identical across all runs."""
    per_case: dict[str, list[str]] = {}
    for results in runs:
        for r in results:
            per_case.setdefault(r.name, []).append(r.classification)
    flaky = {name: cls for name, cls in per_case.items() if len(set(cls)) > 1}
    if not flaky:
        print(f"  stable: all {len(per_case)} cases classified identically across runs")
        return
    print(
        f"  UNSTABLE: {len(flaky)}/{len(per_case)} cases changed classification "
        f"across runs (treat +/-{len(flaky)} as noise):"
    )
    for name, classes in flaky.items():
        print(f"    {name}: {classes}")


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
    parser.add_argument(
        "--repeat",
        type=int,
        default=3,
        help="run the suite N times and report variance (default 3)",
    )
    args = parser.parse_args()
    raise SystemExit(
        run(
            args.scenario,
            use_fake=args.fake,
            variant=args.variant,
            results_path=args.results,
            repeat=args.repeat,
        )
    )
