"""``treble doctor`` — check the install, the decision service and the registry."""

from __future__ import annotations

import importlib.util
import sys
from urllib.parse import urlparse, urlunparse

import httpx
import typer

from treble.config import TrebleConfig
from treble.registry import InvalidProcedure, ProcedureStore


def _mcp_installed() -> bool:
    return importlib.util.find_spec("mcp") is not None


def _health_url(base_url: str) -> str:
    parts = urlparse(base_url)
    return urlunparse((parts.scheme, parts.netloc, "/health", "", "", ""))


def _von_reachable(base_url: str) -> bool:
    try:
        response = httpx.get(_health_url(base_url), timeout=3.0)
    except (httpx.HTTPError, OSError):
        return False
    return response.status_code == 200


def doctor_cmd(
    von: bool = typer.Option(True, "--von/--no-von", help="Probe the Von endpoint."),
) -> None:
    """Report whether Treble is ready to use in this repo.

    Von is *optional*: when it is unreachable the deterministic paths
    (``list``/``test``/forwarding/``stats``) still work — only free-form
    routing needs it. A broken registry is the only hard failure.
    """
    cfg = TrebleConfig.load()
    ok = True

    typer.echo(f"python        {sys.version.split()[0]}")
    typer.echo(f"von url       {cfg.von_base_url}")
    typer.echo(f"variant       {cfg.variant}")
    if _mcp_installed():
        typer.echo("mcp           available (treble-mcp)")
    else:
        typer.echo("mcp           not installed (pip install 'treble[mcp]')")

    if von:
        if _von_reachable(cfg.von_base_url):
            typer.secho("von           reachable", fg="green")
        else:
            typer.secho("von           unreachable", fg="yellow")
            typer.echo(
                "              free-form routing is off; deterministic paths still work:"
            )
            typer.echo(
                "              treble list · treble test <name> · treble <name> --flag"
            )

    try:
        procedures = ProcedureStore().list_all()
    except InvalidProcedure as exc:
        ok = False
        typer.secho(f"registry      INVALID: {exc}", fg="red")
    else:
        count = len(procedures)
        typer.secho(f"registry      {count} procedure(s)", fg="green")
        for procedure in procedures:
            typer.echo(f"              {procedure.name}  [{procedure.risk}]")

    raise typer.Exit(0 if ok else 1)
