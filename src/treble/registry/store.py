"""YAML-backed procedure registry.

One procedure per file: ``<scope>/procedures/<name>.yaml``.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from treble.registry import paths
from treble.registry.exceptions import DuplicateProcedure, InvalidProcedure, ProcedureNotFound
from treble.registry.models import Procedure, Scope, procedure_to_yaml_dict
from treble.registry.schema import validate_procedure_data


class ProcedureStore:
    """Read/write access to the on-disk procedure registry."""

    def __init__(self, cwd: Path | None = None) -> None:
        self._cwd = cwd

    # -- writing -----------------------------------------------------------

    def add(self, procedure: Procedure, *, overwrite: bool = False) -> Path:
        """Persist a procedure to its scope directory."""
        directory = paths.scope_procedures_dir(procedure.scope, self._cwd)
        directory.mkdir(parents=True, exist_ok=True)
        target = paths.procedure_file(procedure.scope, procedure.name, self._cwd)
        if target.exists() and not overwrite:
            msg = f"procedure {procedure.name!r} already exists in scope {procedure.scope}"
            raise DuplicateProcedure(msg)
        data = procedure_to_yaml_dict(procedure)
        validate_procedure_data(data)
        target.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        return target

    def remove(self, name: str, scope: Scope | None = None) -> Path:
        """Delete a procedure; returns the path that was removed."""
        procedure, found_scope = self._locate(name, scope)
        path = paths.procedure_file(found_scope, procedure.name, self._cwd)
        path.unlink()
        return path

    # -- reading -----------------------------------------------------------

    def get(self, name: str) -> Procedure:
        """Fetch a single procedure by name (project scope shadows personal)."""
        procedure, _scope = self._locate(name, None)
        return procedure

    def list_all(self) -> list[Procedure]:
        """All procedures visible from the current context, deduplicated."""
        seen: set[str] = set()
        result: list[Procedure] = []
        for scope in paths.lookup_order(self._cwd):
            for procedure in self._iter_scope(scope):
                if procedure.name not in seen:
                    seen.add(procedure.name)
                    result.append(procedure)
        return result

    # -- internals ---------------------------------------------------------

    def _locate(self, name: str, scope: Scope | None) -> tuple[Procedure, Scope]:
        scopes = [scope] if scope else paths.lookup_order(self._cwd)
        for candidate_scope in scopes:
            path = paths.procedure_file(candidate_scope, name, self._cwd)
            if path.is_file():
                return self._load(path), candidate_scope
        # Fall back to alias lookup.
        for candidate_scope in scopes:
            for procedure in self._iter_scope(candidate_scope):
                if name in procedure.aliases:
                    return procedure, candidate_scope
        msg = f"no procedure named {name!r}"
        raise ProcedureNotFound(msg)

    def _iter_scope(self, scope: Scope) -> list[Procedure]:
        directory = paths.scope_procedures_dir(scope, self._cwd)
        if not directory.is_dir():
            return []
        return [self._load(p) for p in sorted(directory.glob("*.yaml"))]

    @staticmethod
    def _load(path: Path) -> Procedure:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            msg = f"procedure file {path} is not a YAML mapping"
            raise InvalidProcedure(msg)
        try:
            return Procedure.model_validate(raw)
        except Exception as exc:  # pydantic.ValidationError, ValueError
            msg = f"procedure file {path} is invalid: {exc}"
            raise InvalidProcedure(msg) from exc
