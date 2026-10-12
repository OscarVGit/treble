"""``treble show <name>`` — display one procedure in full."""

from __future__ import annotations

import typer
import yaml

from treble.registry import ProcedureNotFound, ProcedureStore
from treble.registry.models import procedure_to_yaml_dict


def show(name: str = typer.Argument(..., help="Procedure name.")) -> None:
    """Render the procedure as YAML (what Treble will actually run)."""
    try:
        procedure = ProcedureStore().get(name)
    except ProcedureNotFound as exc:
        typer.secho(str(exc), fg="red", err=True)
        raise typer.Exit(2) from exc
    typer.echo(yaml.safe_dump(procedure_to_yaml_dict(procedure), sort_keys=False))
