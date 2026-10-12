"""Outcome recording for learning.

Layer 7 in the README: after execution, Treble records whether the
procedure completed successfully and whether its postconditions passed.
MVP: a JSONL file alongside the audit log. No automatic re-ranking is
done — this is purely observational groundwork for Milestone 5.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from treble.config import project_treble_dir

LEARNING_FILE = "outcomes.jsonl"


@dataclass
class OutcomeRecord:
    """One recorded execution outcome for learning."""

    ts: float
    procedure: str
    fingerprint: str
    succeeded: bool
    verified: bool


class LearningStore:
    """Append and read outcome records (project-local)."""

    def __init__(self, cwd: Path | None = None) -> None:
        self._path = project_treble_dir(cwd) / LEARNING_FILE

    @property
    def path(self) -> Path:
        return self._path

    def record(self, entry: OutcomeRecord) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(asdict(entry)) + "\n")

    def record_outcome(
        self, procedure: str, fingerprint: str, *, succeeded: bool, verified: bool
    ) -> None:
        self.record(
            OutcomeRecord(
                ts=time.time(),
                procedure=procedure,
                fingerprint=fingerprint,
                succeeded=succeeded,
                verified=verified,
            )
        )

    def read_all(self) -> list[dict[str, Any]]:
        if not self._path.is_file():
            return []
        return [
            json.loads(line)
            for line in self._path.read_text(encoding="utf-8").splitlines()
            if line
        ]
