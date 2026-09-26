import hashlib
import re
from .errors import AssemblyError
from .paths import checked_path, read_bytes, parse_json
from .markdown import parse_markdown

ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}\Z")
HASH = re.compile(r"[a-f0-9]{64}\Z")


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def require(condition, code, message, location=None):
    if not condition:
        raise AssemblyError(code, message, location)


def fields(obj, required, optional, where):
    require(isinstance(obj, dict), "INVALID_MANIFEST", "Expected an object", where)
    require(required <= obj.keys(), "MISSING_FIELD", f"Required fields: {sorted(required - obj.keys())}", where)
    require(obj.keys() <= required | optional, "UNKNOWN_FIELD", f"Unknown fields: {sorted(obj.keys() - required - optional)}", where)


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def load_manifest(path, *, allow_unapproved=False, collect_issues=False):
    """Read a manifest; normal callers retain the strict build contract.

    Draft inspection may collect source/format issues without treating that
    successful inspection as approval or permission to build. Invalid manifest
    structure and replacement graphs always fail before inspecting sources.
    """
    path = checked_path(path)
    manifest_raw = read_bytes(path)
    manifest = parse_json(manifest_raw, path)
    fields(manifest, {"schema_version", "title", "blocks"}, set(), "manifest")
    require(type(manifest["schema_version"]) is int and manifest["schema_version"] == 1,
            "SCHEMA_VERSION", "Expected schema_version 1")
    require(nonempty(manifest["title"]), "INVALID_TITLE", "Title must be nonempty")
    rows = manifest["blocks"]
    require(isinstance(rows, list) and 0 < len(rows) <= 1000, "INVALID_BLOCKS", "Expected 1–1000 blocks")
    records = {}
    for row in rows:
        fields(row, {"id", "section", "order", "source", "approved", "sha256"}, {"replaces", "approval"}, "block")
        name = row["id"]
        require(isinstance(name, str) and ID.fullmatch(name), "INVALID_ID", "ID must be 1–80 ASCII letters, numbers, dots, underscores or hyphens", str(name))
        require(name not in records, "DUPLICATE_ID", "Block ID occurs more than once", name)
        require(nonempty(row["section"]), "INVALID_SECTION", "Section must be nonempty", name)
        require(type(row["order"]) is int and row["order"] >= 0, "INVALID_ORDER", "Order must be a nonnegative integer", name)
        require(type(row["approved"]) is bool, "INVALID_APPROVAL", "Approval must be explicit boolean", name)
        require(isinstance(row["sha256"], str) and HASH.fullmatch(row["sha256"]), "INVALID_HASH", "sha256 must be lowercase hexadecimal", name)
        if "approval" in row:
            fields(row["approval"], {"decision", "sha256"}, set(), name + ".approval")
            require(nonempty(row["approval"]["decision"]), "INVALID_APPROVAL", "Approval decision must be nonempty", name)
            require(row["approval"]["sha256"] == row["sha256"], "APPROVAL_HASH_MISMATCH", "Approval must refer to the manifest's exact source hash", name)
        fields(row["source"], {"path", "origin"}, {"reference"}, name + ".source")
        require(nonempty(row["source"]["path"]) and nonempty(row["source"]["origin"]), "INVALID_SOURCE", "Source path and origin must be nonempty", name)
        if "reference" in row["source"]:
            require(isinstance(row["source"]["reference"], dict), "INVALID_SOURCE", "Reference must be an object", name)
        if "replaces" in row:
            require(isinstance(row["replaces"], str) and ID.fullmatch(row["replaces"]), "INVALID_REPLACEMENT", "replaces must name a block ID", name)
        records[name] = dict(row)

    replaced_by = {}
    for name, row in records.items():
        old = row.get("replaces")
        if old is None:
            continue
        require(old in records, "MISSING_REPLACEMENT", "Replaced block does not exist", name + ".replaces")
        require(old not in replaced_by, "REPLACEMENT_CONFLICT", "Two blocks replace the same block", old)
        replaced_by[old] = name
    for name in records:
        seen = set()
        cursor = name
        while cursor in replaced_by:
            require(cursor not in seen, "REPLACEMENT_CYCLE", "Replacement graph contains a cycle", cursor)
            seen.add(cursor)
            cursor = replaced_by[cursor]

    active = [row for name, row in records.items() if name not in replaced_by]
    active.sort(key=lambda block: block["order"])
    orders = set()
    for row in active:
        if not allow_unapproved:
            require(row["approved"], "UNAPPROVED_BLOCK", "Active block needs explicit user approval", row["id"])
        require(row["order"] not in orders, "DUPLICATE_ORDER", "Active blocks must have unique order", row["id"])
        orders.add(row["order"])

    issues = []

    def record_issue(name, row, exc):
        if not collect_issues:
            raise exc
        entry = {"block": name, **exc.as_dict()}
        row["issues"].append(entry)
        issues.append(entry)

    # History is audited too: replacing a block does not erase its provenance.
    for name, row in records.items():
        if collect_issues:
            row["issues"] = []
            row["source_verified"] = False
        try:
            source_path = checked_path(row["source"]["path"], path.parent)
            raw = read_bytes(source_path)
        except AssemblyError as exc:
            record_issue(name, row, exc)
            continue
        row["raw"] = raw
        row["source_path"] = str(source_path)
        actual_sha256 = digest(raw)
        if collect_issues:
            row["actual_sha256"] = actual_sha256
            row["source_verified"] = actual_sha256 == row["sha256"]
        if actual_sha256 != row["sha256"]:
            record_issue(name, row, AssemblyError("SOURCE_HASH_MISMATCH", "Source bytes changed since approval; restore or record a newly approved version", name))
        try:
            text = raw.decode("utf-8")
        except UnicodeError as exc:
            record_issue(name, row, AssemblyError("INVALID_UTF8", str(exc), name))
            continue
        if collect_issues:
            row["text"] = text
        if name not in replaced_by:
            try:
                row["units"] = parse_markdown(text)
                require(bool(row["units"]), "EMPTY_BLOCK", "Active block has no supported content units", name)
            except AssemblyError as exc:
                record_issue(name, row, AssemblyError(exc.code, exc.message, name + ":" + str(exc.location or "source")))

    return {"manifest": manifest, "path": path, "sha256": digest(manifest_raw),
            "active": active, "records": records, "replaced_by": replaced_by, "issues": issues}
