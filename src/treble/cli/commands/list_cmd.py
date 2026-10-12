"""``treble list`` — show all visible procedures."""

from __future__ import annotations

import typer

from treble.registry import ProcedureStore


def list_cmd() -> None:
    """Print every procedure visible from the current working directory."""
    procedures = ProcedureStore().list_all()
    if not procedures:
        typer.echo("no procedures registered")
        return
    for proc in procedures:
        typer.echo(f"{proc.name:24s} [{proc.scope:8s}] [{proc.risk:11s}] {proc.description}")
