"""``treble`` — main CLI entry point.

Known sub-commands are dispatched by Typer. Anything else falls through to
``treble run`` so ``treble pnpm run check`` works as a bare invocation.
"""

from __future__ import annotations

import sys

import typer

from treble.cli.commands import (
    add_cmd,
    doctor_cmd,
    explain,
    init_cmd,
    list_cmd,
    remove,
    show,
    stats_cmd,
    test_cmd,
)
from treble.registry import RegistryError

_KNOWN_SUBCOMMANDS = {
    "add", "list", "show", "explain", "test", "remove", "run", "stats", "doctor", "init",
}

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
app.command("stats")(stats_cmd.stats_cmd)
app.command("doctor")(doctor_cmd.doctor_cmd)
app.command("init")(init_cmd.init_cmd)


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
    """Execute the procedure best matching the intent.

    Flags are positional: ``--yes``/``--dry-run`` before the intent are
    Treble's; every token after the identifier is forwarded to the command.
    """
    tokens = [*intent, *ctx.args]
    from treble.cli.commands._pipeline import run_pipeline

    raise typer.Exit(run_pipeline(tokens, dry_run=dry_run, assume_yes=yes))


# Treble's own global flags. They are only recognised *before* the first
# positional token (the procedure identifier). Ownership is positional:
# everything before the identifier is Treble's, everything after it belongs
# to the command — so there is no reserved-word escaping at all.
GLOBAL_FLAGS = {"--dry-run", "--yes", "-y"}

# Sub-commands that take exactly one positional name and no options.
_ONE_ARG_SUBCOMMANDS = {"show", "explain", "remove"}
# Flags the literal ``test`` sub-command owns.
_TEST_FLAGS = {"-y", "--yes", "--dry-run"}
# Flags that mark an ``add`` invocation as the literal registration call.
_ADD_FLAGS = {"--name", "-n", "--command", "--description", "-d", "--alias", "-a"}


def _split_leading_flags(argv: list[str]) -> tuple[list[str], list[str]]:
    """Split ``argv`` into (leading flag tokens, remaining args).

    Splits on token form (``-``-prefixed), not on known flags, so unknown
    leading flags can be reported as errors instead of leaking to Von.
    """
    i = 0
    while i < len(argv) and argv[i].startswith("-"):
        i += 1
    return argv[:i], argv[i:]


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
    if command == "stats":
        return all(flag == "--json" for flag in rest)
    if command == "doctor":
        return all(flag in {"--von", "--no-von"} for flag in rest)
    if command == "init":
        return all(flag == "--package-json" for flag in rest)
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
    try:
        _dispatch_main()
    except RegistryError as exc:
        typer.secho(str(exc), fg="red", err=True)
        raise typer.Exit(1) from None


def _dispatch_main() -> None:
    argv = sys.argv[1:]
    if not argv:
        app()
        return

    # Standard app options bypass global-flag handling.
    if argv[0] in ("--help", "-h", "--version"):
        app()
        return

    global_flags: list[str] = []
    if argv[0].startswith("-"):
        flags, rest = _split_leading_flags(argv)
        unknown = [f for f in flags if f not in GLOBAL_FLAGS]
        if unknown:
            typer.secho(
                f"unknown Treble option {unknown[0]!r}; flags for the command "
                "belong after the procedure name",
                fg="red",
                err=True,
            )
            raise SystemExit(2)
        global_flags = flags
        if not rest:
            app()
            return
        argv = rest

    if argv[0] == "run":
        # Globals drained: reinsert them as run's options before the intent.
        sys.argv = [sys.argv[0], "run", *global_flags, *argv[1:]]
        app()
        return
    if argv[0] in _KNOWN_SUBCOMMANDS and _is_literal_invocation(argv):
        # Literal control-plane sub-command: drop global flags (they are
        # meaningful only on the run path).
        sys.argv = [sys.argv[0], *argv]
        app()
        return
    sys.argv = [sys.argv[0], "run", *global_flags, *argv]
    app()


if __name__ == "__main__":
    main()
