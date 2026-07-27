"""Apply one proxy reclassification group to a copied IFC file.

The script writes to a separate output path. It is intended to be called one
group at a time so a bad class reassignment cannot destroy the last good IFC.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import ifcopenshell
import ifcopenshell.api


def group_key(proxy) -> str:
    object_type = getattr(proxy, "ObjectType", None) or ""
    if object_type:
        return object_type
    name = getattr(proxy, "Name", None) or ""
    return name.rsplit(":", 1)[0] if ":" in name else name


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--pattern", required=True)
    parser.add_argument("--target-class", required=True)
    parser.add_argument("--audit", type=Path, required=True)
    args = parser.parse_args()

    model = ifcopenshell.open(str(args.source))
    matches = [proxy for proxy in model.by_type("IfcBuildingElementProxy") if group_key(proxy) == args.pattern]
    changes = []

    for proxy in matches:
        old_id = proxy.id()
        old_guid = proxy.GlobalId
        old_class = proxy.is_a()
        name = getattr(proxy, "Name", None)
        object_type = getattr(proxy, "ObjectType", None)
        ifcopenshell.api.run("root.reassign_class", model, product=proxy, ifc_class=args.target_class)
        changes.append(
            {
                "id": old_id,
                "global_id": old_guid,
                "old_class": old_class,
                "new_class": args.target_class,
                "name": name,
                "object_type": object_type,
                "pattern": args.pattern,
            }
        )

    model.write(str(args.output))
    args.audit.parent.mkdir(parents=True, exist_ok=True)
    args.audit.write_text(
        json.dumps(
            {
                "source": str(args.source),
                "output": str(args.output),
                "pattern": args.pattern,
                "target_class": args.target_class,
                "changed_count": len(changes),
                "changes": changes,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(json.dumps({"pattern": args.pattern, "target_class": args.target_class, "changed_count": len(changes)}, indent=2))


if __name__ == "__main__":
    main()
