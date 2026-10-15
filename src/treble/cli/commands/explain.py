"""``treble explain <name>`` — show the execution plan for a procedure."""

from __future__ import annotations

import typer

from treble.cli.commands._pipeline import explain_procedure


def explain(name: str = typer.Argument(..., help="Procedure name.")) -> None:
    """Print what Treble would run for the named procedure, and its constraints."""
    raise typer.Exit(explain_procedure(name))
