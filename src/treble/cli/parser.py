"""Request parsing.

Splits Treble's own flags from the user's intent tokens. Anything after
``--`` is treated as literal user intent and never parsed by Typer.
"""

from __future__ import annotations

from dataclasses import dataclass, field

TREBLE_FLAGS = {"--yes", "-y", "--dry-run", "--verbose", "-v", "--json"}


@dataclass(frozen=True)
class ParsedInvocation:
    """A Treble invocation split into flags and intent tokens."""

    tokens: list[str]
    dry_run: bool = False
    assume_yes: bool = False
    verbose: bool = False
    json_output: bool = False
    passthrough: list[str] = field(default_factory=list)


def parse_invocation(argv: list[str]) -> ParsedInvocation:
    """Parse ``argv`` (without program name) into Treble flags + intent."""
    tokens: list[str] = []
    passthrough: list[str] = []
    dry_run = assume_yes = verbose = json_output = False

    it = iter(range(len(argv)))
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--":
            passthrough = argv[i + 1 :]
            break
        if arg in ("--yes", "-y"):
            assume_yes = True
        elif arg == "--dry-run":
            dry_run = True
        elif arg in ("--verbose", "-v"):
            verbose = True
        elif arg == "--json":
            json_output = True
        else:
            tokens.append(arg)
        i += 1
    _ = it
    return ParsedInvocation(
        tokens=tokens,
        dry_run=dry_run,
        assume_yes=assume_yes,
        verbose=verbose,
        json_output=json_output,
        passthrough=passthrough,
    )
