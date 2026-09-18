"""Content evidence comes from decoded exported files, never a model."""
from .manifest import digest


def reconcile(expected, actual, format_name, artifact_sha256):
    issues = []
    blocks = []
    cells = []
    links = []
    issue_count = 0

    def issue(code, location, wanted, found):
        nonlocal issue_count
        issue_count += 1
        if len(issues) < 200:
            issues.append({"code": code, "location": location, "expected": wanted, "actual": found})

    def spans(wanted, found, location):
        if wanted != found:
            issue("TEXT_OR_LINK_MISMATCH", location, wanted, found)
        for i, span in enumerate(wanted):
            if "url" in span:
                got = found[i] if i < len(found) else None
                links.append({"location": location + f".span[{i + 1}].url", "expected": span["url"],
                              "actual": got.get("url") if isinstance(got, dict) else None,
                              "passed": got == span})

    wanted_ids = [b["id"] for b in expected]
    actual_ids = [b["id"] for b in actual]
    if wanted_ids != actual_ids:
        issue("BLOCK_ORDER_OR_SET_MISMATCH", "document.blocks", wanted_ids, actual_ids)
    if len(set(actual_ids)) != len(actual_ids):
        issue("DUPLICATE_EXPORTED_BLOCK", "document.blocks", wanted_ids, actual_ids)
    actual_map = {block["id"]: block for block in actual}
    for block in expected:
        bid = block["id"]
        found = actual_map.get(bid)
        start = issue_count
        if found is None:
            issue("MISSING_BLOCK", bid, bid, None)
            blocks.append({"id": bid, "passed": False})
            continue
        if format_name == "markdown" and block["raw"] != found["raw"]:
            issue("SOURCE_BYTES_MISMATCH", bid + ".raw", digest(block["raw"]), digest(found["raw"]))
        expected_units, actual_units = block["units"], found["units"]
        if len(expected_units) != len(actual_units):
            issue("UNIT_COUNT_MISMATCH", bid + ".units", len(expected_units), len(actual_units))
        block_cells = 0
        for i, unit in enumerate(expected_units):
            loc = f"{bid}.unit[{i + 1}]"
            got = actual_units[i] if i < len(actual_units) else None
            if got is None or unit["kind"] != got.get("kind"):
                issue("UNIT_KIND_OR_ORDER_MISMATCH", loc, unit, got)
                continue
            kind = unit["kind"]
            if kind == "table":
                if unit.get("alignment") != got.get("alignment"):
                    issue("TABLE_ALIGNMENT_MISMATCH", loc + ".alignment", unit.get("alignment"), got.get("alignment"))
                rows, actual_rows = unit["rows"], got["rows"]
                if len(rows) != len(actual_rows):
                    issue("TABLE_ROW_COUNT_MISMATCH", loc + ".table.rows", len(rows), len(actual_rows))
                for r, row in enumerate(rows):
                    found_row = actual_rows[r] if r < len(actual_rows) else []
                    row_loc = loc + f".table.row[{r + 1}]"
                    if len(row) != len(found_row):
                        issue("TABLE_COLUMN_COUNT_MISMATCH", row_loc, len(row), len(found_row))
                    for c, cell in enumerate(row):
                        present = r < len(actual_rows) and c < len(found_row)
                        found_cell = found_row[c] if present else []
                        cell_loc = row_loc + f".cell[{c + 1}]"
                        spans(cell, found_cell, cell_loc)
                        if not present:
                            issue("MISSING_TABLE_CELL", cell_loc, cell, None)
                        cells.append({"block": bid, "location": cell_loc, "expected": cell,
                                      "actual": found_cell if present else None, "passed": present and cell == found_cell})
                        block_cells += 1
            else:
                for key in ("level", "ordered", "number"):
                    if unit.get(key) != got.get(key):
                        issue("STRUCTURE_MISMATCH", loc + "." + key, unit.get(key), got.get(key))
                spans(unit["spans"], got["spans"], loc + ".spans")
        blocks.append({"id": bid, "passed": issue_count == start, "units": len(expected_units),
                       "table_cells": block_cells, "source_sha256": block["sha256"]})
    return {"passed": not issues, "format": format_name, "artifact_sha256": artifact_sha256,
            "scope": "supported-content-and-order", "source_bytes_checked": True,
            "exported_block_bytes_checked": format_name == "markdown", "visual_layout_checked": False,
            "expected_block_order": wanted_ids, "actual_block_order": actual_ids,
            "blocks": blocks, "table_cells": cells, "links": links,
            "issues": issues, "issue_count": issue_count, "issues_truncated": issue_count > 200, "issue_limit": 200}
