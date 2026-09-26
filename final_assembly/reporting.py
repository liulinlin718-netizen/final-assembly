"""Bounded CLI receipts; the complete reconciliation remains on disk."""


def _short(value, limit=240):
    text = str(value)
    return text if len(text) <= limit else text[:limit] + "…"


def _issue(issue):
    # Expected/actual may contain entire tables or private source text. The
    # receipt points to complete evidence without repeating that payload.
    return {key: _short(issue[key]) for key in ("code", "location", "message") if key in issue}


def _format(report):
    issues = report.get("issues", [])
    result = {key: report[key] for key in ("passed", "format", "artifact", "artifact_sha256", "scope", "source_bytes_checked", "exported_block_bytes_checked", "visual_layout_checked") if key in report}
    result.update({"blocks_checked": len(report.get("blocks", [])),
                   "table_cells_checked": len(report.get("table_cells", [])),
                   "links_checked": len(report.get("links", [])),
                   "issue_count": report.get("issue_count", len(issues)),
                   "issues": [_issue(issue) for issue in issues[:5]],
                   "issues_omitted": report.get("issue_count", len(issues)) > 5})
    return result


def summarize(report, report_file):
    result = {"passed": report["passed"], "summary": True, "report_file": report_file}
    for key in ("version", "output_dir", "manifest_sha256", "model_used", "visual_layout_checked"):
        if key in report:
            result[key] = report[key]
    if "formats" in report:
        result["formats"] = [_format(item) for item in report["formats"]]
        result["replacement_count"] = len(report.get("replacements", {}))
    elif "format" in report:
        result.update(_format(report))
    if "error" in report:
        result["error"] = _issue(report["error"])
    return result
