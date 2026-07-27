"""Check 1.4 + 1.6 — GlobalId uniqueness check.

Detects duplicate GlobalIds within a single file and
across multiple federated IFC files.
"""

import ifcopenshell
from pathlib import Path
from collections import Counter
from dataclasses import dataclass, field


@dataclass
class GuidCheckResult:
    """Result of GUID uniqueness check."""
    passed: bool = True
    total_guids: int = 0
    unique_guids: int = 0
    duplicate_count: int = 0
    duplicates: list = field(default_factory=list)
    cross_file_collisions: list = field(default_factory=list)
    errors: list = field(default_factory=list)

    @property
    def summary(self) -> str:
        issues = []
        if self.duplicate_count > 0:
            issues.append(f"{self.duplicate_count} duplicate GUID(s)")
        if self.cross_file_collisions:
            issues.append(f"{len(self.cross_file_collisions)} cross-file collision(s)")
        if not issues:
            return f"GUID OK — {self.total_guids} unique GUIDs"
        return f"GUID ISSUES — {', '.join(issues)}"

    def to_dict(self) -> dict:
        return {
            "check": "guid",
            "passed": self.passed,
            "total_guids": self.total_guids,
            "unique_guids": self.unique_guids,
            "duplicate_count": self.duplicate_count,
            "duplicates": self.duplicates[:50],
            "cross_file_collisions": self.cross_file_collisions[:50],
            "errors": self.errors,
            "summary": self.summary,
        }


def _collect_guids(model: ifcopenshell.file) -> list[tuple[str, str, str]]:
    """Collect (GlobalId, Name, IFC class) tuples from all IfcRoot entities."""
    guids = []
    for entity in model.by_type("IfcRoot"):
        guids.append((
            entity.GlobalId,
            getattr(entity, "Name", None) or "unnamed",
            entity.is_a(),
        ))
    return guids


def run(
    file_path: str | Path,
    model: ifcopenshell.file = None,
    additional_files: list[str | Path] = None,
) -> GuidCheckResult:
    """Check GlobalId uniqueness within and across IFC files.

    Args:
        file_path: Path to the primary IFC file.
        model: Pre-loaded ifcopenshell model (optional).
        additional_files: Extra IFC file paths for cross-file collision check.
    """
    result = GuidCheckResult()

    if model is None:
        try:
            model = ifcopenshell.open(str(file_path))
        except Exception as e:
            result.passed = False
            result.errors.append({"type": "ifc_parse_error", "message": str(e)})
            return result

    # --- Single file duplicate check ---
    guids = _collect_guids(model)
    result.total_guids = len(guids)

    guid_counter = Counter(g[0] for g in guids)
    result.unique_guids = len(guid_counter)

    for guid, count in guid_counter.items():
        if count > 1:
            result.duplicate_count += 1
            # Find all entities with this GUID
            entities = [g for g in guids if g[0] == guid]
            result.duplicates.append({
                "guid": guid,
                "count": count,
                "entities": [
                    {"name": e[1], "ifc_class": e[2]} for e in entities
                ],
            })

    # --- Cross-file collision check ---
    if additional_files:
        primary_guid_set = set(g[0] for g in guids)

        for other_path in additional_files:
            try:
                other_model = ifcopenshell.open(str(other_path))
                other_guids = _collect_guids(other_model)
                other_guid_set = set(g[0] for g in other_guids)

                collisions = primary_guid_set & other_guid_set
                for collision_guid in collisions:
                    result.cross_file_collisions.append({
                        "guid": collision_guid,
                        "file_a": str(file_path),
                        "file_b": str(other_path),
                    })
            except Exception as e:
                result.errors.append({
                    "type": "cross_file_error",
                    "file": str(other_path),
                    "message": str(e),
                })

    result.passed = (
        result.duplicate_count == 0
        and len(result.cross_file_collisions) == 0
    )
    return result
