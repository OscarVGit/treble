"""``treble add`` — alias for the ``treble-add`` console script."""

from __future__ import annotations

import typer

from treble.cli.add import register
from treble.registry import DuplicateProcedure, RiskLevel, Scope


def add_cmd(
    command: str = typer.Argument(..., help="Exact command to register."),
    name: str = typer.Option(..., "--name", "-n"),
    description: str = typer.Option(..., "--description", "-d"),
    scope: Scope = typer.Option(Scope.PROJECT, "--scope", "-s"),
    risk: RiskLevel = typer.Option(RiskLevel.READ_ONLY, "--risk", "-r"),
    alias: list[str] = typer.Option([], "--alias", "-a", help="Alternative name (repeatable)."),
    overwrite: bool = typer.Option(False, "--overwrite"),
) -> None:
    """Register a procedure (same implementation as ``treble-add``)."""
    try:
        path = register(
            name=name,
            command=command,
            description=description,
            scope=scope,
            risk=risk,
            aliases=alias,
            overwrite=overwrite,
        )
    except DuplicateProcedure:
        typer.secho(
            f"a procedure named {name!r} already exists. "
            "Re-run with --overwrite to replace it, or pick another name.",
            fg="yellow",
            err=True,
        )
        raise typer.Exit(1) from None
    typer.echo(f"registered {name!r} → {path}")
