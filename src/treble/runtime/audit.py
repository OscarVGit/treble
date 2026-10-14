"""Append-only JSONL audit trail for every Treble invocation."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from treble.registry import paths
from treble.runtime.env import redact
from treble.runtime.executor import ExecutionResult


@dataclass
class AuditRecord:
    """One entry in the audit log (an executed procedure)."""

    ts: float
    procedure: str
    argv: list[str]
    cwd: str
    exit_code: int
    duration_s: float
    verified: bool
    source: str = "unknown"  # routed | forwarding | literal
    decision_reason: str | None = None
    decision_confidence: float | None = None
    extra_env_redacted: dict[str, str] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True)

    @classmethod
    def from_execution(
        cls,
        result: ExecutionResult,
        *,
        verified: bool,
        source: str = "unknown",
        decision_reason: str | None = None,
        decision_confidence: float | None = None,
    ) -> AuditRecord:
        return cls(
            ts=time.time(),
            procedure=result.procedure,
            argv=list(result.argv),
            cwd=result.cwd,
            exit_code=result.exit_code,
            duration_s=result.duration_s,
            verified=verified,
            source=source,
            decision_reason=decision_reason,
            decision_confidence=decision_confidence,
            extra_env_redacted=redact(result.extra_env),
        )


@dataclass
class EventRecord:
    """One routing event: every request Treble handles, executed or not."""

    ts: float
    source: str  # routed | forwarding | literal
    action: str  # action value (select/remove/show/explain/list/add/clarify/escalate)
    target: str | None
    confidence: float | None
    reason: str | None
    exit_code: int

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True)


def append_audit(record: AuditRecord, cwd: Path | None = None) -> Path:
    """Append one JSON line to the project-local (or user) audit log."""
    target = paths.audit_log_path(cwd)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as fh:
        fh.write(record.to_json() + "\n")
    return target


def append_event(record: EventRecord, cwd: Path | None = None) -> Path:
    """Append one routing event to the project-local events log."""
    target = paths.events_log_path(cwd)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as fh:
        fh.write(record.to_json() + "\n")
    return target


def read_audit(cwd: Path | None = None) -> list[dict[str, Any]]:
    """Read every audit record as a dict."""
    return _read_jsonl(paths.audit_log_path(cwd))


def read_events(cwd: Path | None = None) -> list[dict[str, Any]]:
    """Read every routing event as a dict."""
    return _read_jsonl(paths.events_log_path(cwd))


def _read_jsonl(target: Path) -> list[dict[str, Any]]:
    if not target.is_file():
        return []
    return [
        json.loads(line)
        for line in target.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
