"""Layer 6 — LLM escalation and procedure authoring.

**Deferred per README Milestone 4.** This package defines the contract
only; no LLM client is wired in the MVP. Any implementation must satisfy
:class:`treble.llm.interface.ProcedureAuthor` and must return *proposals*
that a human reviews before registration — never auto-executed commands.
"""

from treble.llm.interface import ProcedureAuthor, ProcedureProposal

__all__ = ["ProcedureAuthor", "ProcedureProposal"]
