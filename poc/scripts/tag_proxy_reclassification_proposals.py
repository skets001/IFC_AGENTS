"""Write proxy reclassification proposals into an IFC as audit properties."""

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
    parser.add_argument("--audit", type=Path, required=True)
    args = parser.parse_args()

    with args.proposal_csv.open(newline="", encoding="utf-8") as f:
        proposals = {row["pattern"]: row for row in csv.DictReader(f)}

    model = ifcopenshell.open(str(args.source))
    tagged = []
    pset_name = "Pset_IFCAgentProxyReview"

    for proxy in model.by_type("IfcBuildingElementProxy"):
        pattern = group_key(proxy)
        proposal = proposals.get(pattern)
        if not proposal:
            continue

        pset = None
        for rel in getattr(proxy, "IsDefinedBy", []) or []:
            if rel.is_a("IfcRelDefinesByProperties"):
                prop_def = rel.RelatingPropertyDefinition
                if prop_def.is_a("IfcPropertySet") and prop_def.Name == pset_name:
                    pset = prop_def
                    break
        if pset is None:
            pset = ifcopenshell.api.run("pset.add_pset", model, product=proxy, name=pset_name)

        properties = {
            "RecommendedAction": proposal["recommended_action"],
            "RecommendedIFCClass": proposal["target_ifc_class"] or "",
            "RecommendationConfidence": proposal["confidence"],
            "RecommendationRationale": proposal["rationale"],
            "ProxyGroupPattern": pattern,
        }
        ifcopenshell.api.run("pset.edit_pset", model, pset=pset, properties=properties)
        tagged.append(
            {
                "global_id": proxy.GlobalId,
                "name": getattr(proxy, "Name", None),
                "object_type": getattr(proxy, "ObjectType", None),
                **properties,
            }
        )

    model.write(str(args.output))
    args.audit.parent.mkdir(parents=True, exist_ok=True)
    args.audit.write_text(
        json.dumps(
            {
                "source": str(args.source),
                "output": str(args.output),
                "pset_name": pset_name,
                "tagged_count": len(tagged),
                "tagged": tagged,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(json.dumps({"output": str(args.output), "pset_name": pset_name, "tagged_count": len(tagged)}, indent=2))


if __name__ == "__main__":
    main()
