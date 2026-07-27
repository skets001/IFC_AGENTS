"""Apply all proxy proposal rows for one target IFC class."""

from __future__ import annotations

import argparse
import csv
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
    parser.add_argument("proposal_csv", type=Path)
    parser.add_argument("--target-class", required=True)
    parser.add_argument("--audit", type=Path, required=True)
    args = parser.parse_args()

    with args.proposal_csv.open(newline="", encoding="utf-8") as f:
        proposal_rows = list(csv.DictReader(f))

    patterns = {
        row["pattern"]
        for row in proposal_rows
        if row["recommended_action"] == "RECLASSIFY" and row["target_ifc_class"] == args.target_class
    }

    model = ifcopenshell.open(str(args.source))
    changes = []
    for proxy in list(model.by_type("IfcBuildingElementProxy")):
        pattern = group_key(proxy)
        if pattern not in patterns:
            continue
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
                "pattern": pattern,
            }
        )

    model.write(str(args.output))
    args.audit.parent.mkdir(parents=True, exist_ok=True)
    args.audit.write_text(
        json.dumps(
            {
                "source": str(args.source),
                "output": str(args.output),
                "target_class": args.target_class,
                "patterns": sorted(patterns),
                "changed_count": len(changes),
                "changes": changes,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(json.dumps({"target_class": args.target_class, "changed_count": len(changes)}, indent=2))


if __name__ == "__main__":
    main()
