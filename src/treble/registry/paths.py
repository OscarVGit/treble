"""Resolution of scope directories and procedure file paths.

MVP scopes:
- project:  ``<cwd>/.treble/procedures/<name>.yaml``
- personal: ``~/.treble/procedures/<name>.yaml``

Lookup order (project wins over personal): ``[project, personal]``.
"""

from __future__ import annotations

from pathlib import Path

from treble.config import project_treble_dir, user_config_dir
from treble.registry.models import Scope

PROCEDURES_SUBDIR = "procedures"
AUDIT_LOG_NAME = "audit.jsonl"


def scope_procedures_dir(scope: Scope, cwd: Path | None = None) -> Path:
    """Directory holding procedure YAML files for the given scope."""
    if scope is Scope.PROJECT:
        return project_treble_dir(cwd) / PROCEDURES_SUBDIR
    return user_config_dir() / PROCEDURES_SUBDIR


def lookup_order(cwd: Path | None = None) -> list[Scope]:
    """Scope search order; earlier scopes shadow later ones."""
    return [Scope.PROJECT, Scope.PERSONAL]


def procedure_file(scope: Scope, name: str, cwd: Path | None = None) -> Path:
    """Filesystem path of a single procedure file."""
    return scope_procedures_dir(scope, cwd) / f"{name}.yaml"


def audit_log_path(cwd: Path | None = None) -> Path:
    """Project-local audit log (created on first write)."""
    return project_treble_dir(cwd) / AUDIT_LOG_NAME
