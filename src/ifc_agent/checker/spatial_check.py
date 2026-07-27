"""Check 1.3 — Spatial containment check.

Every IfcElement must be contained in an IfcSpace or at least an IfcStorey.
Flag orphan elements that have no spatial container.
"""

import ifcopenshell
import ifcopenshell.util.element
from pathlib import Path
from dataclasses import dataclass, field


@dataclass
class SpatialCheckResult:
    """Result of spatial containment check."""
    passed: bool = True
    total_elements: int = 0
    contained_elements: int = 0
    orphan_count: int = 0
    orphans: list = field(default_factory=list)
    errors: list = field(default_factory=list)

    @property
    def summary(self) -> str:
        if self.passed:
            return f"Spatial OK — all {self.total_elements} elements contained"
        return (
            f"Spatial ISSUES — {self.orphan_count} orphan element(s) "
            f"out of {self.total_elements}"
        )

    def to_dict(self) -> dict:
        return {
            "check": "spatial",
            "passed": self.passed,
            "total_elements": self.total_elements,
            "contained_elements": self.contained_elements,
            "orphan_count": self.orphan_count,
            "orphans": self.orphans[:50],  # cap output
            "errors": self.errors,
            "summary": self.summary,
        }


def run(file_path: str | Path, model: ifcopenshell.file = None) -> SpatialCheckResult:
    """Check spatial containment of all elements.

    Args:
        file_path: Path to the IFC file.
        model: Pre-loaded ifcopenshell model (optional, avoids re-opening).
    """
    result = SpatialCheckResult()

    if model is None:
        try:
            model = ifcopenshell.open(str(file_path))
        except Exception as e:
            result.passed = False
            result.errors.append({"type": "ifc_parse_error", "message": str(e)})
            return result

    elements = model.by_type("IfcElement")
    result.total_elements = len(elements)

    for element in elements:
        try:
            container = ifcopenshell.util.element.get_container(element)
        except Exception:
            container = None

        if container is None:
            result.orphan_count += 1
            result.orphans.append({
                "global_id": element.GlobalId,
                "name": getattr(element, "Name", None) or "unnamed",
                "ifc_class": element.is_a(),
                "object_type": getattr(element, "ObjectType", None),
            })
        else:
            result.contained_elements += 1

    result.passed = result.orphan_count == 0
    return result
