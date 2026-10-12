"""Post-execution verification of a procedure's declared postconditions."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from treble.registry.models import Verifier
from treble.runtime.executor import ExecutionResult


@dataclass
class VerificationOutcome:
    """Result of checking a procedure's postconditions."""

    passed: bool
    failures: list[str] = field(default_factory=list)


def verify(verifier: Verifier, result: ExecutionResult, cwd: Path | None = None) -> VerificationOutcome:
    """Evaluate every declared postcondition against an execution result."""
    failures: list[str] = []

    if result.timed_out:
        failures.append("execution timed out")

    if result.exit_code != verifier.expected_exit_code:
        failures.append(
            f"exit code {result.exit_code} != expected {verifier.expected_exit_code}"
        )

    if verifier.stdout_contains and verifier.stdout_contains not in result.stdout:
        failures.append(f"stdout does not contain {verifier.stdout_contains!r}")

    if verifier.stderr_empty and result.stderr.strip():
        failures.append("stderr was expected to be empty")

    if verifier.artifact_exists:
        base = (cwd or Path(result.cwd)).resolve()
        if not (base / verifier.artifact_exists).exists():
            failures.append(f"artifact {verifier.artifact_exists!r} not found")

    return VerificationOutcome(passed=not failures, failures=failures)
