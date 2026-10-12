"""Sandbox policy — placeholder for host-environment permission checks.

MVP: no automatic permission escalation. This module defines the shape of
the policy so Milestone 3 can plug in real sandbox/permission checks
without touching the executor.
"""

from __future__ import annotations

from dataclasses import dataclass

from treble.registry.models import Procedure


@dataclass(frozen=True)
class SandboxPolicy:
    """What the host environment is allowed to do."""

    allow_network: bool = True
    allow_write_outside_cwd: bool = False


def check_sandbox(procedure: Procedure, policy: SandboxPolicy) -> list[str]:
    """Return a list of violations; empty means OK to proceed."""
    _ = (procedure, policy)
    return []
