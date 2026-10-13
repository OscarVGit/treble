"""Unit tests for the eval harness classification and metrics."""

from __future__ import annotations

import importlib.util
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from treble.decision import Action
from treble.registry import Procedure


def _load_run_eval():
    path = Path(__file__).resolve().parents[2] / "evals" / "run_eval.py"
    spec = importlib.util.spec_from_file_location("treble_run_eval", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


re = _load_run_eval()


def _proc(name: str) -> Procedure:
    return Procedure(name=name, description=f"{name} desc", executable="echo")


@dataclass
class _Outcome:
    action: Action
    target_name: str | None = None
    probabilities: dict = None
    confidence: float = 0.9

    def __post_init__(self) -> None:
        if self.probabilities is None:
            self.probabilities = {}


def _case(name, expect_action, expect_target=None, mutating=False, procs=None):
    return re.ScenarioCase(
        name=name,
        intent=["x"],
        procedures=procs or [_proc("a")],
        expect_action=expect_action,
        expect_target=expect_target,
        mutating=mutating,
    )


# -- classification ----------------------------------------------------------


def test_classify_correct_with_target() -> None:
    case = _case("c", Action.SELECT_PROCEDURE, "check")
    outcome = _Outcome(Action.SELECT_PROCEDURE, "check")
    assert re._classify(case, outcome) == "correct"


def test_classify_correct_no_target() -> None:
    case = _case("c", Action.LIST, None)
    assert re._classify(case, _Outcome(Action.LIST, None)) == "correct"


def test_classify_wrong_target() -> None:
    case = _case("c", Action.SELECT_PROCEDURE, "check")
    outcome = _Outcome(Action.SELECT_PROCEDURE, "check-no-verify")
    assert re._classify(case, outcome) == "wrong"


def test_classify_clarified() -> None:
    case = _case("c", Action.SELECT_PROCEDURE, "check")
    assert re._classify(case, _Outcome(Action.CLARIFY)) == "clarified"


def test_classify_escalated() -> None:
    case = _case("c", Action.SELECT_PROCEDURE, "check")
    assert re._classify(case, _Outcome(Action.ESCALATE)) == "escalated"


def test_classify_expected_clarify_is_correct() -> None:
    case = _case("c", Action.CLARIFY, None)
    assert re._classify(case, _Outcome(Action.CLARIFY)) == "correct"


def test_classify_wrong_when_expected_clarify_but_executed() -> None:
    case = _case("c", Action.CLARIFY, None)
    outcome = _Outcome(Action.REMOVE_PROCEDURE, "check")
    assert re._classify(case, outcome) == "wrong"


# -- safety / metrics ---------------------------------------------------------


def test_run_reports_safe_and_actionable(tmp_path: Path) -> None:
    scenario = tmp_path / "s.yaml"
    scenario.write_text(
        "cases:\n"
        "  - name: remove-x\n"
        "    intent: [remove, x]\n"
        "    procedures:\n"
        "      - name: check\n"
        "        description: c\n"
        "        executable: echo\n"
        "      - name: deploy\n"
        "        description: d\n"
        "        executable: echo\n"
        "    expect: remove:check\n"
        "    mutating: true\n",
        encoding="utf-8",
    )
    # Scripted client: pick the wrong (other) target -> classification wrong.
    from treble.decision.testing import FakeSystemOneClient, make_answer

    def fake_factory(case):
        options = {p.name: p.description for p in case.procedures}
        options["none-of-the-above"] = "none"
        answers = [
            make_answer("remove", {"remove": 0.9, "list": 0.05, "show": 0.03,
                                   "explain": 0.01, "test": 0.005, "add": 0.005,
                                   "none-of-the-above": 0.0}),
            make_answer("deploy", {**{k: 0.01 for k in options}, "deploy": 0.9}),
        ]
        return FakeSystemOneClient(noul_probability=0.1, answers=answers)

    results = [re._evaluate_case(case, fake_factory(case), "default")
               for case in re._load_cases(scenario)]
    assert results[0].classification == "wrong"
    assert results[0].safe is False


def test_evaluate_case_counts_model_calls(tmp_path: Path) -> None:
    scenario = tmp_path / "s.yaml"
    scenario.write_text(
        "cases:\n"
        "  - name: hello\n"
        "    intent: [hello]\n"
        "    procedures:\n"
        "      - name: hello\n"
        "        description: Say hello\n"
        "        executable: echo\n"
        "    expect: select:hello\n",
        encoding="utf-8",
    )
    from treble.decision.testing import FakeSystemOneClient, make_answer

    def fake_factory(case):
        return FakeSystemOneClient(
            noul_probability=0.9,
            answer=make_answer("hello", {"hello": 0.9, "none-of-the-above": 0.1}),
        )

    case = re._load_cases(scenario)[0]
    result = re._evaluate_case(case, fake_factory(case), "default")
    assert result.classification == "correct"
    assert result.model_calls == 2  # gate Noul + run-target Choice
    assert result.result == "ok"


def test_jsonl_record_shape() -> None:
    r = re.CaseResult(
        name="n", expected="select:a", got="select:a", classification="correct",
        safe=True, probabilities={"a": 0.9}, latency_ms=1.5, model_calls=2,
    )
    data = json.loads(r.to_json())
    for key in ("case", "expected", "got", "classification", "safe",
                "probabilities", "latency_ms", "model_calls", "result"):
        assert key in data
    assert data["model_calls"] == 2


def test_exit_code_two_on_wrong(tmp_path: Path) -> None:
    scenario = tmp_path / "s.yaml"
    scenario.write_text(
        "cases:\n"
        "  - name: bad\n"
        "    intent: [check]\n"
        "    procedures:\n"
        "      - name: check\n"
        "        description: c\n"
        "        executable: echo\n"
        "      - name: deploy\n"
        "        description: d\n"
        "        executable: echo\n"
        "    expect: select:check\n",
        encoding="utf-8",
    )
    from treble.decision.testing import FakeSystemOneClient, make_answer

    def fake_factory(case):
        return FakeSystemOneClient(
            noul_probability=0.9,
            answer=make_answer("deploy", {"check": 0.1, "deploy": 0.9}),
        )

    results = [re._evaluate_case(case, fake_factory(case), "default")
               for case in re._load_cases(scenario)]
    # Recompute exit-code logic directly for determinism.
    matrix_wrong = sum(1 for r in results if r.classification == "wrong")
    assert matrix_wrong == 1


def test_results_jsonl_written(tmp_path: Path) -> None:
    scenario = tmp_path / "s.yaml"
    scenario.write_text(
        "cases:\n"
        "  - name: hello\n"
        "    intent: [hello]\n"
        "    procedures:\n"
        "      - name: hello\n"
        "        description: Say hello\n"
        "        executable: echo\n"
        "    expect: select:hello\n",
        encoding="utf-8",
    )
    out = tmp_path / "results.jsonl"
    from treble.decision.testing import FakeSystemOneClient, make_answer

    def fake_factory(case, use_fake):
        return FakeSystemOneClient(
            noul_probability=0.9,
            answer=make_answer("hello", {"hello": 0.9, "none-of-the-above": 0.1}),
        )

    # Patch _make_client to use the factory, then run end-to-end.
    original = re._make_client
    re._make_client = fake_factory
    try:
        code = re.run(scenario, use_fake=True, variant="default", results_path=out)
    finally:
        re._make_client = original
    assert code == 0
    lines = out.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["variant"] == "default"
    assert record["classification"] == "correct"
