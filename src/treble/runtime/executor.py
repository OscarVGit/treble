"""Deterministic subprocess execution.

The runtime preserves the registered executable and argument list exactly.
No shell interpolation is used anywhere in this module.
"""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from treble.registry.models import Procedure
from treble.runtime.env import build_environment
from treble.runtime.timeout import DEFAULT_TIMEOUT_S


@dataclass
class ExecutionResult:
    """Captured outcome of one invocation."""

    procedure: str
    argv: list[str]
    cwd: str
    exit_code: int
    stdout: str
    stderr: str
    duration_s: float
    timed_out: bool = False
    error: str | None = None
    extra_env: dict[str, str] = field(default_factory=dict)

    @property
    def succeeded(self) -> bool:
        return self.exit_code == 0 and not self.timed_out and self.error is None


def execute(
    procedure: Procedure,
    cwd: Path | None = None,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    extra_args: list[str] | None = None,
) -> ExecutionResult:
    """Run a procedure and capture its result.

    The procedure's ``args`` are passed as-is, followed by any ``extra_args``
    the user appended at call time. Nothing goes through a shell; working
    directory and environment are applied deterministically.
    """
    argv = [*procedure.invocation(), *(extra_args or [])]
    working_dir = Path(procedure.working_dir) if procedure.working_dir else (cwd or Path.cwd())
    extra_env = dict(procedure.env_vars)
    env = build_environment(extra_env)

    start = time.monotonic()
    try:
        completed = subprocess.run(
            argv,
            cwd=working_dir,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
        return ExecutionResult(
            procedure=procedure.name,
            argv=argv,
            cwd=str(working_dir),
            exit_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            duration_s=time.monotonic() - start,
            extra_env=extra_env,
        )
    except subprocess.TimeoutExpired as exc:
        return ExecutionResult(
            procedure=procedure.name,
            argv=argv,
            cwd=str(working_dir),
            exit_code=124,
            stdout=(exc.stdout or "") if isinstance(exc.stdout, str) else "",
            stderr=(exc.stderr or "") if isinstance(exc.stderr, str) else "",
            duration_s=time.monotonic() - start,
            timed_out=True,
            extra_env=extra_env,
        )
    except (FileNotFoundError, PermissionError, OSError) as exc:
        return ExecutionResult(
            procedure=procedure.name,
            argv=argv,
            cwd=str(working_dir),
            exit_code=127,
            stdout="",
            stderr="",
            duration_s=time.monotonic() - start,
            error=str(exc),
            extra_env=extra_env,
        )
