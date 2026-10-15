"""Tests for the transport-agnostic MCP/agent operations.

These exercise the same pipeline the CLI uses, under a captured I/O adapter.
No MCP SDK is required.
"""

from __future__ import annotations

from pathlib import Path

from treble.decision.prompts import build_run_target_options
from treble.decision.testing import FakeSystemOneClient, make_answer
from treble.mcp import tools
from treble.registry import Procedure, ProcedureStore, RiskLevel


def _seed(cwd: Path) -> None:
    store = ProcedureStore(cwd)
    store.add(Procedure(name="build", description="Build", executable="echo", args=["built"]))
    store.add(
        Procedure(
            name="wipe",
            description="Delete caches",
            executable="echo",
            args=["wiped"],
            risk=RiskLevel.DESTRUCTIVE,
        )
    )


def test_list_procedures(project_cwd: Path) -> None:
    _seed(project_cwd)
    result = tools.list_procedures(cwd=project_cwd)
    assert result["status"] == "ok"
    assert "build" in result["stdout"]
    assert "wipe" in result["stdout"]


def test_run_named_read_only_executes(project_cwd: Path) -> None:
    _seed(project_cwd)
    result = tools.run_named("build", cwd=project_cwd)
    assert result["status"] == "ok"
    assert result["exit_code"] == 0
    assert "built" in result["stdout"]


def test_run_named_destructive_requires_confirmation(project_cwd: Path) -> None:
    _seed(project_cwd)
    result = tools.run_named("wipe", cwd=project_cwd)
    assert result["status"] == "confirmation_required"
    assert result["prompt"]
    assert result["stdout"] == ""  # did not execute


def test_run_named_destructive_with_yes_executes(project_cwd: Path) -> None:
    _seed(project_cwd)
    result = tools.run_named("wipe", yes=True, cwd=project_cwd)
    assert result["status"] == "ok"
    assert "wiped" in result["stdout"]


def test_remove_requires_confirmation(project_cwd: Path) -> None:
    _seed(project_cwd)
    result = tools.remove_procedure("build", cwd=project_cwd)
    assert result["status"] == "confirmation_required"
    assert ProcedureStore(project_cwd).get("build").name == "build"  # still there


def test_remove_with_yes(project_cwd: Path) -> None:
    _seed(project_cwd)
    result = tools.remove_procedure("build", yes=True, cwd=project_cwd)
    assert result["status"] == "ok"
    assert "removed" in result["stdout"]


def test_run_intent_routes_through_the_model(project_cwd: Path) -> None:
    _seed(project_cwd)
    options = build_run_target_options(ProcedureStore(project_cwd).list_all())
    client = FakeSystemOneClient(
        noul_probability=0.9,
        answer=make_answer("build", {k: 0.01 for k in options} | {"build": 0.9}),
    )
    result = tools.run_intent("build the project", cwd=project_cwd, client=client)
    assert result["status"] == "ok"
    assert "built" in result["stdout"]


def test_show_and_explain(project_cwd: Path) -> None:
    _seed(project_cwd)
    assert "executable: echo" in tools.show_procedure("build", cwd=project_cwd)["stdout"]
    explained = tools.explain_procedure("build", cwd=project_cwd)["stdout"]
    assert "argv:      echo built" in explained
