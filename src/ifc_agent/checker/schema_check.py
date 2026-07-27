"""Check 1.1 — Schema validity check.

Opens IFC file via IfcOpenShell, validates it can be parsed,
and reports the IFC schema version.
"""

import ifcopenshell
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SchemaCheckResult:
    """Result of schema validity check."""
    passed: bool = True
    ifc_version: Optional[str] = None
    file_path: str = ""
    entity_count: int = 0
    errors: list = field(default_factory=list)

    @property
    def summary(self) -> str:
        if self.passed:
            return f"Schema OK — {self.ifc_version}, {self.entity_count} entities"
        return f"Schema FAILED — {len(self.errors)} error(s)"

    def to_dict(self) -> dict:
        return {
            "check": "schema",
            "passed": self.passed,
            "ifc_version": self.ifc_version,
            "file_path": self.file_path,
            "entity_count": self.entity_count,
            "errors": self.errors,
            "summary": self.summary,
        }


def run(file_path: str | Path) -> SchemaCheckResult:
    """Validate IFC file schema. Returns SchemaCheckResult."""
    result = SchemaCheckResult(file_path=str(file_path))

    try:
        model = ifcopenshell.open(str(file_path))
    except Exception as e:
        result.passed = False
        result.errors.append({
            "type": "parse_error",
            "message": str(e),
        })
        return result

    # Extract schema info
    try:
        result.ifc_version = model.schema
    except Exception:
        result.ifc_version = "unknown"

    # Count all entities
    try:
        result.entity_count = len(list(model))
    except Exception as e:
        result.errors.append({
            "type": "entity_count_error",
            "message": str(e),
        })

    # Validate schema is a known version
    known_schemas = {"IFC2X3", "IFC4", "IFC4X3", "IFC4X3_ADD2"}
    if result.ifc_version and result.ifc_version.upper() not in known_schemas:
        result.errors.append({
            "type": "unknown_schema",
            "message": f"Schema '{result.ifc_version}' is not a standard version. "
                       f"Known: {', '.join(sorted(known_schemas))}",
        })

    result.passed = len(result.errors) == 0
    return result
