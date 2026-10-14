"""``treble remove <name>`` — delete a procedure."""

from __future__ import annotations

import typer

from treble.cli.commands._pipeline import remove_procedure_by_name


def remove(name: str = typer.Argument(..., help="Procedure name.")) -> None:
    """Delete the named procedure (asks for confirmation)."""
    raise typer.Exit(remove_procedure_by_name(name))
