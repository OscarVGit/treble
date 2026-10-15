"""``treble show <name>`` — display one procedure in full."""

from __future__ import annotations

import typer

from treble.cli.commands._pipeline import show_procedure


def show(name: str = typer.Argument(..., help="Procedure name.")) -> None:
    """Render the procedure as YAML (what Treble will actually run)."""
    raise typer.Exit(show_procedure(name))
