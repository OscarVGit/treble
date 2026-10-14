"""``treble init`` — scaffold a project-local registry in another repo."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from treble.config import project_treble_dir

_GITIGNORE_BLOCK = (
    "\n# Treble: commit .treble/procedures, ignore runtime state\n"
    ".treble/events.jsonl\n"
    ".treble/audit.jsonl\n"
    ".treble/outcomes.jsonl\n"
    ".treble/von.log\n"
)


def init_cmd(
    package_json: bool = typer.Option(
        False, "--package-json", help="Print a package.json scripts snippet."
    ),
) -> None:
    """Create ``.treble/procedures/``, update ``.gitignore``, and print next steps."""
    cwd = Path.cwd()
    procedures = project_treble_dir(cwd) / "procedures"
    procedures.mkdir(parents=True, exist_ok=True)
    typer.secho(f"created {procedures}", fg="green")

    gitignore = cwd / ".gitignore"
    existing = gitignore.read_text(encoding="utf-8") if gitignore.is_file() else ""
    if ".treble/events.jsonl" in existing:
        typer.echo(f"{gitignore} already ignores Treble runtime state")
    else:
        with gitignore.open("a", encoding="utf-8") as fh:
            fh.write(_GITIGNORE_BLOCK)
        typer.secho(f"updated {gitignore}", fg="green")

    typer.echo("\nnext steps:")
    typer.echo(
        "  1. register a command:\n"
        "       treble-add '<exact command>' --name <slug> "
        "--description '<what it does>' --risk read-only|mutating|destructive"
    )
    typer.echo("  2. commit the registry so the team shares it:")
    typer.echo("       git add .treble/procedures .gitignore && git commit")

    if package_json or (cwd / "package.json").is_file():
        snippet = {
            "scripts": {
                "check": "treble test check-no-verify",
                "build": "treble test build",
                "treble:list": "treble list",
                "treble:stats": "treble stats",
            }
        }
        typer.echo("\npackage.json scripts (names must match your registered procedures):")
        typer.echo(json.dumps(snippet, indent=2))
