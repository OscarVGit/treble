"""Precondition utility tests.

These helpers are retained as runtime utilities (declared procedure
metadata); they are not used to filter Von's option set.
"""

from __future__ import annotations

from pathlib import Path

from treble.matching import environment_satisfies, filter_by_environment
from treble.registry.models import Precondition, Procedure


def _proc(name: str) -> Procedure:
    return Procedure(name=name, description=f"{name} desc", executable="echo", args=[name])


def test_environment_satisfies_missing_executable(tmp_path: Path) -> None:
    keep = _proc("keep")
    drop = _proc("drop").model_copy(
        update={"preconditions": Precondition(executable="definitely-not-a-real-binary")}
    )
    assert filter_by_environment([keep, drop], tmp_path) == [keep]
    assert not environment_satisfies(drop.preconditions, tmp_path)


def test_environment_satisfies_env_vars(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("TREBLE_TEST_REQUIRED", raising=False)
    proc = _proc("needs-env").model_copy(
        update={"preconditions": Precondition(env_vars_present=["TREBLE_TEST_REQUIRED"])}
    )
    assert filter_by_environment([proc], tmp_path) == []
    monkeypatch.setenv("TREBLE_TEST_REQUIRED", "1")
    assert filter_by_environment([proc], tmp_path) == [proc]
