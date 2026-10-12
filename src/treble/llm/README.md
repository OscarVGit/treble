# treble.llm — deferred to Milestone 4

This package intentionally contains only the authoring **contract**
(`interface.py`). No LLM client is wired in the MVP, per the README's
Milestone ordering.

When implemented, an author must:

1. Return a `ProcedureProposal` — a draft, never an executable.
2. Surface the proposal to the user for explicit review.
3. Register only after approval, via the normal `treble-add` path.

The LLM must never bypass the runtime's permission checks or convert an
untrusted registry entry into a shell command.
