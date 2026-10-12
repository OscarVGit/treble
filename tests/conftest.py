"""Shared test fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

from treble.registry import Procedure, ProcedureStore


@pytest.fixture()
def project_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An isolated project directory used as cwd."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture()
def store(project_cwd: Path) -> ProcedureStore:
    """A ProcedureStore rooted in the isolated project directory."""
    return ProcedureStore(project_cwd)


@pytest.fixture()
def echo_proc() -> Procedure:
    return Procedure(
        name="echo-hello",
        description="Print hello",
        executable="echo",
        args=["hello"],
    )


@pytest.fixture()
def check_proc() -> Procedure:
    return Procedure(
        name="check",
        description="Run project checks",
        executable="pnpm",
        args=["run", "check"],
    )


@pytest.fixture()
def check_no_verify_proc() -> Procedure:
    return Procedure(
        name="check-no-verify",
        description="Run project checks without verification",
        executable="pnpm",
        args=["run", "check", "--no-verify"],
        aliases=["check-fast"],
    )
