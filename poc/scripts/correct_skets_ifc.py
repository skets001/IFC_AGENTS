"""Project-specific correction pass for the SKETS Campus IFC.

This script never edits the source file in place. It writes a corrected output
IFC plus JSON/CSV audit files describing every mutation.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

import ifcopenshell
import ifcopenshell.api
import ifcopenshell.guid


def classify_proxy(proxy) -> tuple[str | None, str]:
    text = f"{getattr(proxy, 'Name', '') or ''} {getattr(proxy, 'ObjectType', '') or ''}".lower()

    if any(token in text for token in ["model text", "logo", "massing", "generic models 01", "generic models 02"]):
        return None, "Skipped annotation/massing/generic placeholder."
    if "wall sweep" in text or "wall sweeps" in text or "tile base" in text:
        return "IfcCovering", "Wall sweep/tile base is a finish/covering element."
    if "metal truss" in text:
        return "IfcMember", "Structural framing truss mapped to member."
    if "steel post" in text:
        return "IfcColumn", "Steel post mapped to vertical structural column."
    if "receptacle" in text:
        return "IfcOutlet", "Electrical receptacle mapped to IFC outlet."
    if "lighting switches" in text or "switch" in text:
        return "IfcSwitchingDevice", "Lighting switch mapped to switching device."
    if "metal ladder" in text:
        return "IfcStairFlight", "Ladder mapped to stair/ladder flight for circulation."
    if "tree" in text or "planting" in text:
        return "IfcGeographicElement", "Planting/tree mapped to geographic/site element."
    if "steel platform" in text:
        return "IfcSlab", "Steel platform mapped to slab/platform element."
    return None, "No confident mapping rule."


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--audit-dir", type=Path, required=True)
    args = parser.parse_args()

    args.audit_dir.mkdir(parents=True, exist_ok=True)
    model = ifcopenshell.open(str(args.source))
    changes: list[dict] = []
    skipped: list[dict] = []
    errors: list[dict] = []

    guid_map: dict[str, list] = defaultdict(list)
    for entity in model.by_type("IfcRoot"):
        guid_map[entity.GlobalId].append(entity)

    for guid, entities in guid_map.items():
        if len(entities) <= 1:
            continue
        for entity in entities[1:]:
            old_guid = entity.GlobalId
            new_guid = ifcopenshell.guid.new()
            entity.GlobalId = new_guid
            changes.append(
                {
                    "action": "regenerate_duplicate_guid",
                    "id": entity.id(),
                    "old_guid": old_guid,
                    "new_guid": new_guid,
                    "old_class": entity.is_a(),
                    "new_class": entity.is_a(),
                    "name": getattr(entity, "Name", None),
                    "object_type": getattr(entity, "ObjectType", None),
                    "reason": "Duplicate GlobalId; first occurrence preserved, later occurrence regenerated.",
                }
            )

    for proxy in list(model.by_type("IfcBuildingElementProxy")):
        target_class, reason = classify_proxy(proxy)
        if target_class is None:
            skipped.append(
                {
                    "id": proxy.id(),
                    "global_id": proxy.GlobalId,
                    "class": proxy.is_a(),
                    "name": getattr(proxy, "Name", None),
                    "object_type": getattr(proxy, "ObjectType", None),
                    "reason": reason,
                }
            )
            continue

        try:
            old_id = proxy.id()
            old_guid = proxy.GlobalId
            old_class = proxy.is_a()
            name = getattr(proxy, "Name", None)
            object_type = getattr(proxy, "ObjectType", None)
            ifcopenshell.api.run("root.reassign_class", model, product=proxy, ifc_class=target_class)
            changes.append(
                {
                    "action": "reassign_proxy_class",
                    "id": old_id,
                    "global_id": old_guid,
                    "old_class": old_class,
                    "new_class": target_class,
                    "name": name,
                    "object_type": object_type,
                    "reason": reason,
                }
            )
        except Exception as exc:  # pragma: no cover - depends on source IFC data
            errors.append(
                {
                    "id": proxy.id(),
                    "global_id": proxy.GlobalId,
                    "target_class": target_class,
                    "name": getattr(proxy, "Name", None),
                    "object_type": getattr(proxy, "ObjectType", None),
                    "error": str(exc),
                }
            )

    model.write(str(args.output))

    summary = {
        "source": str(args.source),
        "output": str(args.output),
        "changes": len(changes),
        "proxy_reclassifications": sum(1 for c in changes if c["action"] == "reassign_proxy_class"),
        "duplicate_guid_fixes": sum(1 for c in changes if c["action"] == "regenerate_duplicate_guid"),
        "skipped_proxies": len(skipped),
        "errors": len(errors),
    }

    (args.audit_dir / "correction_summary.json").write_text(
        json.dumps({"summary": summary, "changes": changes, "skipped": skipped, "errors": errors}, indent=2),
        encoding="utf-8",
    )

    with (args.audit_dir / "correction_changes.csv").open("w", newline="", encoding="utf-8") as f:
        fieldnames = ["action", "id", "global_id", "old_guid", "new_guid", "old_class", "new_class", "name", "object_type", "reason"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in changes:
            writer.writerow({k: row.get(k, "") for k in fieldnames})

    with (args.audit_dir / "skipped_proxies.csv").open("w", newline="", encoding="utf-8") as f:
        fieldnames = ["id", "global_id", "class", "name", "object_type", "reason"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in skipped:
            writer.writerow(row)

    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
