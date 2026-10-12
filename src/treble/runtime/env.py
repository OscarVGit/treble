"""Environment construction and secret redaction."""

from __future__ import annotations

import os

SECRET_TOKENS = ("SECRET", "TOKEN", "PASSWORD", "KEY", "CREDENTIAL")


def build_environment(extra: dict[str, str] | None = None) -> dict[str, str]:
    """Environment for the child process: inherit current, apply procedure vars."""
    env = dict(os.environ)
    for key, value in (extra or {}).items():
        if value:  # empty string means "unset"
            env[key] = value
        else:
            env.pop(key, None)
    return env


def redact(env: dict[str, str]) -> dict[str, str]:
    """Return a copy safe to log, with secret-looking values masked."""
    return {
        key: ("***" if any(tok in key.upper() for tok in SECRET_TOKENS) else value)
        for key, value in env.items()
    }
