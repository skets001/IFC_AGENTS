"""Tests for IFC Checker modules.

Uses programmatically-created IFC models via ifcopenshell API
so no external test files are needed.
"""

import pytest
import ifcopenshell
import ifcopenshell.api
from pathlib import Path

from ifc_agent.checker import (
    ids_check,
    schema_check,
    spatial_check,
    guid_check,
    proxy_check,
    type_check,
)
from ifc_agent.checker.runner import run_all


def _create_minimal_model() -> tuple[ifcopenshell.file, str]:
    """Create a minimal valid IFC4 model with a wall, door, and space.

    Returns (model, temp_file_path).
    """
    model = ifcopenshell.file(schema="IFC4")

    # Create project structure
    project = ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcProject", name="Test Project")
    site = ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcSite", name="Test Site")
    building = ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcBuilding", name="Test Building")
    storey = ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcBuildingStorey", name="Level 0")

    # Aggregate spatial hierarchy
    ifcopenshell.api.run("aggregate.assign_object", model, relating_object=project, products=[site])
    ifcopenshell.api.run("aggregate.assign_object", model, relating_object=site, products=[building])
    ifcopenshell.api.run("aggregate.assign_object", model, relating_object=building, products=[storey])

    # Create a wall with type
    wall = ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcWall", name="Wall-01")
    wall_type = ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcWallType", name="Wall Type A")
    ifcopenshell.api.run("type.assign_type", model, related_objects=[wall], relating_type=wall_type)
    ifcopenshell.api.run("spatial.assign_container", model, relating_structure=storey, products=[wall])

    # Create a door with type
    door = ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcDoor", name="Door-01")
    door_type = ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcDoorType", name="Door Type A")
    ifcopenshell.api.run("type.assign_type", model, related_objects=[door], relating_type=door_type)
    ifcopenshell.api.run("spatial.assign_container", model, relating_structure=storey, products=[door])

    return model


def _create_problem_model() -> ifcopenshell.file:
    """Create a model with known issues for testing detection."""
    model = ifcopenshell.file(schema="IFC4")

    # Create project structure
    project = ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcProject", name="Problem Project")
    site = ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcSite", name="Test Site")
    building = ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcBuilding", name="Test Building")
    storey = ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcBuildingStorey", name="Level 0")

    ifcopenshell.api.run("aggregate.assign_object", model, relating_object=project, products=[site])
    ifcopenshell.api.run("aggregate.assign_object", model, relating_object=site, products=[building])
    ifcopenshell.api.run("aggregate.assign_object", model, relating_object=building, products=[storey])

    # Wall with type (good)
    wall = ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcWall", name="Wall-01")
    wall_type = ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcWallType", name="Wall Type A")
    ifcopenshell.api.run("type.assign_type", model, related_objects=[wall], relating_type=wall_type)
    ifcopenshell.api.run("spatial.assign_container", model, relating_structure=storey, products=[wall])

    # Orphan element — NOT assigned to any spatial container
    orphan = ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcBeam", name="Orphan-Beam-01")

    # Proxy element
    proxy = ifcopenshell.api.run(
        "root.create_entity", model,
        ifc_class="IfcBuildingElementProxy",
        name="FCU-01",
    )
    proxy.ObjectType = "Fan Coil Unit"
    ifcopenshell.api.run("spatial.assign_container", model, relating_structure=storey, products=[proxy])

    # Element without type assignment
    column = ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcColumn", name="Col-01")
    ifcopenshell.api.run("spatial.assign_container", model, relating_structure=storey, products=[column])

    return model


class TestSchemaCheck:
    def test_valid_file(self, tmp_path):
        model = _create_minimal_model()
        ifc_path = tmp_path / "valid.ifc"
        model.write(str(ifc_path))

        result = schema_check.run(ifc_path)
        assert result.passed is True
        assert result.ifc_version == "IFC4"
        assert result.entity_count > 0

    def test_nonexistent_file(self, tmp_path):
        result = schema_check.run(tmp_path / "nonexistent.ifc")
        assert result.passed is False
        assert len(result.errors) > 0


class TestSpatialCheck:
    def test_all_contained(self):
        model = _create_minimal_model()
        result = spatial_check.run("", model=model)
        assert result.passed is True
        assert result.orphan_count == 0

    def test_orphan_detected(self):
        model = _create_problem_model()
        result = spatial_check.run("", model=model)
        assert result.passed is False
        assert result.orphan_count >= 1
        # The orphan beam should be in the list
        orphan_names = [o["name"] for o in result.orphans]
        assert "Orphan-Beam-01" in orphan_names


class TestGuidCheck:
    def test_unique_guids(self):
        model = _create_minimal_model()
        result = guid_check.run("", model=model)
        assert result.passed is True
        assert result.duplicate_count == 0

    def test_duplicate_detection(self):
        """Create a model with manually duplicated GUIDs."""
        model = ifcopenshell.file(schema="IFC4")
        project = ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcProject", name="Test")

        wall1 = ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcWall", name="Wall-A")
        wall2 = ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcWall", name="Wall-B")

        # Force same GUID
        wall2.GlobalId = wall1.GlobalId

        result = guid_check.run("", model=model)
        assert result.passed is False
        assert result.duplicate_count >= 1


class TestProxyCheck:
    def test_no_proxies(self):
        model = _create_minimal_model()
        result = proxy_check.run("", model=model)
        assert result.passed is True
        assert result.proxy_count == 0

    def test_proxy_detected(self):
        model = _create_problem_model()
        result = proxy_check.run("", model=model)
        assert result.passed is False
        assert result.proxy_count >= 1
        # Check grouping
        assert len(result.groups) >= 1


class TestTypeCheck:
    def test_all_typed(self):
        model = _create_minimal_model()
        result = type_check.run("", model=model)
        assert result.passed is True
        assert result.untyped_count == 0

    def test_untyped_detected(self):
        model = _create_problem_model()
        result = type_check.run("", model=model)
        assert result.passed is False
        assert result.untyped_count >= 1


class TestIdsCheck:
    def test_ids_failures_and_reports_are_populated(self, tmp_path):
        model = _create_minimal_model()
        ifc_path = tmp_path / "ids_model.ifc"
        model.write(str(ifc_path))
        ids_path = tmp_path / "door_tag.ids"
        ids_path.write_text(
            """<?xml version='1.0' encoding='utf-8'?>
<ids xmlns='http://standards.buildingsmart.org/IDS' xmlns:xsi='http://www.w3.org/2001/XMLSchema-instance'>
  <info><title>Door Tag Test</title></info>
  <specifications>
    <specification name='Door tag required' ifcVersion='IFC4'>
      <applicability minOccurs='0' maxOccurs='unbounded'>
        <entity><name><simpleValue>IFCDOOR</simpleValue></name></entity>
      </applicability>
      <requirements>
        <attribute cardinality='required'><name><simpleValue>Tag</simpleValue></name></attribute>
      </requirements>
    </specification>
  </specifications>
</ids>
""",
            encoding="utf-8",
        )

        result = ids_check.run(ifc_path, ids_path=ids_path, output_dir=tmp_path, write_reports=True)

        assert result.passed is False
        assert result.specs_checked == 1
        assert result.total_checks_failed >= 1
        assert result.failures
        assert result.failures[0]["failed_entities"]
        for key in ["json", "html", "csv", "summary_html", "ifctester_json"]:
            assert key in result.report_paths
            assert (tmp_path / Path(result.report_paths[key]).name).stat().st_size > 0

    def test_inspect_ids_returns_specification_metadata(self, tmp_path):
        ids_path = tmp_path / "simple.ids"
        ids_path.write_text(
            """<?xml version='1.0' encoding='utf-8'?>
<ids xmlns='http://standards.buildingsmart.org/IDS'>
  <info><title>Simple IDS</title></info>
  <specifications>
    <specification name='Wall name required' ifcVersion='IFC4'>
      <applicability minOccurs='0' maxOccurs='unbounded'><entity><name><simpleValue>IFCWALL</simpleValue></name></entity></applicability>
      <requirements><attribute cardinality='required'><name><simpleValue>Name</simpleValue></name></attribute></requirements>
    </specification>
  </specifications>
</ids>
""",
            encoding="utf-8",
        )

        result = ids_check.inspect_ids(ids_path)

        assert result["ok"] is True
        assert result["title"] == "Simple IDS"
        assert result["specification_count"] == 1


class TestRunner:
    def test_full_run_clean_model(self, tmp_path):
        model = _create_minimal_model()
        ifc_path = tmp_path / "clean.ifc"
        model.write(str(ifc_path))

        report = run_all(ifc_path, checks=["schema", "spatial", "guid", "proxy", "type"])
        assert report.checks_run == 5
        assert report.overall_passed is True

    def test_full_run_problem_model(self, tmp_path):
        model = _create_problem_model()
        ifc_path = tmp_path / "problems.ifc"
        model.write(str(ifc_path))

        report = run_all(ifc_path, checks=["schema", "spatial", "guid", "proxy", "type"])
        assert report.checks_run == 5
        assert report.overall_passed is False
        assert report.total_issues >= 3  # at least orphan + proxy + untyped
        assert report.telegram_summary  # should produce non-empty summary
