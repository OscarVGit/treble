"""Argument forwarding — deterministic prefix matching for extra flags.

This is the one place Treble resolves a request *without* Von, and it is
argument forwarding, not procedure selection. It only arms when the leading
tokens exactly reproduce an identifier the registry already defines (a name,
alias, or the procedure's full registered command), and the remainder is a
non-empty list of extra arguments the user explicitly appended.

Ownership is positional: the first leftover token must be flag-like for the
run to arm at all, after which every remaining token is forwarded verbatim
(the shell has already split values, so Treble never parses flag/value
pairs itself). A non-flag-leading remainder (e.g. ``without verification``)
does not arm — the request falls through to Von unchanged.

Example::

    treble check-no-verify --watch            # name + extras
    treble pnpm run check --watch             # full command + extras
    treble pnpm run check without verification  # not flag-like -> Von
"""

from __future__ import annotations

from dataclasses import dataclass, field

from treble.registry.models import Procedure


@dataclass(frozen=True)
class ForwardMatch:
    """A deterministic name/command match carrying extra arguments."""

    procedure: Procedure
    extras: list[str] = field(default_factory=list)
    matched_by: str = "name"  # name | alias | command


def _flag_like(token: str) -> bool:
    """True if ``token`` should be forwarded verbatim to the command.

    A token is forwardable if it starts with a dash (short/long flag, flag
    bundles) or contains an ``=`` (``key=value`` env-style). The bare ``-``
    alone (stdin convention) is not.
    """
    return (token.startswith("-") and token != "-") or "=" in token


def match_forward(
    tokens: list[str], procedures: list[Procedure]
) -> ForwardMatch | None:
    """Match ``tokens`` to a registered procedure with extra args, or None.

    Priority: exact name match, then alias match, then full verbatim-command
    prefix match. Returns None on ambiguity, when there are no extras, or
    when the first extra token is not flag-like (fall through to Von).
    """
    if not tokens:
        return None

    first, rest = tokens[0], tokens[1:]
    if not rest:
        return None

    by_name = [p for p in procedures if p.name == first]
    if by_name:
        return _maybe(by_name[0], rest, "name")

    by_alias = [p for p in procedures if first in p.aliases]
    if len(by_alias) == 1:
        return _maybe(by_alias[0], rest, "alias")

    # Full verbatim-command prefix: the longest invocation that exactly
    # prefixes the tokens, with extras left over.
    best: tuple[Procedure, int] | None = None
    for procedure in procedures:
        invocation = procedure.invocation()
        if (
            len(invocation) < len(tokens)
            and tokens[: len(invocation)] == invocation
            and (best is None or len(invocation) > best[1])
        ):
            best = (procedure, len(invocation))
    if best is None:
        return None
    procedure, length = best
    return _maybe(procedure, tokens[length:], "command")


def _maybe(procedure: Procedure, extras: list[str], matched_by: str) -> ForwardMatch | None:
    """Arm only when the first extra is flag-like; else fall through to Von."""
    if not extras or not _flag_like(extras[0]):
        return None
    return ForwardMatch(procedure=procedure, extras=list(extras), matched_by=matched_by)
