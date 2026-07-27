"""Check 1.7 — Missing type assignment check.

Every IfcElement should reference an IfcTypeObject. Elements with no type
are harder to manage at FM (Facility Management) stage.
"""

import ifcopenshell
import ifcopenshell.util.element
from pathlib import Path
from dataclasses import dataclass, field


@dataclass
class TypeCheckResult:
    """Result of type assignment check."""
    passed: bool = True
    total_elements: int = 0
    typed_elements: int = 0
    untyped_count: int = 0
    untyped_elements: list = field(default_factory=list)
    errors: list = field(default_factory=list)

    @property
    def typed_percentage(self) -> float:
        if self.total_elements == 0:
            return 100.0
        return (self.typed_elements / self.total_elements) * 100

    @property
    def summary(self) -> str:
        if self.passed:
            return f"Type OK — all {self.total_elements} elements have type assignments"
        return (
            f"Type ISSUES — {self.untyped_count} element(s) without type assignment "
            f"({self.typed_percentage:.1f}% typed)"
        )

    def to_dict(self) -> dict:
        return {
            "check": "type",
            "passed": self.passed,
            "total_elements": self.total_elements,
            "typed_elements": self.typed_elements,
            "untyped_count": self.untyped_count,
            "typed_percentage": round(self.typed_percentage, 1),
            "untyped_elements": self.untyped_elements[:50],
            "errors": self.errors,
            "summary": self.summary,
        }


def run(file_path: str | Path, model: ifcopenshell.file = None) -> TypeCheckResult:
    """Check that all IfcElement instances have a type assignment.

    Args:
        file_path: Path to the IFC file.
        model: Pre-loaded ifcopenshell model (optional).
    """
    result = TypeCheckResult()

    if model is None:
        try:
            model = ifcopenshell.open(str(file_path))
        except Exception as e:
            result.passed = False
            result.errors.append({"type": "ifc_parse_error", "message": str(e)})
            return result

    elements = [
        element for element in model.by_type("IfcElement")
        if not element.is_a("IfcOpeningElement")
    ]
    result.total_elements = len(elements)

    for element in elements:
        try:
            element_type = ifcopenshell.util.element.get_type(element)
        except Exception:
            element_type = None

        if element_type is None:
            result.untyped_count += 1
            result.untyped_elements.append({
                "global_id": element.GlobalId,
                "name": getattr(element, "Name", None) or "unnamed",
                "ifc_class": element.is_a(),
                "object_type": getattr(element, "ObjectType", None),
            })
        else:
            result.typed_elements += 1

    result.passed = result.untyped_count == 0
    return result
