import pytest
from pathlib import Path
from ifc_agent.bep_parser.compiler import compile_yaml_to_ids

def test_compile_yaml_to_ids(tmp_path):
    yaml_content = """
    project_name: Test Project BEP
    rules:
      - name: Wall Fire Rating
        description: Walls must have correct fire rating
        applicable_entities:
          - IFCWALL
        requirements:
          - type: property
            property_set: Pset_WallCommon
            name: FireRating
            expected_value: 60
      - name: Door Naming
        applicable_entities:
          - IFCDOOR
        requirements:
          - type: attribute
            name: Name
            expected_pattern: "^Door-.*$"
    """
    
    yaml_file = tmp_path / "test_rules.yaml"
    yaml_file.write_text(yaml_content, encoding='utf-8')
    
    ids_file = tmp_path / "test_rules.ids"
    
    spec = compile_yaml_to_ids(yaml_file, ids_file)
    
    assert len(spec.specifications) == 2
    assert spec.info.get("title") == "Test Project BEP"
    
    # Check Wall rule
    assert spec.specifications[0].name == "Wall Fire Rating"
    assert len(spec.specifications[0].applicability) == 1
    assert spec.specifications[0].applicability[0].name == "IFCWALL"
    assert len(spec.specifications[0].requirements) == 1
    assert spec.specifications[0].requirements[0].baseName == "FireRating"
    
    # Check Door rule
    assert spec.specifications[1].name == "Door Naming"
    assert len(spec.specifications[1].applicability) == 1
    assert spec.specifications[1].applicability[0].name == "IFCDOOR"
    assert len(spec.specifications[1].requirements) == 1
    assert spec.specifications[1].requirements[0].name == "Name"

    assert ids_file.exists()
