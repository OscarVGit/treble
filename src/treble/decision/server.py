"""``treble decision serve`` — launch the local Von HTTP server.

Thin wrapper around ``von serve``. It exists so Treble users do not need to
remember Von's CLI flags or the checkpoint environment variable. The model
weights are resolved from ``VON_CHECKPOINT_DIR`` (recommended for a local
checkpoint) before falling back to Von's own defaults.
"""

from __future__ import annotations

import os
import shutil
import subprocess


def serve(
    host: str = "127.0.0.1",
    port: int = 8765,
    checkpoint_dir: str | None = None,
    extra_args: list[str] | None = None,
) -> int:
    """Run ``von serve`` in the foreground; returns its exit code.

    ``checkpoint_dir`` (or the ``VON_CHECKPOINT_DIR`` env var) points at a
    local checkpoint containing ``option_marker.pt``. If neither is set,
    Von's own defaults apply.
    """
    binary = shutil.which("von")
    if binary is None:
        msg = "von CLI not found on PATH; install the 'von-sdk' package"
        raise RuntimeError(msg)
    env = dict(os.environ)
    if checkpoint_dir:
        env["VON_CHECKPOINT_DIR"] = checkpoint_dir
    cmd = [binary, "serve", "--host", host, "--port", str(port)]
    if extra_args:
        cmd.extend(extra_args)
    return subprocess.call(cmd, env=env)
