"""JSON Schema loader and validator for procedure files.

The schema lives in ``schemas/procedure.schema.json`` at the repository
root. During development we locate it by walking up from this module until
we find it; this keeps the source tree self-contained without packaging
the schema inside the wheel.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import jsonschema

from treble.registry.exceptions import InvalidProcedure

SCHEMA_FILENAME = "procedure.schema.json"


def _find_schema_file(start: Path | None = None) -> Path:
    here = (start or Path(__file__)).resolve()
    for directory in (here, *here.parents):
        candidate = directory / "schemas" / SCHEMA_FILENAME
        if candidate.is_file():
            return candidate
    msg = f"could not locate schemas/{SCHEMA_FILENAME} from {here}"
    raise FileNotFoundError(msg)


@lru_cache(maxsize=1)
def load_schema() -> dict[str, Any]:
    """Return the parsed JSON Schema for procedures."""
    return json.loads(_find_schema_file().read_text(encoding="utf-8"))


def validate_procedure_data(data: dict[str, Any]) -> None:
    """Validate raw procedure data against the schema; raise InvalidProcedure."""
    try:
        jsonschema.validate(instance=data, schema=load_schema())
    except jsonschema.ValidationError as exc:
        msg = f"procedure failed schema validation: {exc.message}"
        raise InvalidProcedure(msg) from exc
