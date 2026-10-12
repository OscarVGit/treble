"""Unit tests for the deterministic execution runtime (Layer 5)."""

from __future__ import annotations

import sys
from pathlib import Path

from treble.registry import Procedure, RiskLevel
from treble.registry.models import Verifier
from treble.runtime import (
    AuditRecord,
    PolicyDecision,
    SafetyPolicy,
    append_audit,
    build_environment,
    execute,
    read_audit,
    redact,
    verify,
)


def test_execute_captures_output(echo_proc: Procedure, tmp_path: Path) -> None:
    result = execute(echo_proc, cwd=tmp_path)
    assert result.succeeded
    assert result.stdout.strip() == "hello"
    assert result.exit_code == 0


def test_execute_missing_executable(tmp_path: Path) -> None:
    proc = Procedure(
        name="missing", description="x", executable="definitely-not-a-real-binary"
    )
    result = execute(proc, cwd=tmp_path)
    assert not result.succeeded
    assert result.error is not None
    assert result.exit_code == 127


def test_execute_timeout(tmp_path: Path) -> None:
    proc = Procedure(
        name="slow",
        description="x",
        executable=sys.executable,
        args=["-c", "import time; time.sleep(5)"],
    )
    result = execute(proc, cwd=tmp_path, timeout_s=0.2)
    assert result.timed_out
    assert not result.succeeded


def test_execute_applies_env_vars(tmp_path: Path) -> None:
    proc = Procedure(
        name="print-env",
        description="x",
        executable=sys.executable,
        args=["-c", "import os; print(os.environ.get('TREBLE_TEST_MARKER', ''))"],
        env_vars={"TREBLE_TEST_MARKER": "present"},
    )
    result = execute(proc, cwd=tmp_path)
    assert result.stdout.strip() == "present"


def test_build_environment_unset_on_empty(monkeypatch) -> None:
    monkeypatch.setenv("TREBLE_TEST_TO_UNSET", "value")
    env = build_environment({"TREBLE_TEST_TO_UNSET": ""})
    assert "TREBLE_TEST_TO_UNSET" not in env


def test_redact_masks_secret_keys() -> None:
    redacted = redact({"NORMAL": "ok", "MY_SECRET_TOKEN": "hunter2"})
    assert redacted["NORMAL"] == "ok"
    assert redacted["MY_SECRET_TOKEN"] == "***"


def test_verify_expected_exit_code(echo_proc: Procedure, tmp_path: Path) -> None:
    result = execute(echo_proc, cwd=tmp_path)
    outcome = verify(Verifier(expected_exit_code=0), result, cwd=tmp_path)
    assert outcome.passed
    bad = verify(Verifier(expected_exit_code=1), result, cwd=tmp_path)
    assert not bad.passed


def test_verify_stdout_contains(echo_proc: Procedure, tmp_path: Path) -> None:
    result = execute(echo_proc, cwd=tmp_path)
    assert verify(Verifier(stdout_contains="hello"), result, cwd=tmp_path).passed
    assert not verify(Verifier(stdout_contains="goodbye"), result, cwd=tmp_path).passed


def test_policy_read_only_allowed(echo_proc: Procedure) -> None:
    assert SafetyPolicy().decide(echo_proc) is PolicyDecision.ALLOW


def test_policy_mutating_needs_confirmation() -> None:
    proc = Procedure(name="m", description="x", executable="echo", risk=RiskLevel.MUTATING)
    assert SafetyPolicy().decide(proc) is PolicyDecision.CONFIRM


def test_policy_destructive_needs_confirmation() -> None:
    proc = Procedure(name="d", description="x", executable="echo", risk=RiskLevel.DESTRUCTIVE)
    assert SafetyPolicy().decide(proc) is PolicyDecision.CONFIRM


def test_policy_unapproved_denied() -> None:
    proc = Procedure(
        name="u",
        description="x",
        executable="echo",
        provenance={"approved": False},
    )
    assert SafetyPolicy().decide(proc) is PolicyDecision.DENY


def test_audit_round_trip(echo_proc: Procedure, tmp_path: Path) -> None:
    result = execute(echo_proc, cwd=tmp_path)
    path = append_audit(AuditRecord.from_execution(result, verified=True), cwd=tmp_path)
    entries = read_audit(tmp_path)
    assert path.exists()
    assert len(entries) == 1
    entry = entries[0]
    assert entry["procedure"] == "echo-hello"
    assert entry["verified"] is True
    assert entry["argv"] == ["echo", "hello"]


def test_audit_redacts_env(echo_proc: Procedure, tmp_path: Path) -> None:
    proc = echo_proc.model_copy(update={"env_vars": {"MY_SECRET": "hunter2"}})
    result = execute(proc, cwd=tmp_path)
    append_audit(AuditRecord.from_execution(result, verified=True), cwd=tmp_path)
    entry = read_audit(tmp_path)[0]
    assert entry["extra_env_redacted"]["MY_SECRET"] == "***"
