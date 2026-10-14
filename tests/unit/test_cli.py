"""Unit tests for the CLI layer (Layer 1)."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from treble.cli.add import app as add_app
from treble.cli.main import app as main_app
from treble.decision.prompts import build_run_target_options
from treble.decision.testing import FakeSystemOneClient, make_answer
from treble.registry import ProcedureStore

runner = CliRunner()


def _patch_von(monkeypatch: pytest.MonkeyPatch, client: FakeSystemOneClient) -> None:
    """Force the pipeline to use a scripted client instead of a live server."""
    monkeypatch.setattr("treble.cli.commands._pipeline.default_client", lambda cfg: client)


def _select_client(store: ProcedureStore, name: str) -> FakeSystemOneClient:
    """Scripted client: run-gate says run; target Choice picks ``name``."""
    procs = store.list_all()
    options = build_run_target_options(procs)
    probs = {k: 0.005 for k in options}
    probs[name] = 0.95
    return FakeSystemOneClient(noul_probability=0.9, answer=make_answer(name, probs))


# -- parser -----------------------------------------------------------------


# -- dispatcher: literal vs Von-routed ----------------------------------------


def test_literal_invocation_detection() -> None:
    from treble.cli.main import _is_literal_invocation

    # Well-formed literal calls stay deterministic.
    assert _is_literal_invocation(["list"])
    assert _is_literal_invocation(["stats"])
    assert _is_literal_invocation(["stats", "--json"])
    assert _is_literal_invocation(["remove", "hello"])
    assert _is_literal_invocation(["show", "hello"])
    assert _is_literal_invocation(["test", "hello", "--dry-run"])
    assert _is_literal_invocation(["add", "--name", "x", "--command", "echo", "-d", "y"])
    # Free-form / malformed calls route through Von.
    assert not _is_literal_invocation(["remove", "the", "hello", "procedure"])
    assert not _is_literal_invocation(["remove", "hello", "--dry-run"])
    assert not _is_literal_invocation(["show", "me", "the", "check", "procedure"])
    assert not _is_literal_invocation(["list", "all", "procedures"])
    assert not _is_literal_invocation(["add", "a", "procedure"])


# -- treble-add (deterministic bootstrap; no Von) ----------------------------


def test_add_registers_procedure(project_cwd: Path) -> None:
    result = runner.invoke(
        add_app, ["echo hello", "--name", "hello", "--description", "Say hello"]
    )
    assert result.exit_code == 0, result.output
    assert (project_cwd / ".treble" / "procedures" / "hello.yaml").exists()


def test_add_rejects_empty_command(project_cwd: Path) -> None:
    result = runner.invoke(add_app, ["   ", "--name", "x", "--description", "y"])
    assert result.exit_code != 0


def test_add_duplicate_prints_clean_error(project_cwd: Path) -> None:
    first = runner.invoke(
        add_app, ["echo hello", "--name", "hello", "--description", "Say hello"]
    )
    assert first.exit_code == 0
    second = runner.invoke(
        add_app, ["echo bye", "--name", "hello", "--description", "Say goodbye"]
    )
    assert second.exit_code == 1
    assert "Traceback" not in second.output
    assert "already exists" in second.output
    assert "overwrite" in second.output


def test_add_duplicate_with_overwrite(project_cwd: Path) -> None:
    runner.invoke(add_app, ["echo hello", "--name", "hello", "--description", "Say hello"])
    result = runner.invoke(
        add_app,
        ["echo bye", "--name", "hello", "--description", "Say goodbye", "--overwrite"],
    )
    assert result.exit_code == 0
    assert "registered" in result.output


# -- literal deterministic subcommands (no Von) ------------------------------


def _register(project_cwd: Path) -> None:
    result = runner.invoke(
        add_app, ["echo hello", "--name", "hello", "--description", "Say hello"]
    )
    assert result.exit_code == 0, result.output


def test_list_empty(project_cwd: Path) -> None:
    result = runner.invoke(main_app, ["list"])
    assert result.exit_code == 0
    assert "no procedures" in result.output


def test_list_after_register(project_cwd: Path) -> None:
    _register(project_cwd)
    result = runner.invoke(main_app, ["list"])
    assert result.exit_code == 0
    assert "hello" in result.output


def test_show(project_cwd: Path) -> None:
    _register(project_cwd)
    result = runner.invoke(main_app, ["show", "hello"])
    assert result.exit_code == 0
    assert "executable: echo" in result.output


def test_show_missing(project_cwd: Path) -> None:
    result = runner.invoke(main_app, ["show", "nope"])
    assert result.exit_code == 2


def test_remove_subcommand(project_cwd: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _register(project_cwd)
    monkeypatch.setattr("typer.confirm", lambda *a, **k: True)  # approve
    result = runner.invoke(main_app, ["remove", "hello"])
    assert result.exit_code == 0
    assert not (project_cwd / ".treble" / "procedures" / "hello.yaml").exists()


def test_remove_subcommand_declined_keeps_procedure(
    project_cwd: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The literal `remove` confirms like the model path (no outright delete)."""
    _register(project_cwd)
    monkeypatch.setattr("typer.confirm", lambda *a, **k: False)  # decline
    result = runner.invoke(main_app, ["remove", "hello"])
    assert result.exit_code == 4  # EXIT_DENIED
    assert (project_cwd / ".treble" / "procedures" / "hello.yaml").exists()


def test_explain_subcommand(project_cwd: Path) -> None:
    _register(project_cwd)
    result = runner.invoke(main_app, ["explain", "hello"])
    assert result.exit_code == 0
    assert "procedure: hello" in result.output
    assert "argv:      echo hello" in result.output


def test_stats_subcommand_empty(project_cwd: Path) -> None:
    result = runner.invoke(main_app, ["stats"])
    assert result.exit_code == 0
    assert "no Treble activity" in result.output


def test_stats_subcommand_json(project_cwd: Path) -> None:
    import json

    result = runner.invoke(main_app, ["stats", "--json"])
    assert result.exit_code == 0
    assert "executions" in json.loads(result.output)


# -- Von-routed free-form path ------------------------------------------------


def test_run_executes_via_von(project_cwd: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _register(project_cwd)
    client = _select_client(ProcedureStore(project_cwd), "hello")
    _patch_von(monkeypatch, client)
    result = runner.invoke(main_app, ["run", "hello"])
    assert result.exit_code == 0, result.output
    assert "hello" in result.output
    # bare name: the run gate is skipped by the bare-name signal; Von's
    # run-target Choice selects the procedure.
    assert [c[0] for c in client.calls] == ["choose"]
    assert (project_cwd / ".treble" / "audit.jsonl").exists()


def test_run_dry_run_via_von(project_cwd: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``--dry-run`` before the intent is Treble's (positional ownership)."""
    _register(project_cwd)
    client = _select_client(ProcedureStore(project_cwd), "hello")
    _patch_von(monkeypatch, client)
    result = runner.invoke(main_app, ["run", "--dry-run", "hello"])
    assert result.exit_code == 0
    assert "[dry-run] would execute: echo hello" in result.output


def test_leading_global_flag_dispatcher(
    project_cwd: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`treble --dry-run run hello` treats the leading flag as Treble's."""
    _register(project_cwd)
    client = _select_client(ProcedureStore(project_cwd), "hello")
    _patch_von(monkeypatch, client)
    import sys

    from treble.cli.main import main

    original = sys.argv
    try:
        sys.argv = ["treble", "--dry-run", "run", "hello"]
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code in (0, None)
    finally:
        sys.argv = original


def test_unknown_leading_flag_errors(project_cwd: Path, capsys) -> None:
    import sys

    from treble.cli.main import main

    original = sys.argv
    try:
        sys.argv = ["treble", "--watch", "hello"]
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 2
    finally:
        sys.argv = original
    assert "unknown Treble option '--watch'" in capsys.readouterr().err


def test_trailing_flag_is_forwarded_to_command(project_cwd: Path) -> None:
    """`treble hello --verbose` is the command's flag, not Treble's."""
    _register(project_cwd)
    result = runner.invoke(main_app, ["run", "hello", "--verbose"])
    assert result.exit_code == 0
    assert "hello --verbose" in result.output


def test_run_fails_closed_when_von_down(
    project_cwd: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import httpx

    _register(project_cwd)
    client = FakeSystemOneClient(error=httpx.ConnectError("down"))
    _patch_von(monkeypatch, client)
    result = runner.invoke(main_app, ["run", "hello"])
    assert result.exit_code == 6
    assert "Treble's decision service is unreachable" in result.output


def test_bare_intent_dispatches_to_run(
    project_cwd: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`treble hello` behaves like `treble run hello` (routed through Von)."""
    _register(project_cwd)
    client = _select_client(ProcedureStore(project_cwd), "hello")
    _patch_von(monkeypatch, client)
    import sys

    from treble.cli.main import main

    original = sys.argv
    try:
        sys.argv = ["treble", "hello"]
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code in (0, None)
    finally:
        sys.argv = original
    assert [c[0] for c in client.calls] == ["choose"]


def test_freeform_control_command_routes_to_von(
    project_cwd: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """`treble show me the hello procedure` routes through Von (not the literal
    `show` sub-command, which only accepts a single name)."""
    _register(project_cwd)
    from treble.decision.prompts import build_control_verb_options
    from treble.decision.testing import make_answer

    store = ProcedureStore(project_cwd)
    verb_opts = build_control_verb_options()
    verb_probs = {k: 0.005 for k in verb_opts}
    verb_probs["show"] = 0.95
    target_opts = {p.name: p.description for p in store.list_all()}
    target_opts["none-of-the-above"] = "none"
    target_probs = {k: 0.005 for k in target_opts}
    target_probs["hello"] = 0.95
    client = FakeSystemOneClient(
        noul_probability=0.1,  # control path
        answers=[make_answer("show", verb_probs), make_answer("hello", target_probs)],
    )
    _patch_von(monkeypatch, client)

    import sys

    from treble.cli.main import main

    original = sys.argv
    try:
        sys.argv = ["treble", "show", "me", "the", "hello", "procedure"]
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code in (0, None)
    finally:
        sys.argv = original
    assert "executable: echo" in capsys.readouterr().out
    # The leading "show" is an inspect-precedence signal, so the run gate is
    # bypassed and the control path runs directly: verb Choice + target Choice.
    assert [c[0] for c in client.calls] == ["choose", "choose"]
