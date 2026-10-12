"""``treble-add`` — register a new procedure.

Implemented as a Typer app so ``treble add`` can share the same logic.
The exact argument placement the user provides is preserved verbatim.
"""

from __future__ import annotations

import shlex
from pathlib import Path

import typer

from treble.registry import Procedure, ProcedureStore, RiskLevel, Scope

app = typer.Typer(
    name="treble-add",
    help="Register a command procedure with Treble.",
    add_completion=False,
    no_args_is_help=True,
)


def register(
    *,
    name: str,
    command: str,
    description: str,
    scope: Scope,
    risk: RiskLevel,
    cwd: Path | None = None,
    overwrite: bool = False,
) -> Path:
    """Core registration logic, shared between the two CLI entry points."""
    argv = shlex.split(command)
    if not argv:
        msg = "command must not be empty"
        raise typer.BadParameter(msg)
    procedure = Procedure(
        name=name,
        description=description,
        executable=argv[0],
        args=argv[1:],
        scope=scope,
        risk=risk,
    )
    return ProcedureStore(cwd).add(procedure, overwrite=overwrite)


@app.command()
def main(
    command: str = typer.Argument(..., help="Exact command, e.g. 'pnpm run check --no-verify'."),
    name: str = typer.Option(..., "--name", "-n", help="Unique procedure name."),
    description: str = typer.Option(..., "--description", "-d", help="What this procedure does."),
    scope: Scope = typer.Option(Scope.PROJECT, "--scope", "-s", help="Where to store it."),
    risk: RiskLevel = typer.Option(RiskLevel.READ_ONLY, "--risk", "-r", help="Side-effect level."),
    overwrite: bool = typer.Option(False, "--overwrite", help="Replace an existing procedure."),
) -> None:
    """Register a procedure under the current project (or personal scope)."""
    path = register(
        name=name,
        command=command,
        description=description,
        scope=scope,
        risk=risk,
        overwrite=overwrite,
    )
    typer.echo(f"registered {name!r} → {path}")
