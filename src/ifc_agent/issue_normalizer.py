"""Normalize checker-specific results into a common issue record shape."""

from __future__ import annotations

from typing import Any


def normalize_checker_report(report: Any) -> list[dict[str, Any]]:
    data = report.to_dict() if hasattr(report, "to_dict") else dict(report)
    results = data.get("results", {})
    issues: list[dict[str, Any]] = []

    if "schema" in results and not results["schema"].get("passed", True):
        for error in results["schema"].get("errors", []) or [{"message": results["schema"].get("summary", "Schema check failed")}]:
            issues.append(_issue("IFC-SCHEMA", "IFC schema validity", "schema", "critical", None, None, None, "schema_error", None, str(error.get("message", error)), error))

    if "guid" in results:
        for duplicate in results["guid"].get("duplicates", []) or []:
            for entity in duplicate.get("entities", []) or []:
                issues.append(
                    _issue(
                        "IFC-GUID-UNIQUE",
                        "GlobalId must be unique",
                        "guid",
                        "critical",
                        duplicate.get("guid"),
                        entity.get("ifc_class"),
                        entity.get("name"),
                        "duplicate_global_id",
                        "GlobalId",
                        f"Duplicate GlobalId {duplicate.get('guid')} appears {duplicate.get('count')} times.",
                        {"duplicate": duplicate, "entity": entity},
                        suggested_fix={"method": "generate_new_guid_in_copy", "auto_fixable": True},
                        auto_fixable=True,
                    )
                )

    if "spatial" in results:
        for orphan in results["spatial"].get("orphans", []) or []:
            issues.append(
                _issue(
                    "SPATIAL-CONTAINMENT-REQUIRED",
                    "Elements must be spatially contained",
                    "spatial",
                    "high",
                    orphan.get("global_id"),
                    orphan.get("ifc_class"),
                    orphan.get("name"),
                    "missing_spatial_container",
                    "IfcRelContainedInSpatialStructure",
                    "Element is not contained in a spatial structure.",
                    orphan,
                    suggested_fix={"method": "fix_in_source_model_or_assign_container", "auto_fixable": False},
                )
            )

    if "proxy" in results:
        for proxy in results["proxy"].get("proxies", []) or []:
            issues.append(
                _issue(
                    "IFC-PROXY-REVIEW",
                    "Building element proxies require review",
                    "proxy",
                    "medium",
                    proxy.get("global_id"),
                    "IfcBuildingElementProxy",
                    proxy.get("name"),
                    "proxy_element",
                    "IfcBuildingElementProxy",
                    "Element is exported as IfcBuildingElementProxy and should be reviewed for correct IFC class or explicit approval.",
                    proxy,
                    suggested_fix={"method": "review_export_mapping_or_tag_proxy_review", "auto_fixable": False},
                    approval_required=True,
                )
            )

    if "type" in results:
        for elem in results["type"].get("untyped_elements", []) or []:
            issues.append(
                _issue(
                    "TYPE-ASSIGNMENT-REQUIRED",
                    "Elements should have type assignment",
                    "type",
                    "medium",
                    elem.get("global_id"),
                    elem.get("ifc_class"),
                    elem.get("name"),
                    "missing_type_assignment",
                    "IfcRelDefinesByType",
                    "Element has no type assignment.",
                    elem,
                    suggested_fix={"method": "fix_family_type_export_or_assign_type", "auto_fixable": False},
                )
            )

    if "ids" in results:
        ids_result = results["ids"]
        for failure in ids_result.get("failures", []) or []:
            rule_id = _rule_id("IDS", failure.get("spec_name"), failure.get("requirement"))
            for entity in failure.get("failed_entities", []) or []:
                issues.append(
                    _issue(
                        rule_id,
                        failure.get("spec_name") or "IDS requirement",
                        "ids",
                        "high",
                        entity.get("global_id"),
                        entity.get("ifc_class"),
                        entity.get("name"),
                        "ids_requirement_failed",
                        failure.get("requirement"),
                        f"IDS requirement failed: {failure.get('requirement')} - {entity.get('reason') or failure.get('description')}",
                        _ids_evidence(ids_result, failure, entity),
                        type_name=entity.get("type_name"),
                        approval_required=False,
                    )
                )

    for error in data.get("errors", []) or []:
        issues.append(_issue("CHECKER-ERROR", "Checker execution error", "system", "high", None, None, None, error.get("type", "checker_error"), None, error.get("message", str(error)), error))

    return issues


def _issue(
    rule_id: str,
    rule_name: str,
    category: str,
    severity: str,
    global_id: str | None,
    ifc_class: str | None,
    element_name: str | None,
    problem_type: str,
    field: str | None,
    message: str,
    evidence: Any,
    suggested_fix: dict[str, Any] | None = None,
    type_name: str | None = None,
    auto_fixable: bool = False,
    approval_required: bool = False,
) -> dict[str, Any]:
    return {
        "rule_id": rule_id,
        "rule_name": rule_name,
        "category": category,
        "status": "detected",
        "severity": severity,
        "global_id": global_id,
        "ifc_class": ifc_class,
        "element_name": element_name,
        "type_name": type_name,
        "problem_type": problem_type,
        "field": field,
        "message": message,
        "evidence": evidence,
        "suggested_fix": suggested_fix or {},
        "auto_fixable": auto_fixable,
        "approval_required": approval_required,
        "source": "checker",
    }


def _ids_evidence(ids_result: dict[str, Any], failure: dict[str, Any], entity: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": "ids_requirement_failure",
        "ids_file": ids_result.get("ids_file"),
        "report_paths": ids_result.get("report_paths", {}),
        "spec_name": failure.get("spec_name"),
        "requirement": failure.get("requirement"),
        "facet_type": failure.get("facet_type"),
        "description": failure.get("description"),
        "failed_count": failure.get("failed_count"),
        "total_applicable": failure.get("total_applicable"),
        "percent_pass": failure.get("percent_pass"),
        "entity": {
            "global_id": entity.get("global_id"),
            "ifc_class": entity.get("ifc_class"),
            "name": entity.get("name"),
            "tag": entity.get("tag"),
            "element_id": entity.get("element_id"),
            "type_name": entity.get("type_name"),
            "reason": entity.get("reason"),
        },
    }


def _rule_id(*parts: Any) -> str:
    text = "-".join(str(part or "").strip().upper() for part in parts if str(part or "").strip())
    return "".join(char if char.isalnum() else "-" for char in text).strip("-")[:120] or "IDS-REQUIREMENT"
