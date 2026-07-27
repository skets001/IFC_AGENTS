"""Check 1.2 — IDS-based property validation.

Validates an IFC model against IDS (Information Delivery Specification) XML files
using the ifctester library.
"""

import csv
import json
from html import escape
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

import ifcopenshell

try:
    from ifctester import ids as ids_module
    from ifctester import reporter
    HAS_IFCTESTER = True
except ImportError:
    HAS_IFCTESTER = False


@dataclass
class IdsCheckResult:
    """Result of IDS validation check."""
    passed: bool = True
    specs_checked: int = 0
    specs_passed: int = 0
    specs_failed: int = 0
    total_checks: int = 0
    total_checks_passed: int = 0
    total_checks_failed: int = 0
    total_requirements: int = 0
    total_requirements_failed: int = 0
    failures: list = field(default_factory=list)
    specifications: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    report_errors: list = field(default_factory=list)
    ids_file: str = ""
    report_paths: dict = field(default_factory=dict)

    @property
    def summary(self) -> str:
        if not HAS_IFCTESTER:
            return "IDS check SKIPPED — ifctester not installed"
        if self.specs_checked == 0:
            if self.errors:
                return "IDS SKIPPED — no applicable specs found"
            return "IDS OK — no specs to check"
        if self.passed:
            return f"IDS OK — {self.specs_passed}/{self.specs_checked} specs passed"
        return f"IDS FAILED — {self.specs_failed}/{self.specs_checked} specs failed"

    def to_dict(self) -> dict:
        return {
            "check": "ids",
            "passed": self.passed,
            "specs_checked": self.specs_checked,
            "specs_passed": self.specs_passed,
            "specs_failed": self.specs_failed,
            "total_checks": self.total_checks,
            "total_checks_passed": self.total_checks_passed,
            "total_checks_failed": self.total_checks_failed,
            "total_requirements": self.total_requirements,
            "total_requirements_failed": self.total_requirements_failed,
            "failures": self.failures,
            "specifications": self.specifications,
            "errors": self.errors,
            "report_errors": self.report_errors,
            "ids_file": self.ids_file,
            "report_paths": self.report_paths,
            "summary": self.summary,
        }


def run(
    file_path: str | Path,
    ids_path: Optional[str | Path] = None,
    output_dir: Optional[str | Path] = None,
    write_reports: bool = False,
) -> IdsCheckResult:
    """Validate IFC model against an IDS specification.

    Args:
        file_path: Path to the IFC file.
        ids_path: Path to the IDS XML file. If None, uses baseline.ids from rules/.
        output_dir: Directory for report output. If None, uses reports/.
        write_reports: Generate IDS HTML/BCF report files.
    """
    result = IdsCheckResult()

    if not HAS_IFCTESTER:
        result.passed = True  # skip, don't fail
        result.errors.append({
            "type": "missing_dependency",
            "message": "ifctester not installed. Run: pip install ifctester",
        })
        return result

    # Resolve paths
    file_path = Path(file_path)
    if ids_path is None:
        ids_path = Path(__file__).parent.parent.parent.parent / "rules" / "baseline.ids"
    else:
        ids_path = Path(ids_path)

    if output_dir is None:
        output_dir = Path(__file__).parent.parent.parent.parent / "reports"
    output_dir = Path(output_dir)

    result.ids_file = str(ids_path)

    if not ids_path.exists():
        result.errors.append({
            "type": "ids_not_found",
            "message": f"IDS file not found: {ids_path}",
        })
        result.passed = True  # skip, don't fail
        return result

    # Load IDS
    try:
        specs = ids_module.open(str(ids_path))
    except Exception as e:
        result.passed = False
        result.errors.append({
            "type": "ids_parse_error",
            "message": f"Failed to parse IDS file: {e}",
        })
        return result

    # Load IFC model
    try:
        model = ifcopenshell.open(str(file_path))
    except Exception as e:
        result.passed = False
        result.errors.append({
            "type": "ifc_parse_error",
            "message": f"Failed to open IFC file: {e}",
        })
        return result

    # Validate
    try:
        specs.validate(model)
    except Exception as e:
        result.passed = False
        result.errors.append({
            "type": "validation_error",
            "message": f"Validation failed: {e}",
        })
        return result

    # Use IfcTester JSON as the source of truth. Its model mirrors the
    # official reports and includes per-requirement failure reasons.
    try:
        json_reporter = reporter.Json(specs)
        ids_report = json_reporter.report()
    except Exception as e:
        result.passed = False
        result.errors.append({
            "type": "ids_report_error",
            "message": f"Failed to build IDS report data: {e}",
        })
        return result

    _populate_from_ifctester_report(result, ids_report)

    # If no specs were checked, this is not a failure — just no applicable rules
    if result.specs_checked == 0:
        result.passed = True

    if write_reports:
        output_dir.mkdir(parents=True, exist_ok=True)
        stem = file_path.stem
        _write_report_output(result, "ifctester_json", output_dir / f"{stem}_ids_ifctester_report.json", lambda p: json_reporter.to_file(str(p)))
        _write_report_output(result, "html", output_dir / f"{stem}_ids_report.html", lambda p: _write_ifctester_report(reporter.Html, specs, p))
        _write_report_output(result, "csv", output_dir / f"{stem}_ids_failures.csv", lambda p: _write_failure_csv(result, p))
        _write_report_output(result, "summary_html", output_dir / f"{stem}_ids_summary.html", lambda p: _write_ids_summary_html(result, p, file_path))
        _write_report_output(result, "ods", output_dir / f"{stem}_ids_report.ods", lambda p: _write_ifctester_report(reporter.Ods, specs, p))
        _write_normalized_json_report(result, output_dir / f"{stem}_ids_report.json")

    return result


def inspect_ids(ids_path: str | Path) -> dict:
    """Open an IDS file and return schema/specification metadata."""
    path = Path(ids_path)
    if not path.exists():
        return {"ok": False, "ids_file": str(path), "error": f"IDS file not found: {path}"}
    if not HAS_IFCTESTER:
        return {"ok": False, "ids_file": str(path), "error": "ifctester is not installed"}
    try:
        specs = ids_module.open(str(path))
    except Exception as exc:
        return {"ok": False, "ids_file": str(path), "error": str(exc)}
    return {
        "ok": True,
        "ids_file": str(path),
        "title": specs.info.get("title", "Untitled IDS"),
        "description": specs.info.get("description", ""),
        "specification_count": len(specs.specifications),
        "specifications": [
            {
                "name": spec.name,
                "description": getattr(spec, "description", ""),
                "instructions": getattr(spec, "instructions", ""),
                "applicability": [facet.to_string("applicability") for facet in spec.applicability],
                "requirements": [facet.to_string("requirement", spec, facet) for facet in spec.requirements],
            }
            for spec in specs.specifications
        ],
    }


def _populate_from_ifctester_report(result: IdsCheckResult, ids_report: dict) -> None:
    result.passed = bool(ids_report.get("status", False))
    result.specs_checked = int(ids_report.get("total_specifications") or 0)
    result.specs_passed = int(ids_report.get("total_specifications_pass") or 0)
    result.specs_failed = int(ids_report.get("total_specifications_fail") or 0)
    result.total_requirements = int(ids_report.get("total_requirements") or 0)
    result.total_requirements_failed = int(ids_report.get("total_requirements_fail") or 0)
    result.total_checks = int(ids_report.get("total_checks") or 0)
    result.total_checks_passed = int(ids_report.get("total_checks_pass") or 0)
    result.total_checks_failed = int(ids_report.get("total_checks_fail") or 0)

    for spec in ids_report.get("specifications", []):
        spec_summary = {
            "name": spec.get("name"),
            "description": spec.get("description"),
            "status": spec.get("status"),
            "cardinality": spec.get("cardinality"),
            "is_skipped": spec.get("is_skipped"),
            "is_ifc_version": spec.get("is_ifc_version"),
            "total_applicable": spec.get("total_applicable"),
            "total_checks": spec.get("total_checks"),
            "total_checks_failed": spec.get("total_checks_fail"),
            "percent_checks_pass": spec.get("percent_checks_pass"),
        }
        result.specifications.append(spec_summary)

        if spec.get("status"):
            continue
        for req in spec.get("requirements", []):
            if req.get("status"):
                continue
            failed_entities = [_failure_entity(entity) for entity in req.get("failed_entities", [])]
            result.failures.append({
                "spec_name": spec.get("name", "unnamed"),
                "requirement": req.get("label") or req.get("description") or req.get("facet_type"),
                "facet_type": req.get("facet_type"),
                "description": req.get("description", ""),
                "failed_count": int(req.get("total_fail") or len(failed_entities)),
                "total_applicable": req.get("total_applicable"),
                "percent_pass": req.get("percent_pass"),
                "failed_entities": failed_entities,
            })


def _failure_entity(entity: dict) -> dict:
    element_type = entity.get("element_type")
    return {
        "global_id": entity.get("global_id") or "N/A",
        "name": entity.get("name") or "",
        "ifc_class": entity.get("class") or "N/A",
        "tag": entity.get("tag") or "",
        "element_id": entity.get("id"),
        "type_name": getattr(element_type, "Name", None) if element_type is not None else None,
        "reason": entity.get("reason") or "Requirement failed",
    }


def _write_report_output(result: IdsCheckResult, key: str, path: Path, writer) -> None:
    try:
        writer(path)
        if path.exists() and path.stat().st_size > 0:
            result.report_paths[key] = str(path)
        else:
            result.report_errors.append({"report": key, "path": str(path), "message": "Report file was not created or is empty"})
    except Exception as exc:
        result.report_errors.append({"report": key, "path": str(path), "message": str(exc)})


def _write_ifctester_report(reporter_cls, specs, path: Path) -> None:
    report = reporter_cls(specs)
    report.report()
    report.to_file(str(path))


def _write_normalized_json_report(result: IdsCheckResult, path: Path) -> None:
    try:
        result.report_paths["json"] = str(path)
        path.write_text(json.dumps(result.to_dict(), indent=2, default=str), encoding="utf-8")
        if not path.exists() or path.stat().st_size == 0:
            result.report_paths.pop("json", None)
            result.report_errors.append({"report": "json", "path": str(path), "message": "Report file was not created or is empty"})
    except Exception as exc:
        result.report_paths.pop("json", None)
        result.report_errors.append({"report": "json", "path": str(path), "message": str(exc)})


def _iter_failure_rows(result: IdsCheckResult):
    for failure in result.failures:
        entities = failure.get("failed_entities") or []
        if not entities:
            yield {
                "spec_name": failure.get("spec_name"),
                "requirement": failure.get("requirement"),
                "ifc_class": "",
                "global_id": "",
                "name": "",
                "tag": "",
                "reason": failure.get("description", "Requirement failed"),
            }
        for entity in entities:
            yield {
                "spec_name": failure.get("spec_name"),
                "requirement": failure.get("requirement"),
                "ifc_class": entity.get("ifc_class"),
                "global_id": entity.get("global_id"),
                "name": entity.get("name"),
                "tag": entity.get("tag"),
                "reason": entity.get("reason"),
            }


def _write_failure_csv(result: IdsCheckResult, path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        fieldnames = ["spec_name", "requirement", "ifc_class", "global_id", "name", "tag", "reason"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(_iter_failure_rows(result))


def _write_ids_summary_html(result: IdsCheckResult, path: Path, file_path: Path) -> None:
    rows = []
    for row in _iter_failure_rows(result):
        rows.append(
            "<tr>"
            f"<td>{escape(str(row.get('spec_name') or ''))}</td>"
            f"<td>{escape(str(row.get('requirement') or ''))}</td>"
            f"<td>{escape(str(row.get('ifc_class') or ''))}</td>"
            f"<td><code>{escape(str(row.get('global_id') or ''))}</code></td>"
            f"<td>{escape(str(row.get('name') or ''))}</td>"
            f"<td>{escape(str(row.get('reason') or ''))}</td>"
            "</tr>"
        )
    rows_html = "\n".join(rows) or "<tr><td colspan='6'>No IDS failures.</td></tr>"
    html = f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>IDS Summary - {escape(file_path.name)}</title>
<style>body{{font-family:Segoe UI,Arial,sans-serif;margin:24px;color:#111827}}table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #d1d5db;padding:8px;vertical-align:top}}th{{background:#f3f4f6;text-align:left}}code{{font-family:Cascadia Code,monospace}}.fail{{color:#b91c1c;font-weight:700}}</style></head>
<body><h1>IDS Validation Summary</h1><p><strong>IFC:</strong> {escape(str(file_path))}</p><p><strong>IDS:</strong> {escape(result.ids_file)}</p><p class="fail">{escape(result.summary)} - {result.total_checks_failed} failed checks</p><table><thead><tr><th>Specification</th><th>Requirement</th><th>Class</th><th>GlobalId</th><th>Name</th><th>Reason</th></tr></thead><tbody>{rows_html}</tbody></table></body></html>"""
    path.write_text(html, encoding="utf-8")
