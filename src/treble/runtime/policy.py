"""Safety policy: decide whether a procedure may run without confirmation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from treble.registry.models import Procedure, RiskLevel


class PolicyDecision(StrEnum):
    """Outcome of applying the safety policy."""

    ALLOW = "allow"
    CONFIRM = "confirm"
    DENY = "deny"


@dataclass(frozen=True)
class SafetyPolicy:
    """Configurable gates; defaults follow the README's safety section."""

    auto_allow_read_only: bool = True
    auto_allow_mutating: bool = False
    auto_allow_destructive: bool = False
    allow_unapproved: bool = False

    def decide(self, procedure: Procedure) -> PolicyDecision:
        """Apply the policy to a single procedure."""
        if not procedure.provenance.approved and not self.allow_unapproved:
            return PolicyDecision.DENY
        if procedure.risk is RiskLevel.READ_ONLY and self.auto_allow_read_only:
            return PolicyDecision.ALLOW
        if procedure.risk is RiskLevel.MUTATING and self.auto_allow_mutating:
            return PolicyDecision.ALLOW
        if procedure.risk is RiskLevel.DESTRUCTIVE and self.auto_allow_destructive:
            return PolicyDecision.ALLOW
        return PolicyDecision.CONFIRM
