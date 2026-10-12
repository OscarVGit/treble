"""Unit tests for the Von-first run pipeline (Layer 1→5 orchestration)."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from treble.cli.commands._pipeline import (
    EXIT_CLARIFY,
    EXIT_DENIED,
    EXIT_NEEDS_DECISION,
    EXIT_OK,
    EXIT_VON_UNAVAILABLE,
    run_pipeline,
)
from treble.decision.prompts import (
    NONE_OF_THE_ABOVE,
    build_control_verb_options,
    build_run_target_options,
)
from treble.decision.testing import FakeSystemOneClient, make_answer
from treble.registry import Procedure, ProcedureStore


def _probs(options: dict[str, str], winner: str, p: float = 0.95) -> dict[str, float]:
    probs = {k: 0.001 for k in options}
    probs[winner] = p
    return probs


def _run_client(procs: list[Procedure], target: str) -> FakeSystemOneClient:
    """Scripted client: run-gate says 'run', target Choice picks ``target``."""
    return FakeSystemOneClient(
        noul_probability=0.9,
        answer=make_answer(target, _probs(build_run_target_options(procs), target)),
    )


def _control_client(verb: str, target: str | None, procs: list[Procedure]) -> FakeSystemOneClient:
    """Scripted client: run-gate says 'manage'; verb Choice then target Choice."""
    verb_opts = build_control_verb_options()
    answers = [make_answer(verb, _probs(verb_opts, verb))]
    if target is not None:
        target_opts = {p.name: p.description for p in procs}
        target_opts[NONE_OF_THE_ABOVE] = "none"
        answers.append(make_answer(target, _probs(target_opts, target)))
    return FakeSystemOneClient(noul_probability=0.1, answers=answers)


# -- Von availability --------------------------------------------------------


def test_von_unreachable_fails_closed(
    store: ProcedureStore, echo_proc: Procedure, project_cwd: Path
) -> None:
    store.add(echo_proc)
    client = FakeSystemOneClient(error=httpx.ConnectError("connection refused"))
    rc = run_pipeline(["hello"], cwd=project_cwd, client=client)
    assert rc == EXIT_VON_UNAVAILABLE


def test_no_regex_fallback(store: ProcedureStore, echo_proc: Procedure, project_cwd: Path) -> None:
    """An exact procedure name still routes through Von (no deterministic shortcut)."""
    store.add(echo_proc)
    client = _run_client([echo_proc], "echo-hello")
    rc = run_pipeline(["echo-hello", "--dry-run"], cwd=project_cwd, client=client)
    assert rc == EXIT_OK
    assert client.calls and client.calls[0][0] == "judge"  # Von was consulted first


# -- SELECT / run ------------------------------------------------------------


def test_select_runs_procedure(
    store: ProcedureStore, echo_proc: Procedure, project_cwd: Path, capsys
) -> None:
    store.add(echo_proc)
    client = _run_client([echo_proc], "echo-hello")
    rc = run_pipeline(["please", "say", "hello"], cwd=project_cwd, client=client)
    assert rc == EXIT_OK
    assert "hello" in capsys.readouterr().out
    assert (project_cwd / ".treble" / "audit.jsonl").exists()


def test_select_dry_run(store: ProcedureStore, echo_proc: Procedure, project_cwd: Path, capsys) -> None:
    store.add(echo_proc)
    client = _run_client([echo_proc], "echo-hello")
    rc = run_pipeline(["say", "hello"], cwd=project_cwd, dry_run=True, client=client)
    out = capsys.readouterr().out
    assert rc == EXIT_OK
    assert "[dry-run] would execute: echo hello" in out
    assert not (project_cwd / ".treble" / "audit.jsonl").exists()


def test_select_unknown_target(store: ProcedureStore, project_cwd: Path, capsys) -> None:
    """A Von pick outside the registry's option set escalates safely."""
    client = FakeSystemOneClient(
        noul_probability=0.9,
        answer=make_answer("ghost", {"ghost": 0.9, NONE_OF_THE_ABOVE: 0.1}),
    )
    rc = run_pipeline(["run", "ghost"], cwd=project_cwd, client=client)
    assert rc == EXIT_NEEDS_DECISION
    assert "no suitable action" in capsys.readouterr().out


# -- control plane ------------------------------------------------------------


def test_list_action(store: ProcedureStore, echo_proc: Procedure, project_cwd: Path, capsys) -> None:
    store.add(echo_proc)
    client = _control_client("list", None, [echo_proc])
    rc = run_pipeline(["list", "everything"], cwd=project_cwd, client=client)
    assert rc == EXIT_OK
    assert "echo-hello" in capsys.readouterr().out


def test_show_action(store: ProcedureStore, echo_proc: Procedure, project_cwd: Path, capsys) -> None:
    store.add(echo_proc)
    client = _control_client("show", "echo-hello", [echo_proc])
    rc = run_pipeline(["show", "echo-hello"], cwd=project_cwd, client=client)
    assert rc == EXIT_OK
    assert "executable: echo" in capsys.readouterr().out


def test_explain_action(
    store: ProcedureStore, echo_proc: Procedure, project_cwd: Path, capsys
) -> None:
    store.add(echo_proc)
    client = _control_client("explain", "echo-hello", [echo_proc])
    rc = run_pipeline(["explain", "echo-hello"], cwd=project_cwd, client=client)
    out = capsys.readouterr().out
    assert rc == EXIT_OK
    assert "procedure: echo-hello" in out
    assert "argv:      echo hello" in out


def test_test_action_runs_named(
    store: ProcedureStore, echo_proc: Procedure, project_cwd: Path, capsys
) -> None:
    store.add(echo_proc)
    client = _control_client("test", "echo-hello", [echo_proc])
    rc = run_pipeline(["test", "echo-hello"], cwd=project_cwd, client=client)
    assert rc == EXIT_OK
    assert "hello" in capsys.readouterr().out


# -- ADD (safety boundary: escalate, never auto-author) -----------------------


def test_add_action_escalates_without_registering(
    store: ProcedureStore, project_cwd: Path, capsys
) -> None:
    client = _control_client("add", None, [])
    rc = run_pipeline(["add", "a", "procedure"], cwd=project_cwd, client=client)
    out = capsys.readouterr().out
    assert rc == EXIT_NEEDS_DECISION
    assert "treble-add" in out
    assert store.list_all() == []  # nothing registered


# -- REMOVE (gated) -----------------------------------------------------------


def test_remove_requires_confirmation(
    store: ProcedureStore, echo_proc: Procedure, project_cwd: Path, monkeypatch
) -> None:
    store.add(echo_proc)
    monkeypatch.setattr("typer.confirm", lambda *a, **k: False)
    client = _control_client("remove", "echo-hello", [echo_proc])
    rc = run_pipeline(["remove", "echo-hello"], cwd=project_cwd, client=client)
    assert rc == EXIT_DENIED
    assert store.get("echo-hello").name == "echo-hello"  # still registered


def test_remove_with_yes(store: ProcedureStore, echo_proc: Procedure, project_cwd: Path, capsys) -> None:
    store.add(echo_proc)
    client = _control_client("remove", "echo-hello", [echo_proc])
    rc = run_pipeline(["remove", "echo-hello"], cwd=project_cwd, assume_yes=True, client=client)
    assert rc == EXIT_OK
    assert "removed 'echo-hello'" in capsys.readouterr().out
    with pytest.raises(Exception):  # noqa: B017
        store.get("echo-hello")


def test_remove_dry_run(store: ProcedureStore, echo_proc: Procedure, project_cwd: Path, capsys) -> None:
    store.add(echo_proc)
    client = _control_client("remove", "echo-hello", [echo_proc])
    rc = run_pipeline(["remove", "echo-hello"], cwd=project_cwd, dry_run=True, client=client)
    assert rc == EXIT_OK
    assert "[dry-run] would remove" in capsys.readouterr().out
    assert store.get("echo-hello").name == "echo-hello"


# -- CLARIFY / ESCALATE -------------------------------------------------------


def test_clarify_prints_alternatives(
    store: ProcedureStore,
    check_proc: Procedure,
    check_no_verify_proc: Procedure,
    project_cwd: Path,
    capsys,
) -> None:
    store.add(check_proc)
    store.add(check_no_verify_proc)
    procs = [check_proc, check_no_verify_proc]
    options = build_run_target_options(procs)
    probs = {k: 0.01 for k in options}
    probs["check"] = 0.5
    probs["check-no-verify"] = 0.45  # within margin
    client = FakeSystemOneClient(noul_probability=0.9, answer=make_answer("check", probs))
    rc = run_pipeline(["check"], cwd=project_cwd, client=client)
    out = capsys.readouterr().out
    assert rc == EXIT_CLARIFY
    assert "ambiguous request" in out


def test_escalate_when_none_of_the_above(
    store: ProcedureStore, echo_proc: Procedure, project_cwd: Path, capsys
) -> None:
    store.add(echo_proc)
    client = FakeSystemOneClient(
        noul_probability=0.9,
        answer=make_answer(NONE_OF_THE_ABOVE, {NONE_OF_THE_ABOVE: 0.9, "echo-hello": 0.1}),
    )
    rc = run_pipeline(["totally", "unrelated"], cwd=project_cwd, client=client)
    assert rc == EXIT_NEEDS_DECISION
    assert "no suitable action" in capsys.readouterr().out
