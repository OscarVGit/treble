"""Tests for usage logging (audit/events) and the `treble stats` report."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from treble.registry import Procedure, ProcedureStore
from treble.reporting import collect_stats, render_stats, stats_json
from treble.runtime import AuditRecord, EventRecord, append_audit, append_event, read_events


def test_event_round_trip(project_cwd: Path) -> None:
    append_event(
        EventRecord(
            ts=1.0,
            source="routed",
            action="select",
            target="build",
            confidence=0.9,
            reason="model selected a procedure to run",
            exit_code=0,
        ),
        cwd=project_cwd,
    )
    events = read_events(project_cwd)
    assert len(events) == 1
    assert events[0]["action"] == "select"
    assert events[0]["source"] == "routed"


def test_audit_record_carries_source_and_decision() -> None:
    from treble.runtime.executor import ExecutionResult

    result = ExecutionResult(
        procedure="build",
        argv=["echo", "hi"],
        cwd="/tmp",
        exit_code=0,
        duration_s=0.1,
        stdout="hi\n",
        stderr="",
        extra_env={},
    )
    record = AuditRecord.from_execution(
        result, verified=True, source="routed",
        decision_reason="model selected a procedure to run", decision_confidence=0.83,
    )
    data = json.loads(record.to_json())
    assert data["source"] == "routed"
    assert data["decision_reason"].startswith("model selected")
    assert data["decision_confidence"] == 0.83


def test_collect_stats_aggregates(project_cwd: Path) -> None:
    store = ProcedureStore(project_cwd)
    store.add(Procedure(name="build", description="b", executable="echo"))
    store.add(Procedure(name="dead", description="d", executable="echo"))

    append_event(
        EventRecord(ts=10, source="routed", action="select", target="build",
                    confidence=0.9, reason="r", exit_code=0), cwd=project_cwd,
    )
    append_event(
        EventRecord(ts=11, source="routed", action="clarify", target=None,
                    confidence=0.2, reason="ambiguous", exit_code=7), cwd=project_cwd,
    )
    for ts, ok in ((10, True), (12, True), (13, False)):
        append_audit(
            AuditRecord(ts=ts, procedure="build", argv=["echo"], cwd=str(project_cwd),
                        exit_code=0 if ok else 1, duration_s=1.0, verified=ok,
                        source="routed"), cwd=project_cwd,
        )

    s = collect_stats(project_cwd)
    assert s["requests"] == 2
    assert s["executions"] == 3
    assert s["by_action"]["select"] == 1 and s["by_action"]["clarify"] == 1
    assert s["by_source"]["routed"] == 2
    assert s["hot_procedures"][0] == ("build", 3)
    assert "dead" in s["unused"]
    assert s["first_try_success"] == pytest.approx(2 / 3)


def test_render_stats_empty(project_cwd: Path) -> None:
    assert "no Treble activity" in render_stats(project_cwd)


def test_render_stats_text(project_cwd: Path) -> None:
    append_audit(
        AuditRecord(ts=10, procedure="build", argv=["echo"], cwd=".", exit_code=0,
                    duration_s=0.5, verified=True, source="literal"),
        cwd=project_cwd,
    )
    text = render_stats(project_cwd)
    assert "executions" in text
    assert "build" in text


def test_stats_json_is_valid_json(project_cwd: Path) -> None:
    append_audit(
        AuditRecord(ts=10, procedure="build", argv=["echo"], cwd=".", exit_code=0,
                    duration_s=0.5, verified=True),
        cwd=project_cwd,
    )
    data = json.loads(stats_json(project_cwd))
    assert data["executions"] == 1
    assert "by_action" in data
