"""Checker runner — orchestrates all check modules and aggregates results."""

import time
import ifcopenshell
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

from ifc_agent.checker import (
    schema_check,
    ids_check,
    spatial_check,
    guid_check,
    proxy_check,
    type_check,
)


ALL_CHECKS = {
    "schema": schema_check,
    "ids": ids_check,
    "spatial": spatial_check,
    "guid": guid_check,
    "proxy": proxy_check,
    "type": type_check,
}


@dataclass
class CheckerReport:
    """Aggregated report from all check modules."""
    file_path: str = ""
    timestamp: str = ""
    duration_seconds: float = 0.0
    overall_passed: bool = True
    checks_run: int = 0
    checks_passed: int = 0
    checks_failed: int = 0
    total_issues: int = 0
    results: dict = field(default_factory=dict)
    errors: list = field(default_factory=list)

    @property
    def telegram_summary(self) -> str:
        """One-line summary suitable for Telegram."""
        parts = []
        for name, result in self.results.items():
            r = result.to_dict()
            status = "✓" if r["passed"] else "✗"
            parts.append(f"{status} {name}")

        status_line = " | ".join(parts)
        emoji = "✅" if self.overall_passed else "❌"
        return (
            f"{emoji} IFC Check: {self.checks_passed}/{self.checks_run} passed\n"
            f"{status_line}\n"
            f"Issues: {self.total_issues} | Time: {self.duration_seconds:.1f}s"
        )

    def to_dict(self) -> dict:
        return {
            "file_path": self.file_path,
            "timestamp": self.timestamp,
            "duration_seconds": self.duration_seconds,
            "overall_passed": self.overall_passed,
            "checks_run": self.checks_run,
            "checks_passed": self.checks_passed,
            "checks_failed": self.checks_failed,
            "total_issues": self.total_issues,
            "results": {k: v.to_dict() for k, v in self.results.items()},
            "errors": self.errors,
        }


def run_all(
    file_path: str | Path,
    checks: Optional[list[str]] = None,
    ids_path: Optional[str | Path] = None,
    additional_files: Optional[list[str | Path]] = None,
    output_dir: Optional[str | Path] = None,
) -> CheckerReport:
    """Run all (or selected) checker modules on an IFC file.

    Args:
        file_path: Path to the IFC file to check.
        checks: List of check names to run. None = all checks.
        ids_path: Path to IDS XML for the ids check.
        additional_files: Extra IFC files for cross-file GUID check.
        output_dir: Output directory for reports.

    Returns:
        CheckerReport with aggregated results.
    """
    file_path = Path(file_path)
    report = CheckerReport(
        file_path=str(file_path),
        timestamp=time.strftime("%Y-%m-%dT%H:%M:%S"),
    )

    if not file_path.exists():
        report.overall_passed = False
        report.errors.append({"type": "file_not_found", "message": str(file_path)})
        return report

    start_time = time.time()

    # Determine which checks to run
    if checks is None:
        checks_to_run = list(ALL_CHECKS.keys())
    else:
        checks_to_run = [c for c in checks if c in ALL_CHECKS]
        unknown_checks = [c for c in checks if c not in ALL_CHECKS]
        for check_name in unknown_checks:
            report.errors.append({
                "type": "unknown_check",
                "check": check_name,
                "message": f"Unknown check '{check_name}'. Available checks: {', '.join(ALL_CHECKS)}",
            })

    # Pre-load model once for checks that accept it (avoid re-opening)
    model = None
    if any(c in checks_to_run for c in ["spatial", "guid", "proxy", "type"]):
        try:
            model = ifcopenshell.open(str(file_path))
        except Exception as e:
            report.errors.append({"type": "ifc_parse_error", "message": str(e)})
            # Schema check will catch this too, so continue

    # Run each check
    for check_name in checks_to_run:
        try:
            if check_name == "schema":
                result = schema_check.run(file_path)
            elif check_name == "ids":
                result = ids_check.run(
                    file_path,
                    ids_path=ids_path,
                    output_dir=output_dir,
                    write_reports=output_dir is not None,
                )
            elif check_name == "spatial":
                result = spatial_check.run(file_path, model=model)
            elif check_name == "guid":
                result = guid_check.run(
                    file_path, model=model, additional_files=additional_files
                )
            elif check_name == "proxy":
                result = proxy_check.run(file_path, model=model)
            elif check_name == "type":
                result = type_check.run(file_path, model=model)
            else:
                continue

            report.results[check_name] = result
            report.checks_run += 1

            result_dict = result.to_dict()
            if result_dict["passed"]:
                report.checks_passed += 1
            else:
                report.checks_failed += 1

            # Count individual issues
            if check_name == "spatial":
                report.total_issues += result.orphan_count
            elif check_name == "guid":
                report.total_issues += result.duplicate_count + len(result.cross_file_collisions)
            elif check_name == "proxy":
                report.total_issues += result.proxy_count
            elif check_name == "type":
                report.total_issues += result.untyped_count
            elif check_name == "ids":
                entity_failures = sum(len(failure.get("failed_entities", [])) for failure in getattr(result, "failures", []))
                report.total_issues += entity_failures or getattr(result, "total_checks_failed", 0) or result.specs_failed

        except Exception as e:
            report.errors.append({
                "type": "check_error",
                "check": check_name,
                "message": str(e),
            })

    report.duration_seconds = round(time.time() - start_time, 2)
    report.overall_passed = report.checks_failed == 0 and len(report.errors) == 0

    return report
