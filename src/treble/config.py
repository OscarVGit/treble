"""Treble configuration loading.

Configuration precedence (highest to lowest):
1. Environment variables (``TREBLE_VON_URL``, ``TREBLE_VARIANT``).
2. ``~/.treble/config.toml`` → ``[decision].base_url``.
3. Built-in default ``http://127.0.0.1:8765/v1/systemone``.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

DEFAULT_VON_BASE_URL: str = "http://127.0.0.1:8765/v1/systemone"
TREBLE_VON_URL_ENV: str = "TREBLE_VON_URL"
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
    von_timeout_s: float = 5.0
    variant: str = DEFAULT_VARIANT_NAME

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

        base_url = os.environ.get(TREBLE_VON_URL_ENV) or str(
            file_cfg.get("base_url", DEFAULT_VON_BASE_URL)
        )
        variant = os.environ.get(TREBLE_VARIANT_ENV) or DEFAULT_VARIANT_NAME
        return cls(von_base_url=base_url, variant=variant)
