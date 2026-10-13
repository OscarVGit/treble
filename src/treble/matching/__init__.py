"""Layer 3 — procedure metadata utilities.

Treble's decision path routes every free-form request through Von; there is
no deterministic matcher that *decides* which procedure to run. The one
exception is argument forwarding (``forward.py``): when the leading tokens
exactly match a registered identifier plus trailing flags, the request is
forwarded deterministically. That is argument forwarding, not procedure
selection — Von is never asked to pick in that case.

The precondition helpers here are retained as runtime utilities (declared
procedure metadata), not as decision inputs — the option set handed to Von
is the full enabled registry, unfiltered by environment.
"""

from treble.matching.forward import ForwardMatch, match_forward
from treble.matching.preconditions import environment_satisfies, filter_by_environment

__all__ = [
    "ForwardMatch",
    "environment_satisfies",
    "filter_by_environment",
    "match_forward",
]
