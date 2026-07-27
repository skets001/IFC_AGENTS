"""SQLite-backed validation runs, issue records, and IFC element index."""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Iterable, Optional


def model_id_for_path(path: str | Path) -> str:
    resolved = str(Path(path).resolve()) if Path(path).exists() else str(path)
    return str(uuid.uuid5(uuid.NAMESPACE_URL, resolved))


class ValidationStore:
    """Small persistence layer for MVP validation workflows."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript(
                """
                PRAGMA journal_mode=WAL;

                CREATE TABLE IF NOT EXISTS models (
                    model_id TEXT PRIMARY KEY,
                    file_path TEXT NOT NULL UNIQUE,
                    file_name TEXT NOT NULL,
                    file_size INTEGER,
                    file_mtime INTEGER,
                    schema TEXT,
                    project_name TEXT,
                    site_name TEXT,
                    building_name TEXT,
                    entity_count INTEGER,
                    element_count INTEGER,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    indexed_at TEXT
                );

                CREATE TABLE IF NOT EXISTS elements (
                    model_id TEXT NOT NULL,
                    global_id TEXT NOT NULL,
                    ifc_id INTEGER,
                    ifc_class TEXT NOT NULL,
                    name TEXT,
                    tag TEXT,
                    object_type TEXT,
                    predefined_type TEXT,
                    type_global_id TEXT,
                    type_name TEXT,
                    storey TEXT,
                    space TEXT,
                    systems_json TEXT NOT NULL DEFAULT '[]',
                    classifications_json TEXT NOT NULL DEFAULT '[]',
                    documents_json TEXT NOT NULL DEFAULT '[]',
                    property_sets_json TEXT NOT NULL DEFAULT '[]',
                    relationships_json TEXT NOT NULL DEFAULT '{}',
                    indexed_at TEXT NOT NULL,
                    PRIMARY KEY (model_id, global_id),
                    FOREIGN KEY(model_id) REFERENCES models(model_id)
                );

                CREATE TABLE IF NOT EXISTS validation_runs (
                    run_id TEXT PRIMARY KEY,
                    model_id TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    ids_path TEXT,
                    checks_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    duration_seconds REAL,
                    checks_run INTEGER,
                    checks_passed INTEGER,
                    checks_failed INTEGER,
                    total_issues INTEGER,
                    report_json_path TEXT,
                    report_html_path TEXT,
                    reports_json TEXT NOT NULL DEFAULT '{}',
                    result_json TEXT NOT NULL DEFAULT '{}',
                    FOREIGN KEY(model_id) REFERENCES models(model_id)
                );

                CREATE TABLE IF NOT EXISTS issues (
                    issue_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    model_id TEXT NOT NULL,
                    rule_id TEXT NOT NULL,
                    rule_name TEXT,
                    category TEXT NOT NULL,
                    status TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    global_id TEXT,
                    ifc_class TEXT,
                    element_name TEXT,
                    type_name TEXT,
                    storey TEXT,
                    space TEXT,
                    problem_type TEXT,
                    field TEXT,
                    message TEXT NOT NULL,
                    evidence_json TEXT NOT NULL DEFAULT '{}',
                    suggested_fix_json TEXT NOT NULL DEFAULT '{}',
                    auto_fixable INTEGER NOT NULL DEFAULT 0,
                    approval_required INTEGER NOT NULL DEFAULT 0,
                    source TEXT NOT NULL DEFAULT 'checker',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(run_id) REFERENCES validation_runs(run_id),
                    FOREIGN KEY(model_id) REFERENCES models(model_id)
                );

                CREATE INDEX IF NOT EXISTS idx_elements_class ON elements(model_id, ifc_class);
                CREATE INDEX IF NOT EXISTS idx_elements_name ON elements(model_id, name);
                CREATE INDEX IF NOT EXISTS idx_runs_model ON validation_runs(model_id, started_at DESC);
                CREATE INDEX IF NOT EXISTS idx_issues_run ON issues(run_id);
                CREATE INDEX IF NOT EXISTS idx_issues_model ON issues(model_id);
                CREATE INDEX IF NOT EXISTS idx_issues_class ON issues(model_id, ifc_class);
                CREATE INDEX IF NOT EXISTS idx_issues_category ON issues(run_id, category);
                CREATE INDEX IF NOT EXISTS idx_issues_global_id ON issues(model_id, global_id);
                """
            )
            columns = {row[1] for row in conn.execute("PRAGMA table_info(models)").fetchall()}
            if "file_mtime" not in columns:
                conn.execute("ALTER TABLE models ADD COLUMN file_mtime INTEGER")

    def upsert_model(self, metadata: dict[str, Any]) -> str:
        now = _now()
        model_id = metadata.get("model_id") or model_id_for_path(metadata["file_path"])
        with self.connect() as conn:
            existing = conn.execute("SELECT created_at FROM models WHERE model_id = ?", (model_id,)).fetchone()
            conn.execute(
                """
                INSERT OR REPLACE INTO models (
                    model_id, file_path, file_name, file_size, file_mtime, schema, project_name, site_name,
                    building_name, entity_count, element_count, metadata_json, created_at, updated_at, indexed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    model_id,
                    metadata["file_path"],
                    metadata.get("file_name") or Path(metadata["file_path"]).name,
                    metadata.get("file_size"),
                    metadata.get("file_mtime"),
                    metadata.get("schema"),
                    metadata.get("project_name"),
                    metadata.get("site_name"),
                    metadata.get("building_name"),
                    metadata.get("entity_count"),
                    metadata.get("element_count"),
                    _json(metadata),
                    existing["created_at"] if existing else now,
                    now,
                    metadata.get("indexed_at"),
                ),
            )
        return model_id

    def replace_elements(self, model_id: str, elements: Iterable[dict[str, Any]]) -> int:
        now = _now()
        rows = list(elements)
        with self.connect() as conn:
            conn.execute("DELETE FROM elements WHERE model_id = ?", (model_id,))
            conn.executemany(
                """
                INSERT INTO elements (
                    model_id, global_id, ifc_id, ifc_class, name, tag, object_type, predefined_type,
                    type_global_id, type_name, storey, space, systems_json, classifications_json,
                    documents_json, property_sets_json, relationships_json, indexed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        model_id,
                        row["global_id"],
                        row.get("ifc_id"),
                        row.get("ifc_class"),
                        row.get("name"),
                        row.get("tag"),
                        row.get("object_type"),
                        row.get("predefined_type"),
                        row.get("type_global_id"),
                        row.get("type_name"),
                        row.get("storey"),
                        row.get("space"),
                        _json(row.get("systems", [])),
                        _json(row.get("classifications", [])),
                        _json(row.get("documents", [])),
                        _json(row.get("property_sets", [])),
                        _json(row.get("relationships", {})),
                        now,
                    )
                    for row in rows
                    if row.get("global_id")
                ],
            )
            conn.execute("UPDATE models SET element_count = ?, indexed_at = ?, updated_at = ? WHERE model_id = ?", (len(rows), now, now, model_id))
        return len(rows)

    def get_model_by_path(self, file_path: str | Path) -> Optional[dict[str, Any]]:
        path = str(Path(file_path))
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM models WHERE file_path = ?", (path,)).fetchone()
        return _row_to_dict(row) if row else None

    def get_model(self, model_id: str) -> Optional[dict[str, Any]]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM models WHERE model_id = ?", (model_id,)).fetchone()
        return _row_to_dict(row) if row else None

    def create_validation_run(
        self,
        model_id: str,
        file_path: str | Path,
        checks: list[str],
        ids_path: str | None,
        report: Any,
        report_paths: dict[str, str],
    ) -> str:
        run_id = str(uuid.uuid4())
        data = report.to_dict() if hasattr(report, "to_dict") else dict(report)
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO validation_runs (
                    run_id, model_id, file_path, ids_path, checks_json, status, started_at, completed_at,
                    duration_seconds, checks_run, checks_passed, checks_failed, total_issues,
                    report_json_path, report_html_path, reports_json, result_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    model_id,
                    str(file_path),
                    ids_path,
                    _json(checks),
                    "completed" if not data.get("errors") else "completed_with_warnings",
                    data.get("timestamp") or _now(),
                    _now(),
                    data.get("duration_seconds"),
                    data.get("checks_run"),
                    data.get("checks_passed"),
                    data.get("checks_failed"),
                    data.get("total_issues"),
                    report_paths.get("json"),
                    report_paths.get("html"),
                    _json(report_paths),
                    _json(data),
                ),
            )
        return run_id

    def replace_issues(self, run_id: str, model_id: str, issues: Iterable[dict[str, Any]]) -> int:
        rows = list(issues)
        now = _now()
        with self.connect() as conn:
            conn.execute("DELETE FROM issues WHERE run_id = ?", (run_id,))
            conn.executemany(
                """
                INSERT INTO issues (
                    issue_id, run_id, model_id, rule_id, rule_name, category, status, severity,
                    global_id, ifc_class, element_name, type_name, storey, space, problem_type,
                    field, message, evidence_json, suggested_fix_json, auto_fixable,
                    approval_required, source, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [self._issue_row(run_id, model_id, idx, row, now) for idx, row in enumerate(rows, start=1)],
            )
        return len(rows)

    def list_runs(self, file_path: str | Path | None = None, limit: int = 50, include_result: bool = False) -> list[dict[str, Any]]:
        query = "SELECT * FROM validation_runs"
        params: list[Any] = []
        if file_path:
            query += " WHERE file_path = ?"
            params.append(str(Path(file_path)))
        query += " ORDER BY started_at DESC LIMIT ?"
        params.append(limit)
        with self.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [_decode_run(row, include_result=include_result) for row in rows]

    def list_issues(
        self,
        issue_id: str | None = None,
        run_id: str | None = None,
        model_id: str | None = None,
        category: str | None = None,
        severity: str | None = None,
        ifc_class: str | None = None,
        status: str | None = None,
        limit: int = 500,
        offset: int = 0,
        include_evidence: bool = False,
    ) -> dict[str, Any]:
        where = []
        params: list[Any] = []
        for column, value in [("i.issue_id", issue_id), ("i.run_id", run_id), ("i.model_id", model_id), ("i.category", category), ("i.severity", severity), ("i.ifc_class", ifc_class), ("i.status", status)]:
            if value:
                where.append(f"{column} = ?")
                params.append(value)
        where_sql = f" WHERE {' AND '.join(where)}" if where else ""
        from_sql = "issues i LEFT JOIN elements e ON e.model_id = i.model_id AND e.global_id = i.global_id"
        columns = "i.*, e.ifc_id AS ifc_id, e.tag AS indexed_tag" if include_evidence else ", ".join(
            [
                "i.issue_id AS issue_id",
                "i.run_id AS run_id",
                "i.model_id AS model_id",
                "i.rule_id AS rule_id",
                "i.rule_name AS rule_name",
                "i.category AS category",
                "i.status AS status",
                "i.severity AS severity",
                "i.global_id AS global_id",
                "i.ifc_class AS ifc_class",
                "i.element_name AS element_name",
                "i.type_name AS type_name",
                "COALESCE(i.storey, e.storey) AS storey",
                "COALESCE(i.space, e.space) AS space",
                "e.ifc_id AS ifc_id",
                "e.tag AS indexed_tag",
                "i.problem_type AS problem_type",
                "i.field AS field",
                "i.message AS message",
                "i.suggested_fix_json AS suggested_fix_json",
                "i.auto_fixable AS auto_fixable",
                "i.approval_required AS approval_required",
                "i.source AS source",
                "i.created_at AS created_at",
            ]
        )
        with self.connect() as conn:
            total = conn.execute(f"SELECT COUNT(*) AS count FROM {from_sql}{where_sql}", params).fetchone()["count"]
            rows = conn.execute(
                f"SELECT {columns} FROM {from_sql}{where_sql} ORDER BY i.severity DESC, i.category, i.issue_id LIMIT ? OFFSET ?",
                [*params, limit, offset],
            ).fetchall()
        return {"total": total, "limit": limit, "offset": offset, "issues": [_decode_issue(row, include_evidence=include_evidence) for row in rows]}

    def list_elements(self, model_id: str, ifc_class: str | None = None, search: str = "", limit: int = 500, offset: int = 0) -> dict[str, Any]:
        where = ["model_id = ?"]
        params: list[Any] = [model_id]
        if ifc_class:
            where.append("ifc_class = ?")
            params.append(ifc_class)
        if search:
            where.append("(global_id LIKE ? OR name LIKE ? OR tag LIKE ? OR ifc_class LIKE ?)")
            needle = f"%{search}%"
            params.extend([needle, needle, needle, needle])
        where_sql = " WHERE " + " AND ".join(where)
        with self.connect() as conn:
            total = conn.execute(f"SELECT COUNT(*) AS count FROM elements{where_sql}", params).fetchone()["count"]
            rows = conn.execute(
                f"SELECT * FROM elements{where_sql} ORDER BY ifc_class, name LIMIT ? OFFSET ?",
                [*params, limit, offset],
            ).fetchall()
        return {"total": total, "limit": limit, "offset": offset, "elements": [_decode_element(row) for row in rows]}

    def list_element_classes(self, model_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT ifc_class, COUNT(*) AS count
                FROM elements
                WHERE model_id = ?
                GROUP BY ifc_class
                ORDER BY count DESC, ifc_class
                """,
                (model_id,),
            ).fetchall()
        return [{"ifc_class": row["ifc_class"], "count": row["count"]} for row in rows]

    def get_element(self, model_id: str, global_id: str) -> Optional[dict[str, Any]]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM elements WHERE model_id = ? AND global_id = ?", (model_id, global_id)).fetchone()
        return _decode_element(row) if row else None

    def _issue_row(self, run_id: str, model_id: str, idx: int, row: dict[str, Any], now: str) -> tuple[Any, ...]:
        issue_key = f"{run_id}:{idx}:{row.get('rule_id')}:{row.get('global_id')}"
        issue_id = row.get("issue_id") or f"ISSUE-{uuid.uuid5(uuid.NAMESPACE_URL, issue_key).hex[:12].upper()}"
        return (
            issue_id,
            run_id,
            model_id,
            row.get("rule_id") or "UNKNOWN",
            row.get("rule_name"),
            row.get("category") or "general",
            row.get("status") or "detected",
            row.get("severity") or "medium",
            row.get("global_id"),
            row.get("ifc_class"),
            row.get("element_name"),
            row.get("type_name"),
            row.get("storey"),
            row.get("space"),
            row.get("problem_type"),
            row.get("field"),
            row.get("message") or "Validation issue",
            _json(row.get("evidence", {})),
            _json(row.get("suggested_fix", {})),
            1 if row.get("auto_fixable") else 0,
            1 if row.get("approval_required") else 0,
            row.get("source") or "checker",
            now,
        )


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, default=str, ensure_ascii=False)


def _loads(value: str, fallback: Any) -> Any:
    try:
        return json.loads(value) if value else fallback
    except json.JSONDecodeError:
        return fallback


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    if "metadata_json" in data:
        data["metadata"] = _loads(data.pop("metadata_json"), {})
    return data


def _decode_run(row: sqlite3.Row, include_result: bool = False) -> dict[str, Any]:
    data = dict(row)
    data["checks"] = _loads(data.pop("checks_json"), [])
    data["reports"] = _loads(data.pop("reports_json"), {})
    result = _loads(data.pop("result_json"), {})
    if include_result:
        data["result"] = result
    else:
        data["result_summary"] = {
            "overall_passed": result.get("overall_passed"),
            "checks_run": result.get("checks_run"),
            "checks_passed": result.get("checks_passed"),
            "checks_failed": result.get("checks_failed"),
            "total_issues": result.get("total_issues"),
            "errors": result.get("errors", []),
        }
    return data


def _decode_issue(row: sqlite3.Row, include_evidence: bool = False) -> dict[str, Any]:
    data = dict(row)
    evidence = _loads(data.pop("evidence_json"), {}) if "evidence_json" in data else {}
    if include_evidence:
        data["evidence"] = evidence
    else:
        data["evidence_summary"] = _evidence_summary(evidence)
    data["suggested_fix"] = _loads(data.pop("suggested_fix_json"), {})
    data["auto_fixable"] = bool(data["auto_fixable"])
    data["approval_required"] = bool(data["approval_required"])
    return data


def _evidence_summary(evidence: Any) -> dict[str, Any]:
    if not isinstance(evidence, dict):
        return {}
    summary = {key: evidence.get(key) for key in ["kind", "ids_file", "spec_name", "requirement", "failed_count", "total_applicable"] if evidence.get(key) is not None}
    report_paths = evidence.get("report_paths")
    if isinstance(report_paths, dict) and report_paths:
        summary["report_keys"] = sorted(report_paths)
    entity = evidence.get("entity")
    if isinstance(entity, dict):
        summary["reason"] = entity.get("reason")
    return summary


def _decode_element(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["systems"] = _loads(data.pop("systems_json"), [])
    data["classifications"] = _loads(data.pop("classifications_json"), [])
    data["documents"] = _loads(data.pop("documents_json"), [])
    data["property_sets"] = _loads(data.pop("property_sets_json"), [])
    data["relationships"] = _loads(data.pop("relationships_json"), {})
    return data
