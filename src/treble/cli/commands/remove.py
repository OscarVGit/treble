"""``treble remove <name>`` — delete a procedure."""

from __future__ import annotations

import typer

from treble.registry import ProcedureNotFound, ProcedureStore


def remove(name: str = typer.Argument(..., help="Procedure name.")) -> None:
    """Delete the named procedure from whichever scope holds it."""
    try:
        path = ProcedureStore().remove(name)
    except ProcedureNotFound as exc:
        typer.secho(str(exc), fg="red", err=True)
        raise typer.Exit(2) from exc
    typer.echo(f"removed {name!r} ({path})")
