"""Pydantic models for Treble procedures."""

from __future__ import annotations

import hashlib
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class RiskLevel(StrEnum):
    """Side-effect classification of a procedure."""

    READ_ONLY = "read-only"
    MUTATING = "mutating"
    DESTRUCTIVE = "destructive"


class Scope(StrEnum):
    """Where a procedure is stored."""

    PERSONAL = "personal"
    PROJECT = "project"


class Precondition(BaseModel):
    """Requirements that must hold before a procedure is eligible."""

    executable: str | None = None
    min_python_version: str | None = None
    cwd_contains: str | None = None
    env_vars_present: list[str] = Field(default_factory=list)


class Verifier(BaseModel):
    """Post-execution verification declaration."""

    expected_exit_code: int = 0
    stdout_contains: str | None = None
    stderr_empty: bool = False
    artifact_exists: str | None = None


class Provenance(BaseModel):
    """Authorship and version information for a procedure."""

    author: str | None = None
    source: str = "manual"
    version: int = 1
    approved: bool = True


class Procedure(BaseModel):
    """A registered, inspectable command procedure."""

    name: str
    description: str
    executable: str
    args: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)
    risk: RiskLevel = RiskLevel.READ_ONLY
    scope: Scope = Scope.PROJECT
    enabled: bool = True
    working_dir: str | None = None
    env_vars: dict[str, str] = Field(default_factory=dict)
    preconditions: Precondition = Field(default_factory=Precondition)
    verify: Verifier = Field(default_factory=Verifier)
    provenance: Provenance = Field(default_factory=Provenance)

    @field_validator("name")
    @classmethod
    def _valid_name(cls, value: str) -> str:
        if not value or any(ch.isspace() for ch in value):
            msg = "procedure name must be non-empty and contain no whitespace"
            raise ValueError(msg)
        if value.startswith("-"):
            msg = (
                "procedure name must not start with '-': it would collide with "
                "the positional flag-ownership rule (leading flags are Treble's)"
            )
            raise ValueError(msg)
        return value

    @field_validator("aliases")
    @classmethod
    def _valid_aliases(cls, value: list[str]) -> list[str]:
        for alias in value:
            if alias.startswith("-"):
                msg = (
                    f"alias {alias!r} must not start with '-': it would collide "
                    "with the positional flag-ownership rule"
                )
                raise ValueError(msg)
        return value

    @field_validator("env_vars")
    @classmethod
    def _no_secret_env(cls, value: dict[str, str]) -> dict[str, str]:
        for key, val in value.items():
            secret_like = any(
                tok in key.upper() for tok in ("SECRET", "TOKEN", "PASSWORD", "KEY")
            )
            if secret_like and val:
                msg = f"env var {key!r} looks secret-like; do not store values"
                raise ValueError(msg)
        return value

    def invocation(self) -> list[str]:
        """The exact executable + argument vector to run."""
        return [self.executable, *self.args]

    def fingerprint(self) -> str:
        """Stable content hash used for change detection and invalidation."""
        digest = hashlib.sha256(self.model_dump_json().encode("utf-8")).hexdigest()
        return digest[:16]

    def as_option_description(self) -> str:
        """Compact single-line description used as a Von option."""
        return f"{self.name}: {self.description}"


def procedure_to_yaml_dict(procedure: Procedure) -> dict[str, Any]:
    """Serialize for YAML storage (omits defaults to keep files readable).

    Uses ``mode="json"`` so ``StrEnum`` fields (``risk``, ``scope``) become
    plain strings — ``mode="python"`` leaves enum objects that PyYAML's safe
    dumper cannot represent.
    """
    return procedure.model_dump(mode="json", exclude_defaults=True)
