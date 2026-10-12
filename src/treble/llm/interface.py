"""Contract for LLM-assisted procedure authoring (Milestone 4).

The key safety property: implementations return *proposals*. Treble never
turns a proposal into an executable procedure without explicit human
review and registration through the normal ``treble-add`` path.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class ProcedureProposal:
    """A draft procedure suggested by an LLM. Not yet executable."""

    name: str
    description: str
    executable: str
    args: list[str] = field(default_factory=list)
    rationale: str = ""


class ProcedureAuthor(Protocol):
    """Interface every LLM escalation backend must satisfy."""

    def propose(self, intent: str, context: str) -> ProcedureProposal:
        """Return a draft procedure for human review. Never executes anything."""
        ...
