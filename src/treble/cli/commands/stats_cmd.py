"""``treble stats`` — summarize local usage from the audit and events logs."""

from __future__ import annotations

import typer

from treble.reporting import render_stats, stats_json


def stats_cmd(
    json_out: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """Show usage: requests, routing, executions, hot and unused procedures."""
    typer.echo(stats_json() if json_out else render_stats())
