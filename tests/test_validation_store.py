import ifcopenshell
import ifcopenshell.api

from ifc_agent.checker.runner import run_all
from ifc_agent.ifc_indexer import index_ifc_file
from ifc_agent.issue_normalizer import normalize_checker_report
from ifc_agent.validation_store import ValidationStore


def _problem_model() -> ifcopenshell.file:
    model = ifcopenshell.file(schema="IFC4")
    project = ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcProject", name="Project")
    site = ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcSite", name="Site")
    building = ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcBuilding", name="Building")
    storey = ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcBuildingStorey", name="Level 1")
    ifcopenshell.api.run("aggregate.assign_object", model, relating_object=project, products=[site])
    ifcopenshell.api.run("aggregate.assign_object", model, relating_object=site, products=[building])
    ifcopenshell.api.run("aggregate.assign_object", model, relating_object=building, products=[storey])

    wall = ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcWall", name="Wall-01")
    wall_type = ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcWallType", name="Wall Type")
    ifcopenshell.api.run("type.assign_type", model, related_objects=[wall], relating_type=wall_type)
    ifcopenshell.api.run("spatial.assign_container", model, relating_structure=storey, products=[wall])

    proxy = ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcBuildingElementProxy", name="Proxy-01")
    proxy.ObjectType = "Generic exported family"
    ifcopenshell.api.run("spatial.assign_container", model, relating_structure=storey, products=[proxy])

    column = ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcColumn", name="Column without type")
    ifcopenshell.api.run("spatial.assign_container", model, relating_structure=storey, products=[column])

    ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcBeam", name="Orphan Beam")
    return model


def test_index_ifc_file_persists_model_and_elements(tmp_path):
    ifc_path = tmp_path / "model.ifc"
    _problem_model().write(str(ifc_path))
    store = ValidationStore(tmp_path / "validation.sqlite")

    summary = index_ifc_file(ifc_path, store)

    assert summary["model_id"]
    assert summary["element_count"] >= 4
    model = store.get_model(summary["model_id"])
    assert model["schema"] == "IFC4"
    walls = store.list_elements(summary["model_id"], ifc_class="IfcWall")
    assert walls["total"] == 1
    wall = store.get_element(summary["model_id"], walls["elements"][0]["global_id"])
    assert wall["storey"] == "Level 1"
    assert wall["type_name"] == "Wall Type"


def test_validation_run_and_normalized_issues_are_persisted(tmp_path):
    ifc_path = tmp_path / "problem.ifc"
    _problem_model().write(str(ifc_path))
    store = ValidationStore(tmp_path / "validation.sqlite")
    index_summary = index_ifc_file(ifc_path, store)

    report = run_all(ifc_path, checks=["schema", "spatial", "guid", "proxy", "type"])
    issues = normalize_checker_report(report)
    run_id = store.create_validation_run(index_summary["model_id"], ifc_path, ["schema", "spatial", "guid", "proxy", "type"], None, report, {})
    issue_count = store.replace_issues(run_id, index_summary["model_id"], issues)

    assert issue_count >= 3
    runs = store.list_runs(ifc_path)
    assert runs[0]["run_id"] == run_id
    assert "result_summary" in runs[0]
    assert "result" not in runs[0]
    full_runs = store.list_runs(ifc_path, include_result=True)
    assert "result" in full_runs[0]
    stored = store.list_issues(run_id=run_id, limit=20)
    assert "evidence" not in stored["issues"][0]
    assert "evidence_summary" in stored["issues"][0]
    assert "ifc_id" in stored["issues"][0]
    stored_with_evidence = store.list_issues(run_id=run_id, limit=1, include_evidence=True)
    assert "evidence" in stored_with_evidence["issues"][0]
    assert "evidence_summary" not in stored_with_evidence["issues"][0]
    one_issue = store.list_issues(issue_id=stored["issues"][0]["issue_id"], include_evidence=True)
    assert one_issue["total"] == 1
    assert one_issue["issues"][0]["issue_id"] == stored["issues"][0]["issue_id"]
    categories = {issue["category"] for issue in stored["issues"]}
    assert {"spatial", "proxy", "type"}.issubset(categories)
    assert stored["total"] == issue_count


def test_ids_normalized_evidence_is_compact():
    report = {
        "results": {
            "ids": {
                "ids_file": "handover.ids",
                "report_paths": {"json": "ids_report.json", "html": "ids_report.html"},
                "failures": [
                    {
                        "spec_name": "Door tag required",
                        "requirement": "Tag",
                        "facet_type": "attribute",
                        "description": "Door requires a tag",
                        "failed_count": 2,
                        "total_applicable": 2,
                        "percent_pass": 0,
                        "failed_entities": [
                            {"global_id": "G1", "ifc_class": "IfcDoor", "name": "Door 1", "tag": "", "element_id": 10, "reason": "Missing Tag"},
                            {"global_id": "G2", "ifc_class": "IfcDoor", "name": "Door 2", "tag": "", "element_id": 11, "reason": "Missing Tag"},
                        ],
                    }
                ],
            }
        }
    }

    issues = normalize_checker_report(report)

    assert len(issues) == 2
    evidence = issues[0]["evidence"]
    assert evidence["kind"] == "ids_requirement_failure"
    assert evidence["ids_file"] == "handover.ids"
    assert evidence["report_paths"]["json"] == "ids_report.json"
    assert evidence["failed_count"] == 2
    assert evidence["entity"]["global_id"] == "G1"
    assert "failure" not in evidence
    assert "failed_entities" not in evidence
