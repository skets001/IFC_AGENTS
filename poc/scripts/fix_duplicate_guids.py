"""Fix duplicate IfcRoot GlobalIds without editing the source in place."""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

import ifcopenshell
import ifcopenshell.guid


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--audit-dir", type=Path, required=True)
    args = parser.parse_args()

    args.audit_dir.mkdir(parents=True, exist_ok=True)
    model = ifcopenshell.open(str(args.source))

    guid_map: dict[str, list] = defaultdict(list)
    for entity in model.by_type("IfcRoot"):
        guid_map[entity.GlobalId].append(entity)

    changes = []
    for guid, entities in guid_map.items():
        if len(entities) <= 1:
            continue
        for entity in entities[1:]:
            old_guid = entity.GlobalId
            new_guid = ifcopenshell.guid.new()
            entity.GlobalId = new_guid
            changes.append(
                {
                    "id": entity.id(),
                    "old_guid": old_guid,
                    "new_guid": new_guid,
                    "ifc_class": entity.is_a(),
                    "name": getattr(entity, "Name", None),
                    "object_type": getattr(entity, "ObjectType", None),
                }
            )

    model.write(str(args.output))

    summary = {
        "source": str(args.source),
        "output": str(args.output),
        "duplicate_guid_fixes": len(changes),
    }
    (args.audit_dir / "guid_fix_summary.json").write_text(
        json.dumps({"summary": summary, "changes": changes}, indent=2),
        encoding="utf-8",
    )
    with (args.audit_dir / "guid_fix_changes.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["id", "old_guid", "new_guid", "ifc_class", "name", "object_type"])
        writer.writeheader()
        writer.writerows(changes)

    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
