"""Check 1.5 — Proxy element detection.

Finds all IfcBuildingElementProxy elements and groups them by ObjectType
pattern for batch reclassification in Phase 5.
"""

import re
import ifcopenshell
from pathlib import Path
from collections import defaultdict
from dataclasses import dataclass, field


@dataclass
class ProxyCheckResult:
    """Result of proxy element detection."""
    passed: bool = True
    proxy_count: int = 0
    total_elements: int = 0
    proxy_percentage: float = 0.0
    proxies: list = field(default_factory=list)
    groups: list = field(default_factory=list)
    errors: list = field(default_factory=list)

    @property
    def summary(self) -> str:
        if self.proxy_count == 0:
            return f"Proxy OK — no proxies among {self.total_elements} elements"
        return (
            f"Proxy WARNING — {self.proxy_count} proxy element(s) "
            f"({self.proxy_percentage:.1f}%) in {len(self.groups)} group(s)"
        )

    def to_dict(self) -> dict:
        return {
            "check": "proxy",
            "passed": self.passed,
            "proxy_count": self.proxy_count,
            "total_elements": self.total_elements,
            "proxy_percentage": self.proxy_percentage,
            "proxies": self.proxies[:100],  # cap output
            "groups": self.groups,
            "errors": self.errors,
            "summary": self.summary,
        }


def _infer_group_key(name: str, object_type: str) -> str:
    """Infer a grouping key from element name and object type.

    Tries to find a common prefix pattern for batch reclassification.
    E.g., 'FCU-01', 'FCU-02', 'FCU-03' → 'FCU_*'
    """
    if object_type:
        return object_type

    if name:
        # Strip trailing numbers, dashes, underscores to find prefix
        prefix = re.sub(r"[-_\s]*\d+\s*$", "", name)
        if prefix:
            return f"{prefix}_*"

    return "ungrouped"


def run(file_path: str | Path, model: ifcopenshell.file = None) -> ProxyCheckResult:
    """Detect all IfcBuildingElementProxy elements and group them.

    Args:
        file_path: Path to the IFC file.
        model: Pre-loaded ifcopenshell model (optional).
    """
    result = ProxyCheckResult()

    if model is None:
        try:
            model = ifcopenshell.open(str(file_path))
        except Exception as e:
            result.passed = False
            result.errors.append({"type": "ifc_parse_error", "message": str(e)})
            return result

    result.total_elements = len(model.by_type("IfcElement"))
    proxies = model.by_type("IfcBuildingElementProxy")
    result.proxy_count = len(proxies)

    if result.total_elements > 0:
        result.proxy_percentage = (result.proxy_count / result.total_elements) * 100

    # Collect proxy info
    groups_map = defaultdict(list)

    for proxy in proxies:
        name = getattr(proxy, "Name", None) or ""
        description = getattr(proxy, "Description", None) or ""
        object_type = getattr(proxy, "ObjectType", None) or ""
        global_id = proxy.GlobalId

        proxy_info = {
            "global_id": global_id,
            "name": name,
            "description": description,
            "object_type": object_type,
        }
        result.proxies.append(proxy_info)

        # Group for batch reclassification
        group_key = _infer_group_key(name, object_type)
        groups_map[group_key].append(global_id)

    # Build groups summary
    for group_key, member_ids in sorted(groups_map.items(), key=lambda x: -len(x[1])):
        result.groups.append({
            "pattern": group_key,
            "count": len(member_ids),
            "sample_ids": member_ids[:5],
        })

    # Proxies are a warning, not a hard failure — but flag them
    result.passed = result.proxy_count == 0
    return result
