"""Unit tests for the procedure registry."""

from __future__ import annotations

from pathlib import Path

import pytest

from treble.registry import (
    DuplicateProcedure,
    InvalidProcedure,
    Procedure,
    ProcedureNotFound,
    ProcedureStore,
    RiskLevel,
    Scope,
)


def test_add_and_get_round_trip(store: ProcedureStore, echo_proc: Procedure) -> None:
    store.add(echo_proc)
    loaded = store.get("echo-hello")
    assert loaded.name == "echo-hello"
    assert loaded.invocation() == ["echo", "hello"]


def test_add_duplicate_raises(store: ProcedureStore, echo_proc: Procedure) -> None:
    store.add(echo_proc)
    with pytest.raises(DuplicateProcedure):
        store.add(echo_proc)


def test_add_overwrite(store: ProcedureStore, echo_proc: Procedure) -> None:
    store.add(echo_proc)
    changed = echo_proc.model_copy(update={"description": "updated"})
    store.add(changed, overwrite=True)
    assert store.get("echo-hello").description == "updated"


def test_remove(store: ProcedureStore, echo_proc: Procedure) -> None:
    store.add(echo_proc)
    store.remove("echo-hello")
    with pytest.raises(ProcedureNotFound):
        store.get("echo-hello")


def test_get_missing_raises(store: ProcedureStore) -> None:
    with pytest.raises(ProcedureNotFound):
        store.get("nope")


def test_get_by_alias(store: ProcedureStore, check_no_verify_proc: Procedure) -> None:
    store.add(check_no_verify_proc)
    assert store.get("check-fast").name == "check-no-verify"


def test_list_all(store: ProcedureStore, echo_proc: Procedure, check_proc: Procedure) -> None:
    store.add(echo_proc)
    store.add(check_proc)
    assert {p.name for p in store.list_all()} == {"echo-hello", "check"}


def test_invalid_yaml_raises(store: ProcedureStore, project_cwd: Path) -> None:
    directory = project_cwd / ".treble" / "procedures"
    directory.mkdir(parents=True)
    (directory / "bad.yaml").write_text("not-a-mapping", encoding="utf-8")
    with pytest.raises(InvalidProcedure):
        store.list_all()


def test_secret_env_vars_rejected() -> None:
    with pytest.raises(ValueError, match="secret"):
        Procedure(
            name="x",
            description="y",
            executable="echo",
            env_vars={"API_SECRET": "hunter2"},
        )


def test_fingerprint_changes_with_content(echo_proc: Procedure) -> None:
    assert echo_proc.fingerprint() != echo_proc.model_copy(
        update={"description": "different"}
    ).fingerprint()


def test_risk_defaults_read_only(echo_proc: Procedure) -> None:
    assert echo_proc.risk is RiskLevel.READ_ONLY


def test_scope_defaults_project(echo_proc: Procedure) -> None:
    assert echo_proc.scope is Scope.PROJECT


def test_add_destructive_procedure_round_trips(
    store: ProcedureStore, project_cwd: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: non-default risk/scope enums must serialize to YAML."""
    monkeypatch.setattr(
        "treble.registry.paths.user_config_dir", lambda: project_cwd / ".home"
    )
    proc = Procedure(
        name="wipe",
        description="Delete the build cache",
        executable="rm",
        args=["-rf", "./cache"],
        risk=RiskLevel.DESTRUCTIVE,
        scope=Scope.PERSONAL,
    )
    store.add(proc)
    loaded = store.get("wipe")
    assert loaded.risk is RiskLevel.DESTRUCTIVE
    assert loaded.scope is Scope.PERSONAL
    assert loaded.invocation() == ["rm", "-rf", "./cache"]
