"""Run routing scenarios from a YAML file against the Von decision model.

Each case declares an ``intent`` (the raw tokens a user typed), a fixture
``procedures`` registry, and the expected routing outcome in the action
vocabulary:

- ``select:<name>`` — run-gate opens, run-target Choice picks ``<name>``
- ``remove:<name>`` / ``show:<name>`` / ``test:<name>`` / ``explain:<name>``
  — control verb then target
- ``list`` / ``add``  — control verb, no target
- ``clarify``         — confidence/margin gates trip
- ``escalate``        — none-of-the-above

Default mode talks to a live Von server (``TREBLE_VON_URL`` or the built-in
default). ``--fake`` scripts the model for offline CI.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml

from treble.config import TrebleConfig
from treble.decision import Action, decide
from treble.decision.prompts import (
    NONE_OF_THE_ABOVE,
    build_control_verb_options,
    build_run_target_options,
)
from treble.registry.models import Procedure

_PREFIX_TO_ACTION = {
    "select": Action.SELECT_PROCEDURE,
    "remove": Action.REMOVE_PROCEDURE,
    "show": Action.SHOW,
    "test": Action.TEST,
    "explain": Action.EXPLAIN,
}
_ACTION_TO_VERB = {  # control verbs as they appear in Von's option keys
    Action.REMOVE_PROCEDURE: "remove",
    Action.SHOW: "show",
    Action.TEST: "test",
    Action.EXPLAIN: "explain",
}


def _load_cases(path: Path) -> list[dict[str, object]]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "cases" not in data:
        msg = f"scenario file {path} must contain a top-level 'cases' list"
        raise SystemExit(msg)
    return list(data["cases"])  # type: ignore[arg-type]


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


def run(path: Path, *, use_fake: bool) -> int:
    cases = _load_cases(path)
    total = matched = 0
    failures: list[str] = []

    for case in cases:
        intent = [str(t) for t in case["intent"]]  # type: ignore[index]
        procedures = [Procedure.model_validate(p) for p in case["procedures"]]  # type: ignore[index]
        want_action, want_target = _expected(str(case["expect"]))

        client = _make_client(procedures, want_action, want_target, use_fake)
        outcome = decide(intent, procedures, client)

        total += 1
        ok = outcome.action is want_action and (
            want_target is None or outcome.target_name == want_target
        )
        if ok:
            matched += 1
        else:
            got = f"{outcome.action}:{outcome.target_name or '-'}"
            failures.append(f"{case['name']}: want {case['expect']}, got {got}")

    mode = "fake" if use_fake else "live"
    print(f"[{mode}] {matched}/{total} correct")
    for failure in failures:
        print(f"  FAIL {failure}")
    return 0 if not failures else 1


def _make_client(procedures, want_action, want_target, use_fake):
    if not use_fake:
        from treble.decision import default_client

        return default_client(TrebleConfig.load())

    from treble.decision.testing import FakeSystemOneClient, make_answer

    def spread(options: dict[str, str], winner: str, p: float = 0.95) -> dict[str, float]:
        probs = {k: 0.001 for k in options}
        probs[winner] = p
        return probs

    run_path = want_action is Action.SELECT_PROCEDURE
    noul_p = 0.9 if run_path else 0.1

    if want_action is Action.CLARIFY:
        # Force a below-threshold winner on the path the gate selects.
        options = (
            build_run_target_options(procedures) if run_path else build_control_verb_options()
        )
        first = next(iter(options))
        probs = {k: 0.2 for k in options}
        return FakeSystemOneClient(noul_probability=0.9, answer=make_answer(first, probs))

    if want_action is Action.ESCALATE:
        # none-of-the-above on whichever path the gate selects.
        options = (
            build_run_target_options(procedures) if run_path else build_control_verb_options()
        )
        return FakeSystemOneClient(
            noul_probability=noul_p,
            answer=make_answer(NONE_OF_THE_ABOVE, spread(options, NONE_OF_THE_ABOVE)),
        )

    if run_path:
        options = build_run_target_options(procedures)
        return FakeSystemOneClient(
            noul_probability=0.9,
            answer=make_answer(want_target, spread(options, str(want_target))),
        )

    # Control path: verb Choice, then target Choice if targeted.
    verb_opts = build_control_verb_options()
    verb = want_action.value if want_target is None else _ACTION_TO_VERB[want_action]
    answers = [make_answer(verb, spread(verb_opts, verb))]
    if want_target is not None:
        target_opts = {p.name: p.description for p in procedures}
        target_opts[NONE_OF_THE_ABOVE] = "none"
        answers.append(make_answer(want_target, spread(target_opts, want_target)))
    return FakeSystemOneClient(noul_probability=0.1, answers=answers)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", type=Path)
    parser.add_argument("--fake", action="store_true", help="use a scripted client (offline)")
    args = parser.parse_args()
    raise SystemExit(run(args.scenario, use_fake=args.fake))
