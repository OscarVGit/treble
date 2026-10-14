"""End-to-end round-trip through the Von-routed pipeline."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from treble.cli.add import app as add_app
from treble.cli.main import app as main_app
from treble.decision.prompts import (
    NONE_OF_THE_ABOVE,
    build_run_target_options,
)
from treble.decision.testing import FakeSystemOneClient, make_answer
from treble.registry import ProcedureStore

runner = CliRunner()


def _probs(options: dict[str, str], winner: str, p: float = 0.95) -> dict[str, float]:
    probs = {k: 0.005 for k in options}
    probs[winner] = p
    return probs


def _client_selecting(store: ProcedureStore, name: str) -> FakeSystemOneClient:
    """Run-gate says run; target Choice picks ``name``."""
    options = build_run_target_options(store.list_all())
    return FakeSystemOneClient(
        noul_probability=0.9, answer=make_answer(name, _probs(options, name))
    )


def test_full_round_trip(project_cwd: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    add = runner.invoke(
        add_app,
        ["echo treble-works", "--name", "smoke", "--description", "Smoke-test procedure"],
    )
    assert add.exit_code == 0, add.output

    # Literal deterministic control-plane commands (no Von needed).
    listing = runner.invoke(main_app, ["list"])
    assert listing.exit_code == 0 and "smoke" in listing.output
    shown = runner.invoke(main_app, ["show", "smoke"])
    assert shown.exit_code == 0 and "treble-works" in shown.output
    explained = runner.invoke(main_app, ["explain", "smoke"])
    assert explained.exit_code == 0 and "procedure: smoke" in explained.output

    # Free-form execution routed through Von.
    store = ProcedureStore(project_cwd)
    client = _client_selecting(store, "smoke")
    monkeypatch.setattr("treble.cli.commands._pipeline.default_client", lambda cfg: client)
    ran = runner.invoke(main_app, ["run", "smoke"])
    assert ran.exit_code == 0, ran.output
    assert "treble-works" in ran.output
    # bare name: run gate skipped; Von's run-target Choice selects the procedure
    assert [c[0] for c in client.calls] == ["choose"]

    audit_file = project_cwd / ".treble" / "audit.jsonl"
    assert audit_file.exists()
    entry = json.loads(audit_file.read_text(encoding="utf-8").splitlines()[-1])
    assert entry["procedure"] == "smoke"
    assert entry["exit_code"] == 0
    assert entry["verified"] is True


def test_ambiguous_intent_clarifies(project_cwd: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for name, extra in (("check", []), ("check-fast", ["--no-verify"])):
        add = runner.invoke(
            add_app,
            [" ".join(["echo", name, *extra]), "--name", name, "--description", f"{name} procedure"],
        )
        assert add.exit_code == 0, add.output

    store = ProcedureStore(project_cwd)
    options = build_run_target_options(store.list_all())
    probs = {k: 0.005 for k in options}
    probs["check"] = 0.5
    probs["check-fast"] = 0.45  # within margin → showdown Noul rejects → CLARIFY
    client = FakeSystemOneClient(
        noul_series=[0.9, 0.1], answer=make_answer("check", probs)
    )
    monkeypatch.setattr("treble.cli.commands._pipeline.default_client", lambda cfg: client)

    result = runner.invoke(main_app, ["run", "check", "quickly"])
    assert result.exit_code == 7
    assert "ambiguous request" in result.output


def test_no_suitable_action_escalates(
    project_cwd: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner.invoke(
        add_app, ["echo hello", "--name", "hello", "--description", "Say hello"]
    )
    # Run-gate says run; the run-target Choice returns none-of-the-above.
    options = build_run_target_options(ProcedureStore(project_cwd).list_all())
    probs = {k: 0.005 for k in options}
    probs[NONE_OF_THE_ABOVE] = 0.9
    client = FakeSystemOneClient(
        noul_probability=0.9, answer=make_answer(NONE_OF_THE_ABOVE, probs)
    )
    monkeypatch.setattr("treble.cli.commands._pipeline.default_client", lambda cfg: client)
    result = runner.invoke(main_app, ["run", "deploy", "to", "production"])
    assert result.exit_code == 3
    assert "no suitable action" in result.output
