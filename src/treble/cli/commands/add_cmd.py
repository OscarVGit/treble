"""``treble add`` — alias for the ``treble-add`` console script."""

from __future__ import annotations

import typer

from treble.cli.add import register
from treble.registry import RiskLevel, Scope


def add_cmd(
    command: str = typer.Argument(..., help="Exact command to register."),
    name: str = typer.Option(..., "--name", "-n"),
    description: str = typer.Option(..., "--description", "-d"),
    scope: Scope = typer.Option(Scope.PROJECT, "--scope", "-s"),
    risk: RiskLevel = typer.Option(RiskLevel.READ_ONLY, "--risk", "-r"),
    overwrite: bool = typer.Option(False, "--overwrite"),
) -> None:
    """Register a procedure (same implementation as ``treble-add``)."""
    path = register(
        name=name,
        command=command,
        description=description,
        scope=scope,
        risk=risk,
        overwrite=overwrite,
    )
    typer.echo(f"registered {name!r} → {path}")
