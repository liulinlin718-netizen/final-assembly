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


def load_manifest(path):
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
        fields(row, {"id", "section", "order", "source", "approved", "sha256"}, {"replaces"}, "block")
        name = row["id"]
        require(isinstance(name, str) and ID.fullmatch(name), "INVALID_ID", "ID must be 1–80 ASCII letters, numbers, dots, underscores or hyphens", str(name))
        require(name not in records, "DUPLICATE_ID", "Block ID occurs more than once", name)
        require(nonempty(row["section"]), "INVALID_SECTION", "Section must be nonempty", name)
        require(type(row["order"]) is int and row["order"] >= 0, "INVALID_ORDER", "Order must be a nonnegative integer", name)
        require(type(row["approved"]) is bool, "INVALID_APPROVAL", "Approval must be explicit boolean", name)
        require(isinstance(row["sha256"], str) and HASH.fullmatch(row["sha256"]), "INVALID_HASH", "sha256 must be lowercase hexadecimal", name)
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
        require(row["approved"], "UNAPPROVED_BLOCK", "Active block needs explicit user approval", row["id"])
        require(row["order"] not in orders, "DUPLICATE_ORDER", "Active blocks must have unique order", row["id"])
        orders.add(row["order"])

    # History is audited too: replacing a block does not erase its provenance.
    for name, row in records.items():
        source_path = checked_path(row["source"]["path"], path.parent)
        raw = read_bytes(source_path)
        require(digest(raw) == row["sha256"], "SOURCE_HASH_MISMATCH", "Source bytes changed since approval; restore or record a newly approved version", name)
        try:
            text = raw.decode("utf-8")
        except UnicodeError as exc:
            raise AssemblyError("INVALID_UTF8", str(exc), name) from exc
        row["raw"] = raw
        row["source_path"] = str(source_path)
        if name not in replaced_by:
            try:
                row["units"] = parse_markdown(text)
                require(bool(row["units"]), "EMPTY_BLOCK", "Active block has no supported content units", name)
            except AssemblyError as exc:
                raise AssemblyError(exc.code, exc.message, name + ":" + str(exc.location or "source")) from exc

    return {"manifest": manifest, "path": path, "sha256": digest(manifest_raw),
            "active": active, "records": records, "replaced_by": replaced_by}
