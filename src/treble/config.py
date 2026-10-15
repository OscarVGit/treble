"""Treble configuration loading.

Configuration precedence (highest to lowest):
1. Environment variables (``TREBLE_DECISION_URL``/``TREBLE_VON_URL``,
   ``TYPESAFE_API_KEY``/``TYPESAFE_API``/``TREBLE_API_KEY``, ``TREBLE_MODEL``,
   ``TREBLE_VARIANT``).
2. ``~/.treble/config.toml`` → ``[decision]`` (``base_url``, ``api_key``,
   ``model``).
3. Built-in defaults.

The decision backend is any service that speaks the ``/v1/systemone`` wire
protocol — the local Von server, or TypeSafe Jev behind an API key. Point
``TREBLE_DECISION_URL`` at it and set ``TYPESAFE_API``; nothing else changes.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

DEFAULT_VON_BASE_URL: str = "http://127.0.0.1:8765/v1/systemone"
DEFAULT_MODEL_NAME: str = "von-latest"
DEFAULT_TIMEOUT_S: float = 5.0
TREBLE_DECISION_URL_ENV: str = "TREBLE_DECISION_URL"
TREBLE_VON_URL_ENV: str = "TREBLE_VON_URL"  # legacy alias
TYPESAFE_API_KEY_ENV: str = "TYPESAFE_API_KEY"
TYPESAFE_API_ENV: str = "TYPESAFE_API"  # legacy alias
TREBLE_API_KEY_ENV: str = "TREBLE_API_KEY"
TREBLE_MODEL_ENV: str = "TREBLE_MODEL"
TREBLE_TIMEOUT_ENV: str = "TREBLE_TIMEOUT_S"
TREBLE_VARIANT_ENV: str = "TREBLE_VARIANT"
DEFAULT_VARIANT_NAME: str = "default"


def user_config_dir() -> Path:
    """User-level Treble directory (config, personal procedures, audit log)."""
    return Path.home() / ".treble"


def project_treble_dir(cwd: Path | None = None) -> Path:
    """Project-local Treble directory under the current working directory."""
    return (cwd or Path.cwd()) / ".treble"


@dataclass(frozen=True)
class TrebleConfig:
    """Resolved Treble configuration."""

    von_base_url: str = DEFAULT_VON_BASE_URL
    von_timeout_s: float = DEFAULT_TIMEOUT_S
    variant: str = DEFAULT_VARIANT_NAME
    model: str = DEFAULT_MODEL_NAME
    api_key: str | None = None

    @classmethod
    def load(cls, cwd: Path | None = None) -> TrebleConfig:
        """Load configuration from file, with environment-variable override."""
        cfg_path = user_config_dir() / "config.toml"
        file_cfg: dict[str, object] = {}
        if cfg_path.is_file():
            data = tomllib.loads(cfg_path.read_text(encoding="utf-8"))
            decision = data.get("decision")
            if isinstance(decision, dict):
                file_cfg = decision

        base_url = (
            os.environ.get(TREBLE_DECISION_URL_ENV)
            or os.environ.get(TREBLE_VON_URL_ENV)
            or str(file_cfg.get("base_url", DEFAULT_VON_BASE_URL))
        )
        api_key = (
            os.environ.get(TYPESAFE_API_KEY_ENV)
            or os.environ.get(TYPESAFE_API_ENV)
            or os.environ.get(TREBLE_API_KEY_ENV)
            or (str(file_cfg["api_key"]) if file_cfg.get("api_key") else None)
        )
        model = os.environ.get(TREBLE_MODEL_ENV) or str(
            file_cfg.get("model", DEFAULT_MODEL_NAME)
        )
        timeout_raw = os.environ.get(TREBLE_TIMEOUT_ENV) or file_cfg.get(
            "timeout_s", DEFAULT_TIMEOUT_S
        )
        timeout = float(timeout_raw)
        variant = os.environ.get(TREBLE_VARIANT_ENV) or DEFAULT_VARIANT_NAME
        return cls(
            von_base_url=base_url,
            von_timeout_s=timeout,
            variant=variant,
            model=model,
            api_key=api_key,
        )
