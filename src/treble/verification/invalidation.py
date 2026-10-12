"""Procedure invalidation detection.

Compares a stored procedure's fingerprint against recorded outcomes and
flags procedures whose environment has drifted since they last passed.
MVP: report-only, no automatic disabling.
"""

from __future__ import annotations

from dataclasses import dataclass

from treble.registry.models import Procedure


@dataclass(frozen=True)
class InvalidationReport:
    """Outcome of an invalidation check."""

    procedure: str
    stale: bool
    reason: str | None = None


def detect_invalidation(
    procedure: Procedure, last_seen_fingerprint: str | None
) -> InvalidationReport:
    """Flag a procedure whose content changed since last successful run."""
    if last_seen_fingerprint is None:
        return InvalidationReport(procedure.name, stale=False, reason=None)
    if procedure.fingerprint() != last_seen_fingerprint:
        return InvalidationReport(
            procedure.name, stale=True, reason="procedure content changed since last success"
        )
    return InvalidationReport(procedure.name, stale=False, reason=None)
