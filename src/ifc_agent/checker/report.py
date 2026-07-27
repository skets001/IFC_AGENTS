"""Report generator — outputs checker results in HTML, JSON, and summary formats."""

import json
from html import escape
from pathlib import Path
from datetime import datetime


def to_json(report, output_path: str | Path = None) -> str:
    """Generate JSON report.

    Args:
        report: CheckerReport instance.
        output_path: If provided, write to file.

    Returns:
        JSON string.
    """
    data = report.to_dict()
    json_str = json.dumps(data, indent=2, default=str)

    if output_path:
        Path(output_path).write_text(json_str, encoding="utf-8")

    return json_str


def to_html(report, output_path: str | Path = None) -> str:
    """Generate styled HTML report.

    Args:
        report: CheckerReport instance.
        output_path: If provided, write to file.

    Returns:
        HTML string.
    """
    results_html = ""
    for check_name, result in report.results.items():
        r = result.to_dict()
        status_class = "pass" if r["passed"] else "fail"
        status_badge = "✓ PASS" if r["passed"] else "✗ FAIL"
        safe_check_name = escape(str(check_name.upper()))
        safe_summary = escape(str(r["summary"]))

        # Build details table
        details_rows = ""
        if check_name == "spatial" and r.get("orphans"):
            for orphan in r["orphans"][:30]:
                details_rows += (
                    f"<tr><td>{escape(str(orphan['global_id']))}</td>"
                    f"<td>{escape(str(orphan['name']))}</td>"
                    f"<td>{escape(str(orphan['ifc_class']))}</td>"
                    f"<td>Not contained in any spatial element</td></tr>\n"
                )
        elif check_name == "guid" and r.get("duplicates"):
            for dup in r["duplicates"][:30]:
                entities = ", ".join(
                    f"{escape(str(e['name']))} ({escape(str(e['ifc_class']))})"
                    for e in dup["entities"]
                )
                details_rows += (
                    f"<tr><td>{escape(str(dup['guid']))}</td>"
                    f"<td colspan='2'>{entities}</td>"
                    f"<td>{escape(str(dup['count']))} occurrences</td></tr>\n"
                )
        elif check_name == "proxy" and r.get("proxies"):
            for proxy in r["proxies"][:30]:
                details_rows += (
                    f"<tr><td>{escape(str(proxy['global_id']))}</td>"
                    f"<td>{escape(str(proxy['name']))}</td>"
                    f"<td>{escape(str(proxy['object_type']))}</td>"
                    f"<td>Needs reclassification</td></tr>\n"
                )
        elif check_name == "type" and r.get("untyped_elements"):
            for elem in r["untyped_elements"][:30]:
                details_rows += (
                    f"<tr><td>{escape(str(elem['global_id']))}</td>"
                    f"<td>{escape(str(elem['name']))}</td>"
                    f"<td>{escape(str(elem['ifc_class']))}</td>"
                    f"<td>No type assignment</td></tr>\n"
                )
        elif check_name == "ids" and r.get("failures"):
            for failure in r["failures"]:
                for entity in (failure.get("failed_entities") or [])[:30]:
                    issue = f"{failure.get('spec_name', '')}: {failure.get('requirement', '')} - {entity.get('reason', '')}"
                    details_rows += (
                        f"<tr><td>{escape(str(entity.get('global_id', '')))}</td>"
                        f"<td>{escape(str(entity.get('name', '')))}</td>"
                        f"<td>{escape(str(entity.get('ifc_class', '')))}</td>"
                        f"<td>{escape(str(issue))}</td></tr>\n"
                    )
                if len(details_rows) > 40000:
                    break

        details_table = ""
        if details_rows:
            details_table = f"""
            <table class="details">
                <thead><tr>
                    <th>GlobalId</th><th>Name</th><th>Class/Type</th><th>Issue</th>
                </tr></thead>
                <tbody>{details_rows}</tbody>
            </table>"""

        if check_name == "ids" and r.get("report_paths"):
            links = "".join(
                f"<li>{escape(str(kind))}: <code>{escape(str(path))}</code></li>"
                for kind, path in r["report_paths"].items()
            )
            details_table += f"<div class='report-links'><strong>Generated IDS reports</strong><ul>{links}</ul></div>"

        if check_name == "ids" and r.get("report_errors"):
            errors = "".join(
                f"<li>{escape(str(err.get('report', 'report')))}: {escape(str(err.get('message', '')))}</li>"
                for err in r["report_errors"]
            )
            details_table += f"<div class='report-errors'><strong>Report generation warnings</strong><ul>{errors}</ul></div>"

        results_html += f"""
        <div class="check-card {status_class}">
            <div class="check-header">
                <span class="check-name">{safe_check_name}</span>
                <span class="badge {status_class}">{status_badge}</span>
            </div>
            <p class="check-summary">{safe_summary}</p>
            {details_table}
        </div>
        """

    overall_class = "pass" if report.overall_passed else "fail"
    overall_text = "ALL CHECKS PASSED" if report.overall_passed else "ISSUES FOUND"

    safe_file_name = escape(Path(report.file_path).name)
    safe_timestamp = escape(str(report.timestamp))

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>IFC Check Report — {safe_file_name}</title>
    <style>
        :root {{
            --bg: #0f1117;
            --card: #1a1d27;
            --border: #2a2d3a;
            --text: #e1e4ed;
            --text-dim: #8b8fa3;
            --pass-bg: #0d2818;
            --pass-border: #1a7a3a;
            --pass-text: #4ade80;
            --fail-bg: #2d0f0f;
            --fail-border: #7a1a1a;
            --fail-text: #f87171;
            --accent: #818cf8;
        }}
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: 'Inter', 'Segoe UI', system-ui, sans-serif;
            background: var(--bg);
            color: var(--text);
            line-height: 1.6;
            padding: 2rem;
        }}
        .container {{ max-width: 1000px; margin: 0 auto; }}
        h1 {{
            font-size: 1.8rem;
            font-weight: 700;
            margin-bottom: 0.25rem;
        }}
        .subtitle {{
            color: var(--text-dim);
            font-size: 0.9rem;
            margin-bottom: 2rem;
        }}
        .overall-banner {{
            padding: 1.25rem 1.5rem;
            border-radius: 12px;
            margin-bottom: 2rem;
            font-size: 1.1rem;
            font-weight: 600;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        .overall-banner.pass {{
            background: var(--pass-bg);
            border: 1px solid var(--pass-border);
            color: var(--pass-text);
        }}
        .overall-banner.fail {{
            background: var(--fail-bg);
            border: 1px solid var(--fail-border);
            color: var(--fail-text);
        }}
        .stats {{ display: flex; gap: 2rem; margin-bottom: 2rem; }}
        .stat {{
            background: var(--card);
            border: 1px solid var(--border);
            border-radius: 10px;
            padding: 1rem 1.25rem;
            flex: 1;
        }}
        .stat-value {{ font-size: 1.5rem; font-weight: 700; }}
        .stat-label {{ color: var(--text-dim); font-size: 0.8rem; }}
        .check-card {{
            background: var(--card);
            border: 1px solid var(--border);
            border-radius: 10px;
            padding: 1.25rem;
            margin-bottom: 1rem;
        }}
        .check-card.fail {{ border-left: 3px solid var(--fail-text); }}
        .check-card.pass {{ border-left: 3px solid var(--pass-text); }}
        .check-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 0.5rem;
        }}
        .check-name {{ font-weight: 600; font-size: 1rem; }}
        .badge {{
            padding: 0.2rem 0.75rem;
            border-radius: 6px;
            font-size: 0.75rem;
            font-weight: 600;
        }}
        .badge.pass {{ background: var(--pass-bg); color: var(--pass-text); }}
        .badge.fail {{ background: var(--fail-bg); color: var(--fail-text); }}
        .check-summary {{ color: var(--text-dim); font-size: 0.9rem; }}
        .details {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 0.75rem;
            font-size: 0.8rem;
        }}
        .details th {{
            text-align: left;
            padding: 0.5rem;
            border-bottom: 1px solid var(--border);
            color: var(--text-dim);
            font-weight: 500;
        }}
        .details td {{
            padding: 0.4rem 0.5rem;
            border-bottom: 1px solid var(--border);
            font-family: 'Cascadia Code', 'Fira Code', monospace;
            font-size: 0.75rem;
        }}
        .report-links, .report-errors {{
            margin-top: 0.75rem;
            color: var(--text-dim);
            font-size: 0.85rem;
        }}
        .report-errors {{ color: var(--fail-text); }}
        .report-links ul, .report-errors ul {{ margin-left: 1.2rem; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>🏗️ IFC Check Report</h1>
        <p class="subtitle">{safe_file_name} — {safe_timestamp}</p>

        <div class="overall-banner {overall_class}">
            <span>{overall_text}</span>
            <span>{report.checks_passed}/{report.checks_run} checks passed · {report.total_issues} issue(s) · {report.duration_seconds}s</span>
        </div>

        <div class="stats">
            <div class="stat">
                <div class="stat-value">{report.checks_run}</div>
                <div class="stat-label">Checks Run</div>
            </div>
            <div class="stat">
                <div class="stat-value" style="color: var(--pass-text)">{report.checks_passed}</div>
                <div class="stat-label">Passed</div>
            </div>
            <div class="stat">
                <div class="stat-value" style="color: var(--fail-text)">{report.checks_failed}</div>
                <div class="stat-label">Failed</div>
            </div>
            <div class="stat">
                <div class="stat-value" style="color: var(--accent)">{report.total_issues}</div>
                <div class="stat-label">Total Issues</div>
            </div>
        </div>

        {results_html}
    </div>
</body>
</html>"""

    if output_path:
        Path(output_path).write_text(html, encoding="utf-8")

    return html
