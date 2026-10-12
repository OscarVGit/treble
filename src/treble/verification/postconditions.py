"""Postcondition vocabulary.

MVP supports a small fixed set; the registry's :class:`Verifier` mirrors
these. Keeping the names in one place makes adding new kinds explicit.
"""

from __future__ import annotations

from enum import StrEnum


class Postcondition(StrEnum):
    """Kinds of post-execution checks Treble knows how to run."""

    EXIT_CODE = "exit-code"
    STDOUT_CONTAINS = "stdout-contains"
    STDERR_EMPTY = "stderr-empty"
    ARTIFACT_EXISTS = "artifact-exists"
