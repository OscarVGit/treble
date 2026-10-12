"""``treble`` — main CLI entry point.

Known sub-commands are dispatched by Typer. Anything else falls through to
``treble run`` so ``treble pnpm run check`` works as a bare invocation.
"""

from __future__ import annotations

import sys

import typer

from treble.cli.commands import add_cmd, explain, list_cmd, remove, show, test_cmd

_KNOWN_SUBCOMMANDS = {"add", "list", "show", "explain", "test", "remove", "run"}

app = typer.Typer(
    name="treble",
    help="Decision-driven command execution harness.",
    add_completion=False,
    no_args_is_help=True,
)

app.command("add")(add_cmd.add_cmd)
app.command("list")(list_cmd.list_cmd)
app.command("show")(show.show)
app.command("explain")(explain.explain)
app.command("test")(test_cmd.test_cmd)
app.command("remove")(remove.remove)


@app.command(
    "run",
    context_settings={
        "allow_extra_args": True,
        "allow_interspersed_args": False,
        "ignore_unknown_options": True,
    },
)
def run_command(
    ctx: typer.Context,
    intent: list[str] = typer.Argument(None, help="Command name, alias, or intent."),
    yes: bool = typer.Option(False, "--yes", "-y"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Execute the procedure best matching the intent."""
    tokens, extra_yes, extra_dry_run = _extract_flags([*intent, *ctx.args])
    from treble.cli.commands._pipeline import run_pipeline

    raise typer.Exit(
        run_pipeline(tokens, dry_run=dry_run or extra_dry_run, assume_yes=yes or extra_yes)
    )


def _extract_flags(tokens: list[str]) -> tuple[list[str], bool, bool]:
    """Pull ``--yes``/``--dry-run`` out of trailing intent tokens."""
    yes = dry_run = False
    kept: list[str] = []
    for token in tokens:
        if token in ("--yes", "-y"):
            yes = True
        elif token == "--dry-run":
            dry_run = True
        else:
            kept.append(token)
    return kept, yes, dry_run


# Sub-commands that take exactly one positional name and no options.
_ONE_ARG_SUBCOMMANDS = {"show", "explain", "remove"}
# Flags the literal ``test`` sub-command owns.
_TEST_FLAGS = {"-y", "--yes", "--dry-run"}
# Flags that mark an ``add`` invocation as the literal registration call.
_ADD_FLAGS = {"--name", "-n", "--command", "--description", "-d"}


def _is_literal_invocation(argv: list[str]) -> bool:
    """True iff ``argv`` is a clean, well-formed literal sub-command call.

    A sub-command is only treated as the deterministic literal path when the
    arguments fit its simple grammar. Otherwise (extra words, unknown options)
    the whole invocation is routed through Von as free-form intent, so that
    natural-language requests like ``remove the hello procedure`` work.
    """
    command, rest = argv[0], argv[1:]
    if command == "list":
        return not rest
    if command == "add":
        return any(flag in _ADD_FLAGS for flag in rest)
    if command in _ONE_ARG_SUBCOMMANDS:
        return len(rest) == 1 and not rest[0].startswith("-")
    if command == "test":
        positionals = [a for a in rest if not a.startswith("-")]
        flags = [a for a in rest if a.startswith("-")]
        return len(positionals) == 1 and all(f in _TEST_FLAGS for f in flags)
    return False


def main() -> None:
    """Dispatch.

    A known sub-command runs deterministically only when the invocation fits
    its literal grammar; every other non-flag invocation (including
    natural-language requests that happen to start with a sub-command word)
    is routed through Von via ``run``.
    """
    argv = sys.argv[1:]
    if not argv or argv[0].startswith("-") or argv[0] == "run":
        app()
        return
    if argv[0] in _KNOWN_SUBCOMMANDS and _is_literal_invocation(argv):
        app()
        return
    sys.argv = [sys.argv[0], "run", *argv]
    app()


if __name__ == "__main__":
    main()
