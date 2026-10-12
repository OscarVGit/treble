"""Unit tests for the Von decision layer (Layer 4).

Uses a scripted FakeSystemOneClient so tests run without a live Von server.
The fake scripts the Noul run-gate (``noul_probability``) and the Choice
answers (``answer`` or an ordered ``answers`` list) independently.
"""

from __future__ import annotations

from treble.decision import Action, decide
from treble.decision.prompts import (
    NONE_OF_THE_ABOVE,
    build_control_verb_options,
    build_run_target_options,
    build_state,
)
from treble.decision.protocol import (
    ChoiceAnswer,
    NoulAnswer,
    parse_choice_answer,
    parse_noul_answer,
)
from treble.decision.testing import FakeSystemOneClient, make_answer
from treble.registry import Procedure


def _probs(options: dict[str, str], winner: str, p: float = 0.95) -> dict[str, float]:
    probs = {k: 0.001 for k in options}
    probs[winner] = p
    return probs


# -- protocol ---------------------------------------------------------------


def test_parse_choice_answer_round_trip() -> None:
    body = {
        "answers": {
            "route": {
                "type": "choice",
                "choice": "check",
                "probabilities": {"check": 0.7, "build": 0.3},
                "confidence": 0.7,
            }
        }
    }
    answer = parse_choice_answer(body)
    assert answer.choice == "check"
    assert answer.winning_probability == 0.7


def test_parse_noul_answer_prefers_raw() -> None:
    body = {"answers": {"route": {"type": "noul", "noul": 0.83, "noul_raw": 0.91}}}
    answer = parse_noul_answer(body)
    assert answer.probability == 0.91
    assert answer.holds


def test_noul_answer_falls_back_to_banded() -> None:
    assert NoulAnswer(noul=0.8).probability == 0.8
    assert not NoulAnswer(noul=0.2).holds


def test_choice_answer_top_two() -> None:
    answer = ChoiceAnswer(choice="a", probabilities={"a": 0.5, "b": 0.4, "c": 0.1})
    top = answer.top_two()
    assert top is not None and top[0] == ("a", 0.5) and top[1] == ("b", 0.4)


def test_build_state_contains_request() -> None:
    assert "pnpm run check" in build_state(["pnpm", "run", "check"])


def test_option_builders_include_escape_hatch(check_proc: Procedure) -> None:
    assert NONE_OF_THE_ABOVE in build_run_target_options([check_proc])
    assert NONE_OF_THE_ABOVE in build_control_verb_options()


# -- run path (Noul gate = run) ----------------------------------------------


def test_run_request_selects_procedure(
    check_proc: Procedure, check_no_verify_proc: Procedure
) -> None:
    procs = [check_proc, check_no_verify_proc]
    options = build_run_target_options(procs)
    client = FakeSystemOneClient(
        noul_probability=0.9,  # run gate: yes
        answer=make_answer("check-no-verify", _probs(options, "check-no-verify", 0.7)),
    )
    outcome = decide(["check", "without", "verification"], procs, client)
    assert outcome.action is Action.SELECT_PROCEDURE
    assert outcome.target_name == "check-no-verify"
    # One Noul (gate) + one Choice (target).
    assert [c[0] for c in client.calls] == ["judge", "choose"]


def test_run_request_with_no_procedures_escalates() -> None:
    client = FakeSystemOneClient(noul_probability=0.9)
    outcome = decide(["run", "something"], [], client)
    assert outcome.action is Action.ESCALATE


def test_run_target_none_of_the_above_escalates(check_proc: Procedure) -> None:
    options = build_run_target_options([check_proc])
    client = FakeSystemOneClient(
        noul_probability=0.9,
        answer=make_answer(NONE_OF_THE_ABOVE, _probs(options, NONE_OF_THE_ABOVE, 0.9)),
    )
    outcome = decide(["deploy", "the", "monolith"], [check_proc], client)
    assert outcome.action is Action.ESCALATE


# -- control path (Noul gate = not-run) ---------------------------------------


def test_list_control_action() -> None:
    options = build_control_verb_options()
    client = FakeSystemOneClient(
        noul_probability=0.1,  # run gate: no
        answer=make_answer("list", _probs(options, "list", 0.99)),
    )
    outcome = decide(["list", "all", "procedures"], [], client)
    assert outcome.action is Action.LIST
    assert outcome.target_name is None


def test_add_control_action() -> None:
    options = build_control_verb_options()
    client = FakeSystemOneClient(
        noul_probability=0.1,
        answer=make_answer("add", _probs(options, "add", 0.98)),
    )
    outcome = decide(["add", "a", "procedure"], [], client)
    assert outcome.action is Action.ADD_PROCEDURE


def test_targeted_control_verb_then_target(
    check_proc: Procedure, check_no_verify_proc: Procedure
) -> None:
    procs = [check_proc, check_no_verify_proc]
    verb_opts = build_control_verb_options()
    target_opts = {p.name: p.description for p in procs}
    target_opts[NONE_OF_THE_ABOVE] = "none"
    client = FakeSystemOneClient(
        noul_probability=0.1,  # control path
        answers=[
            make_answer("remove", _probs(verb_opts, "remove", 0.95)),   # verb
            make_answer("check", _probs(target_opts, "check", 0.9)),      # target
        ],
    )
    outcome = decide(["remove", "the", "check", "procedure"], procs, client)
    assert outcome.action is Action.REMOVE_PROCEDURE
    assert outcome.target_name == "check"
    assert [c[0] for c in client.calls] == ["judge", "choose", "choose"]


def test_control_none_of_the_above_escalates() -> None:
    options = build_control_verb_options()
    client = FakeSystemOneClient(
        noul_probability=0.1,
        answer=make_answer(NONE_OF_THE_ABOVE, _probs(options, NONE_OF_THE_ABOVE, 0.9)),
    )
    outcome = decide(["what", "is", "the", "weather"], [], client)
    assert outcome.action is Action.ESCALATE


# -- gates --------------------------------------------------------------------


def test_low_winning_probability_clarifies(check_proc: Procedure) -> None:
    options = build_run_target_options([check_proc])
    # Winner at 0.2, below the 0.4 threshold.
    probs = {k: 0.2 for k in options}
    client = FakeSystemOneClient(
        noul_probability=0.9, answer=make_answer("check", probs)
    )
    outcome = decide(["check"], [check_proc], client, confidence_threshold=0.4)
    assert outcome.action is Action.CLARIFY
    assert outcome.options  # exposed for the caller to format


def test_close_top_two_clarifies(
    check_proc: Procedure, check_no_verify_proc: Procedure
) -> None:
    procs = [check_proc, check_no_verify_proc]
    options = build_run_target_options(procs)
    probs = {k: 0.01 for k in options}
    probs["check"] = 0.5
    probs["check-no-verify"] = 0.45  # within margin 0.12 of 0.5
    client = FakeSystemOneClient(noul_probability=0.9, answer=make_answer("check", probs))
    outcome = decide(["check"], procs, client, ambiguity_margin=0.12)
    assert outcome.action is Action.CLARIFY
