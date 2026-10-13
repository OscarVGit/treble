"""Integration test: prompt variants actually reach the model client."""

from __future__ import annotations

from treble.decision import decide
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
    decide(["a"], [_proc("a")], client, variant="default")
    q = _gate_question(client)
    assert q.instructions == get_variant("default").run_gate_condition
    assert "Treat a short request" in q.instructions  # the verbose default


def test_compact_gate_variant_sends_short_instruction() -> None:
    client = FakeSystemOneClient(
        noul_probability=0.9,
        answer=make_answer("a", {"a": 0.9, "none-of-the-above": 0.1}),
    )
    decide(["a"], [_proc("a")], client, variant="compact-gate")
    q = _gate_question(client)
    assert q.instructions == "Is this a request to run a registered procedure?"


def test_compact_gate_state_carries_framing_line() -> None:
    client = FakeSystemOneClient(
        noul_probability=0.9,
        answer=make_answer("a", {"a": 0.9, "none-of-the-above": 0.1}),
    )
    decide(["a"], [_proc("a")], client, variant="compact-gate")
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
    decide(["a"], [_proc("a")], client, variant="default")
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
        outcome = decide(["a"], [_proc("a")], client, variant=variant)
        assert outcome.target_name == "a"
