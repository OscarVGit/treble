"""Transport-agnostic operations for the MCP server (and tests).

They call the *same* pipeline functions the CLI uses, under a captured I/O
context (``PipelineIO``), so an agent and a human exercise an identical
pathway, options and safety gates. A mutating/destructive action with no
``yes`` returns ``confirmation_required`` instead of blocking on a TTY — the
agent is expected to ask the human, then re-call with ``yes=True`` (the exact
equivalent of a human typing ``--yes``).

This module deliberately does not import the MCP SDK, so it is usable and
testable without the optional ``mcp`` extra.
"""

from __future__ import annotations

import shlex
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from treble.cli.commands import _pipeline
from treble.cli.commands._pipeline import (
    EXIT_CLARIFY,
    EXIT_DENIED,
    EXIT_FAILED,
    EXIT_NEEDS_DECISION,
    EXIT_NO_MATCH,
    EXIT_OK,
    EXIT_VON_UNAVAILABLE,
    ConfirmationRequired,
    PipelineIO,
)
from treble.reporting import collect_stats

_STATUS_BY_EXIT = {
    EXIT_OK: "ok",
    EXIT_NO_MATCH: "no_match",
    EXIT_NEEDS_DECISION: "needs_decision",
    EXIT_DENIED: "denied",
    EXIT_FAILED: "failed",
    EXIT_VON_UNAVAILABLE: "von_unavailable",
    EXIT_CLARIFY: "clarify",
}


@dataclass
class ToolResult:
    """Structured result returned to the agent."""

    status: str
    exit_code: int = EXIT_OK
    stdout: str = ""
    stderr: str = ""
    prompt: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _invoke(fn, *args, **kwargs) -> ToolResult:
    """Run a shared op under a capturing, non-interactive I/O adapter."""
    out: list[str] = []
    err: list[str] = []

    def confirm(prompt: str) -> bool:
        raise ConfirmationRequired(prompt)

    token = _pipeline.IO.set(PipelineIO(out=out.append, err=err.append, confirm=confirm))
    try:
        code = fn(*args, **kwargs)
    except ConfirmationRequired as exc:
        return ToolResult(status="confirmation_required", prompt=exc.prompt)
    finally:
        _pipeline.IO.reset(token)

    return ToolResult(
        status=_STATUS_BY_EXIT.get(code, "error"),
        exit_code=code,
        stdout="".join(out),
        stderr="".join(err),
    )


def list_procedures(*, cwd: Path | None = None) -> dict[str, Any]:
    return _invoke(_pipeline.list_procedures, cwd=cwd).as_dict()


def show_procedure(name: str, *, cwd: Path | None = None) -> dict[str, Any]:
    return _invoke(_pipeline.show_procedure, name, cwd=cwd).as_dict()


def explain_procedure(name: str, *, cwd: Path | None = None) -> dict[str, Any]:
    return _invoke(_pipeline.explain_procedure, name, cwd=cwd).as_dict()


def run_intent(
    intent: str | list[str],
    *,
    dry_run: bool = False,
    yes: bool = False,
    cwd: Path | None = None,
    client: object | None = None,
) -> dict[str, Any]:
    tokens = shlex.split(intent) if isinstance(intent, str) else list(intent)
    return _invoke(
        _pipeline.run_intent,
        tokens,
        dry_run=dry_run,
        assume_yes=yes,
        cwd=cwd,
        client=client,
    ).as_dict()


def run_named(
    name: str,
    *,
    dry_run: bool = False,
    yes: bool = False,
    cwd: Path | None = None,
) -> dict[str, Any]:
    return _invoke(
        _pipeline.run_named, name, dry_run=dry_run, assume_yes=yes, cwd=cwd
    ).as_dict()


def remove_procedure(
    name: str,
    *,
    dry_run: bool = False,
    yes: bool = False,
    cwd: Path | None = None,
) -> dict[str, Any]:
    return _invoke(
        _pipeline.remove_named, name, dry_run=dry_run, assume_yes=yes, cwd=cwd
    ).as_dict()


def stats(*, cwd: Path | None = None) -> dict[str, Any]:
    return collect_stats(cwd)
