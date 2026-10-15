"""``treble list`` — show all visible procedures."""

from __future__ import annotations

import typer

from treble.cli.commands._pipeline import list_procedures


def list_cmd() -> None:
    """Print every procedure visible from the current working directory."""
    raise typer.Exit(list_procedures())
