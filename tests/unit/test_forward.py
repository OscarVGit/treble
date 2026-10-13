"""Unit tests for deterministic argument forwarding (matching/forward.py)."""

from __future__ import annotations

from treble.matching import match_forward
from treble.registry import Procedure


def _procs() -> list[Procedure]:
    return [
        Procedure(name="hello", description="Say hello", executable="echo", args=["hello"]),
        Procedure(
            name="check",
            description="Run project checks",
            executable="pnpm",
            args=["run", "check"],
            aliases=["chk"],
        ),
        Procedure(
            name="check-no-verify",
            description="Run project checks without verification",
            executable="pnpm",
            args=["run", "check", "--no-verify"],
        ),
    ]


def test_name_match_with_flag_extra() -> None:
    match = match_forward(["hello", "--watch"], _procs())
    assert match is not None
    assert match.procedure.name == "hello"
    assert match.extras == ["--watch"]
    assert match.matched_by == "name"


def test_alias_match() -> None:
    match = match_forward(["chk", "--verbose"], _procs())
    assert match is not None
    assert match.procedure.name == "check"
    assert match.matched_by == "alias"


def test_full_command_match() -> None:
    match = match_forward(["pnpm", "run", "check", "--watch"], _procs())
    assert match is not None
    assert match.procedure.name == "check"
    assert match.extras == ["--watch"]
    assert match.matched_by == "command"


def test_multi_extras() -> None:
    match = match_forward(["hello", "-m", "hi there", "--verbose", "k=v"], _procs())
    assert match is not None
    assert match.extras == ["-m", "hi there", "--verbose", "k=v"]


def test_no_forward_without_extras() -> None:
    assert match_forward(["hello"], _procs()) is None


def test_no_forward_when_extra_not_flag_like() -> None:
    """'without verification' is intent, not args — falls through to Von."""
    assert match_forward(["check", "quickly"], _procs()) is None
    assert match_forward(["hello", "world"], _procs()) is None
    # The README's flagship natural-language example must not be hijacked.
    assert (
        match_forward(
            ["pnpm", "run", "check", "without", "verification"], _procs()
        )
        is None
    )


def test_flag_like_edge_cases() -> None:
    # bare "-" alone is not a flag (stdin convention)
    assert match_forward(["hello", "-"], _procs()) is None
    # key=value counts
    match = match_forward(["hello", "MODE=prod"], _procs())
    assert match is not None
    assert match.extras == ["MODE=prod"]


def test_ambiguous_prefix_not_forwarded() -> None:
    # "pnpm run check" prefixes BOTH the `check` and (via alias-free command
    # match) only `check` invocations; but two different procedures cannot
    # share an invocation prefix here, so this is the unambiguous case.
    # Truly ambiguous: an alias shared by two procedures.
    a = Procedure(name="a", description="x", executable="echo", aliases=["dup"])
    b = Procedure(name="b", description="y", executable="echo", aliases=["dup"])
    assert match_forward(["dup", "--watch"], [a, b]) is None


def test_longest_verbatim_match_wins() -> None:
    procs = [
        Procedure(name="check", description="x", executable="pnpm", args=["run", "check"]),
        Procedure(
            name="check-no-verify",
            description="y",
            executable="pnpm",
            args=["run", "check", "--no-verify"],
        ),
    ]
    match = match_forward(
        ["pnpm", "run", "check", "--no-verify", "--watch"], procs
    )
    assert match is not None
    assert match.procedure.name == "check-no-verify"
    assert match.extras == ["--watch"]
