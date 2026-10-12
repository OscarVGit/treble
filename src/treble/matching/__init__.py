"""Layer 3 — procedure metadata utilities.

Treble's decision path routes every free-form request through Von; there is
no deterministic matcher that *decides* which procedure to run. The
precondition helpers here are retained as runtime utilities (declared
procedure metadata), not as decision inputs — the option set handed to Von
is the full enabled registry, unfiltered by environment.
"""

from treble.matching.preconditions import environment_satisfies, filter_by_environment

__all__ = [
    "environment_satisfies",
    "filter_by_environment",
]
