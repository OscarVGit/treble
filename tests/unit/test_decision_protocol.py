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
    # One Noul (gate) + one Choice (target) + one Noul (name-collision showdown;
    # the request names "check" exactly but the pick extends it).
    assert [c[0] for c in client.calls] == ["judge", "choose", "judge"]


def test_name_collision_showdown_falls_back_to_exact_match(
    check_proc: Procedure, check_no_verify_proc: Procedure
) -> None:
    """Request names 'check' exactly but the model picks 'check-no-verify';
    the showdown Noul rejects the longer pick, so the exact name wins."""
    procs = [check_proc, check_no_verify_proc]
    options = build_run_target_options(procs)
    client = FakeSystemOneClient(
        noul_series=[0.1],  # bare name: collision showdown rejects the pick
        answer=make_answer("check-no-verify", _probs(options, "check-no-verify", 0.9)),
    )
    outcome = decide(["check"], procs, client)
    assert outcome.action is Action.SELECT_PROCEDURE
    assert outcome.target_name == "check"


def test_name_collision_showdown_confirms_longer_pick(
    check_proc: Procedure, check_no_verify_proc: Procedure
) -> None:
    """When the request carries the distinguishing qualifier, the collision
    Noul confidently endorses the longer name and it is kept."""
    procs = [check_proc, check_no_verify_proc]
    options = build_run_target_options(procs)
    client = FakeSystemOneClient(
        noul_series=[0.9, 0.9],  # collision Noul confident (>= 0.6)
        answer=make_answer("check-no-verify", _probs(options, "check-no-verify", 0.9)),
    )
    outcome = decide(["check", "--no-verify"], procs, client)
    assert outcome.target_name == "check-no-verify"


def test_name_collision_unsure_prefers_exact_name(
    check_proc: Procedure, check_no_verify_proc: Procedure
) -> None:
    """The live failure mode: the Noul is unsure (0.3 <= p < 0.6), so the
    exact-name match wins without a confirmation prompt."""
    procs = [check_proc, check_no_verify_proc]
    options = build_run_target_options(procs)
    client = FakeSystemOneClient(
        noul_series=[0.33],
        answer=make_answer("check-no-verify", _probs(options, "check-no-verify", 0.9)),
    )
    outcome = decide(["check"], procs, client)
    assert outcome.target_name == "check"
    assert outcome.confirm is False


def test_control_target_name_collision_falls_back(
    check_proc: Procedure, check_no_verify_proc: Procedure
) -> None:
    procs = [check_proc, check_no_verify_proc]
    verb_opts = build_control_verb_options()
    target_opts = build_run_target_options(procs)
    client = FakeSystemOneClient(
        noul_series=[0.1, 0.1],  # gate=control, collision showdown rejects
        answers=[
            make_answer("remove", _probs(verb_opts, "remove", 0.95)),
            make_answer(
                "check-no-verify", _probs(target_opts, "check-no-verify", 0.9)
            ),
        ],
    )
    outcome = decide(["remove", "the", "check", "procedure"], procs, client)
    assert outcome.action is Action.REMOVE_PROCEDURE
    assert outcome.target_name == "check"


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


def test_close_top_two_clarifies_when_showdown_rejects(
    check_proc: Procedure, check_no_verify_proc: Procedure
) -> None:
    procs = [check_proc, check_no_verify_proc]
    options = build_run_target_options(procs)
    probs = {k: 0.01 for k in options}
    probs["check"] = 0.5
    probs["check-no-verify"] = 0.45  # within margin
    # bare "check" skips the run gate; showdown Noul rejects top pick (0.1 -> abandon)
    client = FakeSystemOneClient(
        noul_series=[0.1], answer=make_answer("check", probs)
    )
    outcome = decide(["check"], procs, client, ambiguity_margin=0.12)
    assert outcome.action is Action.CLARIFY


def test_showdown_noul_confirms_pick(
    check_proc: Procedure, check_no_verify_proc: Procedure
) -> None:
    procs = [check_proc, check_no_verify_proc]
    options = build_run_target_options(procs)
    probs = {k: 0.01 for k in options}
    probs["check"] = 0.5
    probs["check-no-verify"] = 0.45  # within margin
    # showdown Noul clearly confirms the top pick -> execute, no user gate.
    client = FakeSystemOneClient(
        noul_series=[0.9, 0.85], answer=make_answer("check", probs)
    )
    outcome = decide(["check"], procs, client, ambiguity_margin=0.12)
    assert outcome.action is Action.SELECT_PROCEDURE
    assert outcome.target_name == "check"
    assert outcome.confirm is False
    assert outcome.runner_up == "check-no-verify"


def test_showdown_noul_unsure_requires_confirmation(
    check_proc: Procedure, check_no_verify_proc: Procedure
) -> None:
    procs = [check_proc, check_no_verify_proc]
    options = build_run_target_options(procs)
    probs = {k: 0.01 for k in options}
    probs["check"] = 0.5
    probs["check-no-verify"] = 0.45  # within margin
    # bare "check" skips the run gate; showdown Noul is unsure -> confirm.
    client = FakeSystemOneClient(
        noul_series=[0.45], answer=make_answer("check", probs)
    )
    outcome = decide(["check"], procs, client, ambiguity_margin=0.12)
    assert outcome.action is Action.SELECT_PROCEDURE
    assert outcome.target_name == "check"
    assert outcome.confirm is True
    assert outcome.runner_up == "check-no-verify"


# -- mutating confirmation gate ----------------------------------------------


def test_remove_selection_requires_confirmation(
    check_proc: Procedure, check_no_verify_proc: Procedure
) -> None:
    procs = [check_proc, check_no_verify_proc]
    verb_opts = build_control_verb_options()
    target_opts = {p.name: p.description for p in procs}
    target_opts[NONE_OF_THE_ABOVE] = "none"
    client = FakeSystemOneClient(
        noul_probability=0.1,
        answers=[
            make_answer("remove", _probs(verb_opts, "remove", 0.95)),
            make_answer("check", _probs(target_opts, "check", 0.9)),
        ],
    )
    outcome = decide(["remove", "the", "check", "procedure"], procs, client)
    assert outcome.action is Action.REMOVE_PROCEDURE
    assert outcome.target_name == "check"
    assert outcome.confirm is True
    assert outcome.confirm_reason


def test_destructive_run_selection_requires_confirmation() -> None:
    procs = [
        Procedure(name="check", description="c", executable="echo"),
        Procedure(
            name="deploy",
            description="Deploy to production",
            executable="echo",
            risk="destructive",
        ),
    ]
    options = build_run_target_options(procs)
    client = FakeSystemOneClient(
        noul_probability=0.9,
        answer=make_answer("deploy", _probs(options, "deploy", 0.9)),
    )
    outcome = decide(["deploy", "it"], procs, client)
    assert outcome.action is Action.SELECT_PROCEDURE
    assert outcome.target_name == "deploy"
    assert outcome.confirm is True
    assert "destructive" in outcome.confirm_reason


def test_read_only_run_selection_needs_no_extra_confirmation(
    check_proc: Procedure,
) -> None:
    options = build_run_target_options([check_proc])
    client = FakeSystemOneClient(
        noul_probability=0.9,
        answer=make_answer("check", _probs(options, "check", 0.9)),
    )
    outcome = decide(["check"], [check_proc], client)
    assert outcome.action is Action.SELECT_PROCEDURE
    assert outcome.confirm is False


# -- inspect-precedence guard -------------------------------------------------


def test_leading_inspection_verb_detection() -> None:
    from treble.decision.router import _leading_inspection_verb

    build = Procedure(name="build", description="b", executable="echo")

    assert _leading_inspection_verb(["show", "me", "the", "build"], [build]) == "show"
    assert _leading_inspection_verb(["explain", "the", "build"], [build]) == "explain"
    assert _leading_inspection_verb(["describe", "the", "build"], [build]) == "describe"
    assert _leading_inspection_verb(["list", "all", "procedures"], [build]) == "list"
    assert _leading_inspection_verb(["what", "does", "build", "do"], [build]) == "what"
    assert _leading_inspection_verb(["how", "does", "build", "work"], [build]) == "how"
    # courtesy filler is skipped
    assert _leading_inspection_verb(["please", "show", "me", "build"], [build]) == "show"


def test_leading_inspection_verb_ignores_runs_and_bare_names() -> None:
    from treble.decision.router import _leading_inspection_verb

    build = Procedure(name="build", description="b", executable="echo")
    assert _leading_inspection_verb(["build"], [build]) is None
    assert _leading_inspection_verb(["run", "the", "build"], [build]) is None
    assert _leading_inspection_verb(["test", "please"], [build]) is None
    assert _leading_inspection_verb(["pnpm", "run", "check"], [build]) is None
    # a procedure named like an inspection verb still runs when typed bare
    listing = Procedure(name="list", description="l", executable="echo")
    assert _leading_inspection_verb(["list"], [listing]) is None


def test_leading_inspection_verb_refinement_with_verb_named_procedure() -> None:
    from treble.decision.router import _leading_inspection_verb

    show_proc = Procedure(name="show", description="s", executable="echo")
    build = Procedure(name="build", description="b", executable="echo")
    procs = [show_proc, build]
    # bare invocation of the verb-named procedure -> run (no guard)
    assert _leading_inspection_verb(["show"], procs) is None
    # but the *same* word leading a phrase is an inspection, even though a
    # procedure is named "show"
    assert _leading_inspection_verb(["show", "me", "the", "build"], procs) == "show"
    assert _leading_inspection_verb(["please", "show", "the", "build"], procs) == "show"


def test_bare_registered_name_detection() -> None:
    from treble.decision.router import _bare_registered_name

    build = Procedure(
        name="build", description="b", executable="echo", aliases=["compile"]
    )
    assert _bare_registered_name(["build"], [build]) == "build"
    assert _bare_registered_name(["compile"], [build]) == "build"  # alias
    assert _bare_registered_name(["please", "build"], [build]) == "build"
    assert _bare_registered_name(["build", "the", "project"], [build]) is None
    assert _bare_registered_name(["pnpm", "run", "check"], [build]) is None
    assert _bare_registered_name(["nope"], [build]) is None


def test_bare_registered_name_runs_without_gate() -> None:
    from treble.decision.prompts import build_run_target_options

    describe = Procedure(name="describe", description="d", executable="echo")
    build = Procedure(name="build", description="b", executable="echo")
    opts = build_run_target_options([describe, build])
    client = FakeSystemOneClient(
        answer=make_answer("describe", _probs(opts, "describe"))
    )
    outcome = decide(["describe"], [describe, build], client)
    assert outcome.action is Action.SELECT_PROCEDURE
    assert outcome.target_name == "describe"
    assert client.calls[0][0] == "choose"  # run gate skipped


def test_guard_routes_inspection_to_control_without_gate() -> None:
    from treble.decision.prompts import (
        build_control_target_options,
        build_control_verb_options,
    )

    build = Procedure(name="build", description="b", executable="echo")
    verb_opts = build_control_verb_options()
    target_opts = build_control_target_options([build])
    # noul_probability=0.9 would send a gated request down the run path; the
    # guard must bypass the gate entirely.
    client = FakeSystemOneClient(
        noul_probability=0.9,
        answers=[
            make_answer("show", _probs(verb_opts, "show")),
            make_answer("build", _probs(target_opts, "build")),
        ],
    )
    outcome = decide(["show", "me", "the", "build"], [build], client)
    assert outcome.action is Action.SHOW
    assert outcome.target_name == "build"
    assert client.calls[0][0] == "choose"  # no run-gate Noul was consulted
