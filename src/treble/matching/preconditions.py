"""Environment precondition filtering (Milestone 3 groundwork).

Deterministic checks: is the executable on PATH, do required env vars
exist, does the working directory satisfy the declared constraint?
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from treble.registry.models import Precondition, Procedure


def environment_satisfies(precondition: Precondition, cwd: Path | None = None) -> bool:
    """True iff every declared precondition holds in the current environment."""
    if precondition.executable and shutil.which(precondition.executable) is None:
        return False
    for var in precondition.env_vars_present:
        if var not in os.environ:
            return False
    if precondition.cwd_contains:
        base = (cwd or Path.cwd()).resolve()
        if precondition.cwd_contains not in str(base):
            return False
    return True


def filter_by_environment(
    procedures: list[Procedure], cwd: Path | None = None
) -> list[Procedure]:
    """Drop procedures whose preconditions the environment does not satisfy."""
    return [p for p in procedures if environment_satisfies(p.preconditions, cwd)]
