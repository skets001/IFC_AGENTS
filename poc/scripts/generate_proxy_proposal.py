"""Generate a proxy reclassification proposal from issue_audit.json."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def propose(pattern: str) -> tuple[str, str, float, str]:
    text = pattern.lower()
    if "model text" in text:
        return "SKIP", "", 0.95, "Annotation/model text; keep out of asset reclassification."
    if "logo" in text:
        return "SKIP", "", 0.95, "Logo/signage placeholder; keep as proxy unless signage classification is required."
    if "massing" in text:
        return "SKIP", "", 0.95, "Massing placeholder; do not convert to physical asset class automatically."
    if "generic models 01" in text or "generic models 02" in text:
        return "REVIEW", "", 0.40, "Generic placeholder family; needs visual/model author review."
    if "wall sweep" in text or "wall sweeps" in text or "tile base" in text:
        return "RECLASSIFY", "IfcCovering", 0.90, "Wall sweep/tile base is best represented as a covering/finish."
    if "metal truss" in text:
        return "RECLASSIFY", "IfcMember", 0.85, "Structural framing truss is likely a member assembly; validate IfcBeam vs IfcMember."
    if "steel post" in text:
        return "RECLASSIFY", "IfcColumn", 0.90, "Steel post is a vertical structural/support element."
    if "receptacle" in text:
        return "RECLASSIFY", "IfcOutlet", 0.95, "Electrical receptacle maps directly to IfcOutlet."
    if "lighting switches" in text or "switch" in text:
        return "RECLASSIFY", "IfcSwitchingDevice", 0.90, "Lighting switch maps to IfcSwitchingDevice."
    if "metal ladder" in text:
        return "RECLASSIFY", "IfcStairFlight", 0.75, "Ladder can be represented as circulation flight; confirm project convention."
    if "tree" in text or "planting" in text:
        return "RECLASSIFY", "IfcGeographicElement", 0.85, "Planting/tree is site/geographic context."
    if "steel platform" in text:
        return "RECLASSIFY", "IfcSlab", 0.75, "Steel platform is likely a slab/platform; validate IfcPlate vs IfcSlab."
    return "REVIEW", "", 0.30, "No confident automatic mapping."


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("audit_json", type=Path)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()

    audit = json.loads(args.audit_json.read_text(encoding="utf-8"))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    out_csv = args.output_dir / "proxy_reclassification_proposal.csv"
    out_json = args.output_dir / "proxy_reclassification_proposal.json"

    rows = []
    for group in audit["proxy_groups"]:
        action, target, confidence, rationale = propose(group["pattern"])
        rows.append(
            {
                "pattern": group["pattern"],
                "count": group["count"],
                "recommended_action": action,
                "target_ifc_class": target,
                "confidence": confidence,
                "rationale": rationale,
                "sample_global_ids": ";".join(sample["global_id"] for sample in group["samples"]),
                "sample_names": " | ".join(sample["name"] for sample in group["samples"][:3]),
            }
        )

    out_json.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    summary = {}
    for row in rows:
        key = f"{row['recommended_action']}:{row['target_ifc_class']}"
        summary[key] = summary.get(key, 0) + row["count"]

    print(json.dumps({"proposal_csv": str(out_csv), "proposal_json": str(out_json), "summary_by_action": summary}, indent=2))


if __name__ == "__main__":
    main()
