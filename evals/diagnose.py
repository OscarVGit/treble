"""Diagnose where the decision pipeline diverges for a scenario category.

Replays each case in a category through the live router with a *tracing*
client, and reports the run-gate Noul probability, the gate decision, and the
stage at which the request diverged from its expectation. Read-only: it does
not change the harness; it exists to ground a fix in evidence.

Usage:
    python evals/diagnose.py evals/scenarios/routing.yaml
    python evals/diagnose.py evals/scenarios/routing.yaml --category bare
    python evals/diagnose.py evals/scenarios/routing.yaml --variant verb-first-gate
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_eval

from treble.config import TrebleConfig
from treble.decision import Action, decide, default_client
from treble.decision.router import RUN_GATE_THRESHOLD


class TraceClient:
    """Wrap a client and record every judge/choose call with its answer."""

    def __init__(self, inner: object) -> None:
        self._inner = inner
        self.calls: list[tuple[str, str, object]] = []

    def judge(self, state, question):
        answer = self._inner.judge(state, question)  # type: ignore[attr-defined]
        self.calls.append(("judge", question.instructions, answer.probability))
        return answer

    def choose(self, state, question):
        answer = self._inner.choose(state, question)  # type: ignore[attr-defined]
        self.calls.append(("choose", question.instructions, (answer.choice, answer.probabilities)))
        return answer


def _expected_str(case) -> str:
    if case.expect_target:
        return f"{case.expect_action.value}:{case.expect_target}"
    return case.expect_action.value


def _got_str(outcome) -> str:
    if outcome.target_name:
        return f"{outcome.action.value}:{outcome.target_name}"
    return outcome.action.value


def _is_correct(case, outcome) -> bool:
    return outcome.action == case.expect_action and (
        case.expect_target is None or outcome.target_name == case.expect_target
    )


def _stage(case, outcome, gate_run: bool) -> str:
    if _is_correct(case, outcome):
        return "ok"
    if outcome.action is Action.CLARIFY:
        return "clarify"
    if outcome.action is Action.ESCALATE:
        return "escalate"
    inspect_expected = case.expect_action is not Action.SELECT_PROCEDURE
    if inspect_expected and gate_run:
        return "GATE (gate said run, expected control)"
    if inspect_expected and outcome.action is not Action.SELECT_PROCEDURE:
        return "VERB (control path, wrong verb)"
    if case.expect_action is Action.SELECT_PROCEDURE and outcome.action is Action.SELECT_PROCEDURE:
        return "TARGET (run path, wrong procedure)"
    return "other"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", type=Path)
    parser.add_argument("--category", default="nl-inspect")
    parser.add_argument("--variant", default="default")
    args = parser.parse_args()

    cases = [c for c in run_eval._load_cases(args.scenario)
             if args.category in ("all", c.category)]
    inner = default_client(TrebleConfig.load())

    print(f"category={args.category}  variant={args.variant}  cases={len(cases)}  "
          f"RUN_GATE_THRESHOLD={RUN_GATE_THRESHOLD}\n")
    tally: dict[str, int] = {}
    for case in cases:
        client = TraceClient(inner)
        outcome = decide(case.intent, case.procedures, client, variant=args.variant)
        gate_call = next((c for c in client.calls if c[0] == "judge"), None)
        gate_p = gate_call[2] if gate_call else None
        gate_run = gate_p is not None and gate_p >= RUN_GATE_THRESHOLD
        stage = _stage(case, outcome, gate_run)
        tally[stage] = tally.get(stage, 0) + 1
        want, got = _expected_str(case), _got_str(outcome)
        flag = "OK " if stage == "ok" else "   "
        gp = f"{gate_p:.2f}" if gate_p is not None else " n/a"
        print(f"{flag}{case.name:34s} gate={gp} ({'RUN' if gate_run else 'CTL'})  "
              f"want {want:16s} got {got:16s} -> {stage}")

    print("\nstage tally:")
    for stage, n in sorted(tally.items(), key=lambda kv: -kv[1]):
        print(f"  {n:3d}  {stage}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
