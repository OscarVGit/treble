"""``treble explain <name>`` — show the execution plan for a procedure."""

from __future__ import annotations

from pathlib import Path

import typer

from treble.registry import ProcedureNotFound, ProcedureStore


def explain(name: str = typer.Argument(..., help="Procedure name.")) -> None:
    """Print what Treble would run for the named procedure, and its constraints."""
    try:
        procedure = ProcedureStore().get(name)
    except ProcedureNotFound as exc:
        typer.secho(str(exc), fg="red", err=True)
        raise typer.Exit(2) from exc
    typer.echo(f"procedure: {procedure.name}")
    typer.echo(f"argv:      {' '.join(procedure.invocation())}")
    typer.echo(f"risk:      {procedure.risk}")
    typer.echo(f"cwd:       {procedure.working_dir or Path.cwd()}")
    if procedure.verify.expected_exit_code != 0:
        typer.echo(f"verify:    exit code must be {procedure.verify.expected_exit_code}")
