"""Structured evidence packs for Hermes agent reasoning.

The GUI agent endpoint should not send a random slice of validation issues to
the LLM. This module builds a compact, category-balanced evidence pack from the
SQLite validation store and existing audit artifacts.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from ifc_agent.validation_store import ValidationStore


DEFAULT_MAX_CHARS = 24000


def build_agent_evidence_pack(
    file_path: str | Path,
    store: ValidationStore,
    run_id: str | None = None,
    agent: str = "hermes_orchestrator",
    audit_dir: str | Path | None = None,
    max_issues_per_cluster: int = 3,
    max_issues: int = 20000,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> dict[str, Any]:
    """Build a compact, clustered evidence pack for agent reasoning.

    The pack intentionally carries cluster summaries and representative elements
    instead of unbounded issue lists. Full detail remains available through
    deterministic backend tools when the agent requests it.
    """
    path = Path(file_path)
    run = _select_run(store, path, run_id)
    if not run:
        return {"error": "no_validation_run", "file_path": str(path), "agent": agent}

    run_id = run["run_id"]
    model = store.get_model(run["model_id"]) or {}
    issue_data = store.list_issues(run_id=run_id, limit=max_issues, include_evidence=False)
    issues = issue_data.get("issues", [])

    clusters = _cluster_issues(issues, max_issues_per_cluster=max_issues_per_cluster)
    result = run.get("result") or {}
    results = result.get("results") or {}
    artifact_paths = _artifact_paths(path, audit_dir, run, results)

    ids_summary = build_ids_failure_summary_from_result(results.get("ids") or {})
    if not ids_summary.get("failed_requirements") and artifact_paths.get("ids_ifctester_json"):
        ids_summary = get_ids_failure_summary(artifact_paths["ids_ifctester_json"])

    pack = {
        "pack_version": 1,
        "agent": agent,
        "file_path": str(path),
        "run_id": run_id,
        "model_id": run.get("model_id"),
        "model_info": _model_info(model),
        "validation_run": {
            "status": run.get("status"),
            "started_at": run.get("started_at"),
            "completed_at": run.get("completed_at"),
            "duration_seconds": run.get("duration_seconds"),
            "checks": run.get("checks"),
            "ids_path": run.get("ids_path"),
            "reports": run.get("reports"),
            "result_summary": run.get("result_summary") or _result_summary(result),
        },
        "check_summaries": _check_summaries(results),
        "issue_clusters": clusters,
        "category_totals": dict(Counter(issue.get("category") for issue in issues if issue.get("category"))),
        "severity_totals": dict(Counter(issue.get("severity") for issue in issues if issue.get("severity"))),
        "class_totals": dict(Counter(issue.get("ifc_class") for issue in issues if issue.get("ifc_class"))),
        "issue_fetch_note": {
            "stored_total": issue_data.get("total"),
            "included_for_clustering": len(issues),
            "truncated": bool((issue_data.get("total") or 0) > len(issues)),
        },
        "ids_failure_summary": ids_summary,
        "cobie_gap_map": get_cobie_gap_map(artifact_paths.get("cobie_proposals", "")),
        "proxy_candidate_summary": get_proxy_candidate_summary(artifact_paths.get("proxy_reclassification", "")),
        "artifact_paths": artifact_paths,
        "human_in_loop": {
            "write_actions_disabled_in_agent_loop": True,
            "approval_required_for_ifc_mutation": True,
            "original_ifc_never_overwritten": True,
        },
    }
    return _trim_pack(pack, max_chars=max_chars)


def build_ids_failure_summary_from_result(ids_result: dict[str, Any]) -> dict[str, Any]:
    """Summarize normalized IDS checker output into root-cause evidence."""
    failures = []
    for failure in ids_result.get("failures", []) or []:
        entities = failure.get("failed_entities", []) or []
        reason_counts = Counter(str(entity.get("reason") or "unspecified") for entity in entities)
        failures.append(
            {
                "spec_name": failure.get("spec_name"),
                "requirement": failure.get("requirement"),
                "facet_type": failure.get("facet_type"),
                "description": failure.get("description"),
                "failed_count": failure.get("failed_count") or len(entities),
                "total_applicable": failure.get("total_applicable"),
                "percent_pass": failure.get("percent_pass"),
                "reason_counts": dict(reason_counts.most_common(5)),
                "sample_failures": [_entity_failure_sample(entity) for entity in entities[:5]],
            }
        )
    failures.sort(key=lambda item: int(item.get("failed_count") or 0), reverse=True)
    return {
        "ids_file": ids_result.get("ids_file"),
        "summary": ids_result.get("summary"),
        "specs_checked": ids_result.get("specs_checked"),
        "specs_passed": ids_result.get("specs_passed"),
        "specs_failed": ids_result.get("specs_failed"),
        "total_checks_failed": ids_result.get("total_checks_failed"),
        "total_requirements_failed": ids_result.get("total_requirements_failed"),
        "failed_requirements": failures,
        "total_failed_requirements": len(failures),
        "report_paths": ids_result.get("report_paths") or {},
    }


def get_ids_failure_summary(ids_report_path: str | Path) -> dict[str, Any]:
    """Parse a full ifctester JSON report into a compact requirement summary."""
    if not ids_report_path:
        return {"error": "ids_report_not_available"}
    path = Path(ids_report_path)
    if not path.exists():
        return {"error": "ids_report_not_found", "path": str(path)}
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"error": "ids_report_parse_failed", "path": str(path), "message": str(exc)}

    failures = []
    for spec in report.get("specifications", []) or []:
        for req in spec.get("requirements", []) or []:
            status = req.get("status", req.get("passed", True))
            if status:
                continue
            entities = req.get("failed_entities", []) or []
            failures.append(
                {
                    "spec_name": spec.get("name"),
                    "requirement": req.get("label") or req.get("description") or req.get("facet_type"),
                    "facet_type": req.get("facet_type"),
                    "description": req.get("description"),
                    "failed_count": int(req.get("total_fail") or req.get("failed_count") or len(entities)),
                    "total_applicable": req.get("total_applicable") or req.get("total_count"),
                    "percent_pass": req.get("percent_pass"),
                    "sample_failures": [_entity_failure_sample(entity) for entity in entities[:5]],
                }
            )
    failures.sort(key=lambda item: int(item.get("failed_count") or 0), reverse=True)
    return {"source_path": str(path), "failed_requirements": failures, "total_failed_requirements": len(failures)}


def get_cobie_gap_map(cobie_proposals_path: str | Path) -> dict[str, Any] | None:
    """Group generated COBie proposals by IFC class and missing/inferable fields."""
    if not cobie_proposals_path:
        return None
    path = Path(cobie_proposals_path)
    if not path.exists():
        return {"error": "cobie_proposals_not_found", "path": str(path)}
    try:
        proposals = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"error": "cobie_proposals_parse_failed", "path": str(path), "message": str(exc)}

    inferable_fields = {"ModelReference", "ModelLabel"}
    product_data_fields = {"Manufacturer", "ArticleNumber", "AssemblyPlace"}
    grouped: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "count": 0,
            "missing_fields": Counter(),
            "inferred_fields": Counter(),
            "needs_product_data_count": 0,
            "samples": [],
        }
    )

    for item in proposals:
        cls = item.get("ifc_class") or "Unknown"
        proposal = item.get("proposal") or {}
        row = grouped[cls]
        row["count"] += 1
        for field, value in proposal.items():
            if value in (None, ""):
                row["missing_fields"][field] += 1
                if field in product_data_fields:
                    row["needs_product_data_count"] += 1
            elif field in inferable_fields:
                row["inferred_fields"][field] += 1
        if len(row["samples"]) < 5:
            row["samples"].append(
                {
                    "global_id": item.get("global_id"),
                    "name": item.get("name"),
                    "proposal": proposal,
                    "confidence": item.get("confidence"),
                }
            )

    return {
        cls: {
            "count": data["count"],
            "missing_fields": dict(data["missing_fields"]),
            "inferred_fields": dict(data["inferred_fields"]),
            "needs_product_data_count": data["needs_product_data_count"],
            "samples": data["samples"],
        }
        for cls, data in sorted(grouped.items(), key=lambda item: (-item[1]["count"], item[0]))
    }


def get_proxy_candidate_summary(proxy_proposal_path: str | Path) -> dict[str, Any] | None:
    """Read proxy proposal groups created by the existing proxy analyzer."""
    if not proxy_proposal_path:
        return None
    path = Path(proxy_proposal_path)
    if not path.exists():
        return {"error": "proxy_reclassification_not_found", "path": str(path)}
    try:
        groups = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"error": "proxy_reclassification_parse_failed", "path": str(path), "message": str(exc)}
    actions = Counter(group.get("recommended_action") for group in groups)
    targets = Counter(group.get("target_ifc_class") for group in groups if group.get("target_ifc_class"))
    return {
        "group_count": len(groups),
        "proxy_count": sum(int(group.get("count") or 0) for group in groups),
        "actions": dict(actions),
        "target_classes": dict(targets.most_common()),
        "groups": [
            {
                "pattern": group.get("pattern"),
                "count": group.get("count"),
                "recommended_action": group.get("recommended_action"),
                "target_ifc_class": group.get("target_ifc_class"),
                "confidence": group.get("confidence"),
                "rationale": group.get("rationale"),
            }
            for group in groups[:20]
        ],
    }


def _select_run(store: ValidationStore, path: Path, run_id: str | None) -> dict[str, Any] | None:
    runs = store.list_runs(path, limit=100, include_result=True)
    if run_id:
        for run in runs:
            if run.get("run_id") == run_id:
                return run
        return None
    return runs[0] if runs else None


def _cluster_issues(issues: list[dict[str, Any]], max_issues_per_cluster: int) -> list[dict[str, Any]]:
    clusters: dict[str, dict[str, Any]] = {}
    for issue in issues:
        key_parts = [issue.get("category"), issue.get("rule_id"), issue.get("ifc_class"), issue.get("field")]
        key = ":".join(str(part or "*") for part in key_parts)
        if key not in clusters:
            clusters[key] = {
                "cluster_id": key,
                "category": issue.get("category"),
                "rule_id": issue.get("rule_id"),
                "rule_name": issue.get("rule_name"),
                "ifc_class": issue.get("ifc_class"),
                "field": issue.get("field"),
                "severity": issue.get("severity"),
                "count": 0,
                "storeys": set(),
                "spaces": set(),
                "messages": Counter(),
                "rep_elements": [],
            }
        cluster = clusters[key]
        cluster["count"] += 1
        if issue.get("storey"):
            cluster["storeys"].add(issue["storey"])
        if issue.get("space"):
            cluster["spaces"].add(issue["space"])
        if issue.get("message"):
            cluster["messages"][issue["message"]] += 1
        if len(cluster["rep_elements"]) < max_issues_per_cluster:
            cluster["rep_elements"].append(
                {
                    "issue_id": issue.get("issue_id"),
                    "global_id": issue.get("global_id"),
                    "element_name": issue.get("element_name"),
                    "type_name": issue.get("type_name"),
                    "storey": issue.get("storey"),
                    "space": issue.get("space"),
                    "message": issue.get("message"),
                    "auto_fixable": bool(issue.get("auto_fixable")),
                    "approval_required": bool(issue.get("approval_required")),
                }
            )
    rows = []
    for cluster in clusters.values():
        cluster["storeys"] = sorted(cluster["storeys"])
        cluster["spaces"] = sorted(cluster["spaces"])
        cluster["top_messages"] = [message for message, _ in cluster.pop("messages").most_common(3)]
        rows.append(cluster)
    rows.sort(key=lambda item: (-int(item.get("count") or 0), str(item.get("category") or "")))
    return rows


def _artifact_paths(path: Path, audit_dir: str | Path | None, run: dict[str, Any], results: dict[str, Any]) -> dict[str, str]:
    base = Path(audit_dir) if audit_dir else Path(run.get("report_json_path") or path).parent
    if base == path.parent:
        base = path.parent / "corrected" / "audit"
    stem = path.stem
    candidates = {
        "gui_json": run.get("report_json_path"),
        "gui_html": run.get("report_html_path"),
        "ids_ifctester_json": base / f"{stem}_ids_ifctester_report.json",
        "ids_normalized_json": base / f"{stem}_ids_report.json",
        "ids_html": base / f"{stem}_ids_report.html",
        "ids_failures_csv": base / f"{stem}_ids_failures.csv",
        "cobie_proposals": base / "cobie_proposals.json",
        "proxy_reclassification": base / "proxy_reclassification_proposal.json",
        "bsdd_mapping_discovery": base / "bsdd_mapping_discovery.json",
    }
    ids_paths = ((results.get("ids") or {}).get("report_paths") or {}) if isinstance(results, dict) else {}
    for key, value in ids_paths.items():
        candidates[f"ids_{key}"] = value
    return {key: str(value) for key, value in candidates.items() if value and Path(value).exists()}


def _model_info(model: dict[str, Any]) -> dict[str, Any]:
    return {
        "file_path": model.get("file_path"),
        "file_name": model.get("file_name"),
        "schema": model.get("schema"),
        "project_name": model.get("project_name"),
        "site_name": model.get("site_name"),
        "building_name": model.get("building_name"),
        "entity_count": model.get("entity_count"),
        "element_count": model.get("element_count"),
    }


def _result_summary(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "overall_passed": result.get("overall_passed"),
        "checks_run": result.get("checks_run"),
        "checks_passed": result.get("checks_passed"),
        "checks_failed": result.get("checks_failed"),
        "total_issues": result.get("total_issues"),
        "errors": result.get("errors", []),
    }


def _check_summaries(results: dict[str, Any]) -> dict[str, Any]:
    summaries = {}
    for name, result in (results or {}).items():
        if isinstance(result, dict):
            summaries[name] = {
                "passed": result.get("passed"),
                "summary": result.get("summary"),
                "issue_count": _check_issue_count(name, result),
            }
    return summaries


def _check_issue_count(name: str, result: dict[str, Any]) -> int | None:
    if name == "proxy":
        return result.get("proxy_count")
    if name == "type":
        return result.get("untyped_count")
    if name == "spatial":
        return result.get("orphan_count")
    if name == "guid":
        return result.get("duplicate_count")
    if name == "ids":
        return result.get("total_checks_failed") or sum(int(item.get("failed_count") or 0) for item in result.get("failures", []) or [])
    if name == "schema":
        return len(result.get("errors", []) or [])
    return None


def _entity_failure_sample(entity: dict[str, Any]) -> dict[str, Any]:
    return {
        "global_id": entity.get("global_id") or entity.get("GlobalId"),
        "ifc_class": entity.get("ifc_class") or entity.get("class") or entity.get("type"),
        "name": entity.get("name"),
        "tag": entity.get("tag"),
        "type_name": entity.get("type_name"),
        "reason": entity.get("reason"),
    }


def _trim_pack(pack: dict[str, Any], max_chars: int) -> dict[str, Any]:
    """Keep the pack bounded while retaining root-cause useful evidence."""
    text = json.dumps(pack, default=str)
    if len(text) <= max_chars:
        return pack
    pack = json.loads(json.dumps(pack, default=str))
    pack.setdefault("trim_notes", []).append(f"Evidence pack trimmed from {len(text)} characters to target {max_chars}.")
    pack["issue_clusters"] = pack.get("issue_clusters", [])[:12]
    for cluster in pack.get("issue_clusters", []):
        cluster["rep_elements"] = cluster.get("rep_elements", [])[:1]
        cluster["storeys"] = cluster.get("storeys", [])[:10]
        cluster["spaces"] = cluster.get("spaces", [])[:10]
    ids = pack.get("ids_failure_summary") or {}
    ids["failed_requirements"] = ids.get("failed_requirements", [])[:10]
    for failure in ids.get("failed_requirements", []):
        failure["sample_failures"] = failure.get("sample_failures", [])[:2]
    if isinstance(pack.get("proxy_candidate_summary"), dict):
        pack["proxy_candidate_summary"]["groups"] = pack["proxy_candidate_summary"].get("groups", [])[:8]
    text = json.dumps(pack, default=str)
    if len(text) <= max_chars:
        return pack
    pack["trim_notes"].append("Secondary trim removed detailed COBie samples.")
    cobie = pack.get("cobie_gap_map")
    if isinstance(cobie, dict):
        for data in cobie.values():
            if isinstance(data, dict):
                data["samples"] = data.get("samples", [])[:1]
    text = json.dumps(pack, default=str)
    if len(text) <= max_chars:
        return pack
    pack["trim_notes"].append("Tertiary trim reduced artifact, proxy, and IDS details for LLM limits.")
    pack["artifact_paths"] = {key: value for key, value in (pack.get("artifact_paths") or {}).items() if key in {"gui_json", "gui_html", "ids_failures_csv"}}
    ids = pack.get("ids_failure_summary") or {}
    ids["failed_requirements"] = ids.get("failed_requirements", [])[:7]
    for failure in ids.get("failed_requirements", []):
        failure.pop("reason_counts", None)
        failure["sample_failures"] = failure.get("sample_failures", [])[:1]
    if isinstance(pack.get("proxy_candidate_summary"), dict):
        pack["proxy_candidate_summary"]["groups"] = pack["proxy_candidate_summary"].get("groups", [])[:5]
    pack["issue_clusters"] = pack.get("issue_clusters", [])[:10]
    for cluster in pack.get("issue_clusters", []):
        cluster["rep_elements"] = cluster.get("rep_elements", [])[:1]
    return pack
