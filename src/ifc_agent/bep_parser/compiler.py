"""Compiler for converting BEP YAML rules into IDS XML."""

import yaml
from pathlib import Path
from ifctester import ids

def compile_yaml_to_ids(yaml_path: str | Path, output_ids_path: str | Path | None = None) -> ids.Ids:
    """Read a YAML rule pack and compile it to an ifctester IDS specification."""
    yaml_path = Path(yaml_path)
    if not yaml_path.exists():
        raise FileNotFoundError(f"YAML file not found: {yaml_path}")

    with yaml_path.open('r', encoding='utf-8') as f:
        data = yaml.safe_load(f)

    project_name = data.get("project_name", "BEP Generated Specifications")
    
    # Initialize IDS block
    specifications = ids.Ids(title=project_name, description="Generated from BEP YAML Rule Pack by IFC Intelligence Agent")

    for rule in data.get("rules", []):
        spec = ids.Specification(
            name=rule.get("name", "Unnamed Rule"),
            description=rule.get("description", ""),
            ifcVersion=["IFC2X3", "IFC4", "IFC4X3_ADD2"]
        )

        # 1. Applicability
        for ent in rule.get("applicable_entities", []):
            spec.applicability.append(ids.Entity(name=ent))

        # 2. Requirements
        for req in rule.get("requirements", []):
            req_type = req.get("type", "property").lower()
            
            if req_type == "attribute":
                expected = req.get("expected_pattern") or req.get("expected_value")
                attr = ids.Attribute(
                    name=req.get("name", ""),
                    value=expected
                )
                spec.requirements.append(attr)
                
            elif req_type == "property":
                expected = req.get("expected_pattern") or req.get("expected_value")
                prop = ids.Property(
                    propertySet=req.get("property_set", ""),
                    baseName=req.get("name", ""),
                    value=expected
                )
                spec.requirements.append(prop)

        # Add specification only if it has both applicability and requirements
        if spec.applicability and spec.requirements:
            specifications.specifications.append(spec)

    if output_ids_path:
        out_path = Path(output_ids_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        specifications.to_xml(str(out_path))

    return specifications
