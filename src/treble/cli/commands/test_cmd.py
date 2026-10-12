"""``treble test <name>`` — execute a known procedure by name."""

from __future__ import annotations

import typer

from treble.cli.commands._pipeline import run_procedure_by_name


def test_cmd(
    name: str = typer.Argument(..., help="Procedure name."),
    yes: bool = typer.Option(False, "--yes", "-y"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Run a procedure directly by name, bypassing decision-model routing."""
    raise typer.Exit(run_procedure_by_name(name, dry_run=dry_run, assume_yes=yes))
