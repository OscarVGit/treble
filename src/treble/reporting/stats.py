"""Summarize Treble usage from the local audit and events logs.

Read-only. Aggregates ``.treble/events.jsonl`` (every routed request) and
``.treble/audit.jsonl`` (every executed procedure) into a small usage report:
how many requests, by source; the routing distribution; execution success and
latency; hot procedures; and registered-but-unused procedures. Intended for the
solo dogfood described in the AGENTS/pilot notes — run it after a couple of
weeks and read the signal.
"""

from __future__ import annotations

import datetime
import json
import statistics
from collections import Counter
from pathlib import Path
from typing import Any

from treble.registry import ProcedureStore
from treble.runtime import read_audit, read_events

_EXIT_LABELS = {
    0: "ok",
    2: "no-match",
    3: "needs-decision",
    4: "denied",
    5: "failed",
    6: "von-unavailable",
    7: "clarify",
}


def collect_stats(cwd: Path | None = None) -> dict[str, Any]:
    """Aggregate the logs into a JSON-serializable summary."""
    events = read_events(cwd)
    audit = read_audit(cwd)

    stamps = [e.get("ts", 0.0) for e in events] + [a.get("ts", 0.0) for a in audit]
    window = [min(stamps), max(stamps)] if stamps else [None, None]

    sources = Counter(e.get("source", "?") for e in events)
    actions = Counter(e.get("action", "?") for e in events)
    outcomes = Counter(
        _EXIT_LABELS.get(e.get("exit_code", 0), str(e.get("exit_code"))) for e in events
    )
    hot = Counter(a.get("procedure", "?") for a in audit)
    durations = [a.get("duration_s", 0.0) for a in audit]
    verified = sum(1 for a in audit if a.get("verified"))

    registered = [p.name for p in ProcedureStore(cwd).list_all()]
    unused = [name for name in registered if name not in hot]

    return {
        "window": {"start": window[0], "end": window[1]},
        "requests": len(events),
        "executions": len(audit),
        "by_source": dict(sources.most_common()),
        "by_action": dict(actions.most_common()),
        "by_outcome": dict(outcomes.most_common()),
        "first_try_success": (verified / len(audit)) if audit else None,
        "median_latency_s": statistics.median(durations) if durations else None,
        "hot_procedures": hot.most_common(),
        "registered": len(registered),
        "unused": unused,
    }


def render_stats(cwd: Path | None = None) -> str:
    """Human-readable multi-line summary."""
    s = collect_stats(cwd)
    if s["requests"] == 0 and s["executions"] == 0:
        return (
            "no Treble activity recorded yet "
            "(.treble/events.jsonl, .treble/audit.jsonl)"
        )

    lines: list[str] = []
    start, end = s["window"]["start"], s["window"]["end"]
    if start and end:
        lines.append(f"window        {_fmt_ts(start)} → {_fmt_ts(end)}")

    src = " · ".join(f"{k} {v}" for k, v in s["by_source"].items())
    lines.append(f"requests      {s['requests']}" + (f"   ({src})" if src else ""))

    succ = s["first_try_success"]
    succ_s = f"{succ * 100:.0f}%" if succ is not None else "n/a"
    lat = s["median_latency_s"]
    lat_s = f"{lat:.2f}s" if lat is not None else "n/a"
    lines.append(
        f"executions    {s['executions']}   first-try success {succ_s}   "
        f"median latency {lat_s}"
    )

    if s["by_action"]:
        lines.append("actions       " + " · ".join(f"{k} {v}" for k, v in s["by_action"].items()))
    if s["by_outcome"]:
        lines.append("outcomes      " + " · ".join(f"{k} {v}" for k, v in s["by_outcome"].items()))
    if s["hot_procedures"]:
        hot = "  ".join(f"{name} {n}" for name, n in s["hot_procedures"][:8])
        lines.append(f"hot           {hot}")
    if s["unused"]:
        lines.append(f"unused        {', '.join(s['unused'])}  (registered, never run)")
    return "\n".join(lines)


def stats_json(cwd: Path | None = None) -> str:
    return json.dumps(collect_stats(cwd), indent=2, sort_keys=True)


def _fmt_ts(ts: float) -> str:
    return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
