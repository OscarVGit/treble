"""Integration test: prompt variants actually reach the model client."""

from __future__ import annotations

from treble.decision import Action, decide
from treble.decision.prompts import get_variant
from treble.decision.testing import FakeSystemOneClient, make_answer
from treble.registry import Procedure


def _proc(name: str) -> Procedure:
    return Procedure(name=name, description=f"{name} desc", executable="echo")


def _gate_question(client: FakeSystemOneClient):
    """The judge call question recorded by the fake client (the run gate)."""
    for kind, _state, question in client.calls:
        if kind == "judge":
            return question
    raise AssertionError("no judge call recorded")


def test_default_variant_sends_default_gate_instruction() -> None:
    client = FakeSystemOneClient(
        noul_probability=0.9,
        answer=make_answer("a", {"a": 0.9, "none-of-the-above": 0.1}),
    )
    decide(["run", "a"], [_proc("a")], client, variant="default")
    q = _gate_question(client)
    assert q.instructions == get_variant("default").run_gate_condition
    assert "Treat a short request" in q.instructions  # the verbose default


def test_compact_gate_variant_sends_short_instruction() -> None:
    client = FakeSystemOneClient(
        noul_probability=0.9,
        answer=make_answer("a", {"a": 0.9, "none-of-the-above": 0.1}),
    )
    decide(["run", "a"], [_proc("a")], client, variant="compact-gate")
    q = _gate_question(client)
    assert q.instructions == "Is this a request to run a registered procedure?"


def test_compact_gate_state_carries_framing_line() -> None:
    client = FakeSystemOneClient(
        noul_probability=0.9,
        answer=make_answer("a", {"a": 0.9, "none-of-the-above": 0.1}),
    )
    decide(["run", "a"], [_proc("a")], client, variant="compact-gate")
    for kind, state, _q in client.calls:
        if kind == "judge":
            assert "name a procedure count as run requests" in state
            return
    raise AssertionError("no judge call recorded")


def test_default_gate_state_has_no_framing_line() -> None:
    client = FakeSystemOneClient(
        noul_probability=0.9,
        answer=make_answer("a", {"a": 0.9, "none-of-the-above": 0.1}),
    )
    decide(["run", "a"], [_proc("a")], client, variant="default")
    for kind, state, _q in client.calls:
        if kind == "judge":
            assert "name a procedure count as run requests" not in state
            return
    raise AssertionError("no judge call recorded")


def test_variant_changes_do_not_alter_outcome_shape() -> None:
    for variant in ("default", "compact-gate"):
        client = FakeSystemOneClient(
            noul_probability=0.9,
            answer=make_answer("a", {"a": 0.9, "none-of-the-above": 0.1}),
        )
        outcome = decide(["run", "a"], [_proc("a")], client, variant=variant)
        assert outcome.target_name == "a"


# -- folded variant (single action Choice) ------------------------------------


def _probs(options: dict[str, str], winner: str, p: float = 0.9) -> dict[str, float]:
    probs = {k: 0.001 for k in options}
    probs[winner] = p
    return probs


def test_folded_run_choice_selects_procedure() -> None:
    from treble.decision.prompts import build_action_options, build_run_target_options

    procs = [_proc("a")]
    action_opts = build_action_options()
    run_opts = build_run_target_options(procs)
    client = FakeSystemOneClient(
        answers=[
            make_answer("run", _probs(action_opts, "run")),
            make_answer("a", _probs(run_opts, "a")),
        ]
    )
    outcome = decide(["a"], procs, client, variant="folded")
    assert outcome.action is Action.SELECT_PROCEDURE
    assert outcome.target_name == "a"
    assert [c[0] for c in client.calls] == ["choose", "choose"]


def test_folded_list_choice_is_terminal() -> None:
    from treble.decision.prompts import build_action_options

    action_opts = build_action_options()
    client = FakeSystemOneClient(answer=make_answer("list", _probs(action_opts, "list")))
    outcome = decide(["what", "is", "registered"], [], client, variant="folded")
    assert outcome.action is Action.LIST
    assert [c[0] for c in client.calls] == ["choose"]


def test_folded_show_choice_then_target() -> None:
    from treble.decision.prompts import (
        build_action_options,
        build_control_target_options,
    )

    procs = [_proc("a")]
    action_opts = build_action_options()
    target_opts = build_control_target_options(procs)
    client = FakeSystemOneClient(
        answers=[
            make_answer("show", _probs(action_opts, "show")),
            make_answer("a", _probs(target_opts, "a")),
        ]
    )
    outcome = decide(["show", "a"], procs, client, variant="folded")
    assert outcome.action is Action.SHOW
    assert outcome.target_name == "a"


def test_folded_none_escalates() -> None:
    from treble.decision.prompts import NONE_OF_THE_ABOVE, build_action_options

    action_opts = build_action_options()
    client = FakeSystemOneClient(
        answer=make_answer(NONE_OF_THE_ABOVE, _probs(action_opts, NONE_OF_THE_ABOVE))
    )
    outcome = decide(["what", "is", "the", "weather"], [], client, variant="folded")
    assert outcome.action is Action.ESCALATE
