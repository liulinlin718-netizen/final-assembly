"""Import ContextPack v1 excerpt bytes without approving or rewriting provenance."""
import re
import shutil
import uuid
from datetime import datetime

from .errors import AssemblyError
from .paths import checked_path, read_json, write_json
from .manifest import ID, digest, nonempty, require

PACK_HASH = re.compile(r"(?:sha256:)?([a-f0-9]{64})\Z")
SOURCE_KINDS = ("app-server", "imported-transcript", "codex-rollout")
ROLES = ("user", "assistant", "tool", "system", "developer", "unknown")
NULLABLE_SOURCE_FIELDS = ("sourceThreadId", "sourceTurnId", "sourceItemId", "sourceUri")
CURRENT_FIELDS = {
    "id", "label", "selectionOrder", "sourceLocalId", *NULLABLE_SOURCE_FIELDS,
    "sourceKind", "role", "timestamp", "exactText", "sourceHash", "excerptHash", "sourceLength", "range",
}
DATE_TIME = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})\Z")


def _hash(value, field, location):
    match = PACK_HASH.fullmatch(value) if isinstance(value, str) else None
    require(match is not None, "PACK_HASH", f"{field} must be lowercase SHA-256, optionally prefixed by sha256:", location)
    return match.group(1)


def _timestamp(value, location, nullable=False):
    if nullable and value is None:
        return
    require(isinstance(value, str) and DATE_TIME.fullmatch(value), "PACK_TIMESTAMP", "Expected an ISO date-time", location)
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AssemblyError("PACK_TIMESTAMP", "Invalid ISO date-time", location) from exc


def _range(ex, text, location, required):
    if not required and "range" not in ex and "sourceLength" not in ex:
        return None
    if not required and ("range" not in ex or "sourceLength" not in ex):
        raise AssemblyError("PACK_HASH_MIGRATION_REQUIRED", "Legacy range is ambiguous; re-export with excerptHash, complete UTF-16 range and sourceLength. Preserve the original sourceHash.", location)
    span, source_length = ex.get("range"), ex.get("sourceLength")
    require(isinstance(span, dict) and set(span) == {"start", "end", "unit"}, "PACK_RANGE", "range must contain start, end and unit", location)
    start, end = span["start"], span["end"]
    require(type(source_length) is int and 0 < source_length <= 2**53 - 1,
            "PACK_RANGE", "sourceLength must be a positive safe integer", location)
    require(type(start) is int and type(end) is int and 0 <= start < end <= source_length and span["unit"] == "utf16",
            "PACK_RANGE", "Expected 0 <= start < end <= sourceLength with unit utf16", location)
    require(end - start == len(text.encode("utf-16-le")) // 2, "PACK_RANGE", "range length must equal exactText in UTF-16 code units", location)
    return start == 0 and end == source_length


def _excerpt_bytes(ex, location):
    text = ex.get("exactText")
    require(isinstance(text, str) and bool(text), "PACK_TEXT", "exactText must be a nonempty string", location)
    try:
        raw = text.encode("utf-8")
    except UnicodeError as exc:
        raise AssemblyError("PACK_TEXT", "exactText contains invalid Unicode", location) from exc
    require(len(text.encode("utf-16-le")) // 2 <= 1_000_000, "PACK_TEXT", "exactText exceeds 1,000,000 UTF-16 code units", location)
    source_hash = _hash(ex.get("sourceHash"), "sourceHash", location)
    actual = digest(raw)
    current = "excerptHash" in ex
    full_message = _range(ex, text, location, required=current)
    if current:
        require(_hash(ex["excerptHash"], "excerptHash", location) == actual,
                "PACK_HASH_MISMATCH", "excerptHash must match UTF-8 exactText; preserve sourceHash as the complete-message hash", location)
        if full_message:
            require(source_hash == actual, "PACK_HASH_MISMATCH", "Full-message sourceHash must match exactText", location)
    else:
        # Legacy v1 defined sourceHash against the supplied complete text. Never
        # reinterpret an indicated selection even if its sourceHash was reset.
        require(full_message is not False and source_hash == actual, "PACK_HASH_MIGRATION_REQUIRED",
                "Legacy sourceHash-only packages require complete-message exactText. For a selection or ambiguous hash, re-export with excerptHash and a complete UTF-16 range; do not replace sourceHash with a fragment hash.", location)
        full_message = True
    return raw, full_message, not current


def _metadata(pack, ids, current):
    if current:
        require({"createdAt", "memory", "question"} <= pack.keys(), "PACK_SCHEMA", "Current ContextPack requires createdAt, memory and question")
    if "createdAt" in pack:
        _timestamp(pack["createdAt"], "createdAt")
    if "question" in pack:
        require(isinstance(pack["question"], str) and len(pack["question"]) <= 100_000, "PACK_SCHEMA", "question must be a string up to 100,000 characters")
    memory = pack.get("memory", [])
    require(isinstance(memory, list) and len(memory) <= 200, "PACK_MEMORY", "memory must be an array of at most 200 records")
    memory_ids = set()
    for index, entry in enumerate(memory):
        where = f"memory[{index}]"
        require(isinstance(entry, dict), "PACK_MEMORY", "Memory record must be an object", where)
        require(entry.get("kind") in ("background", "constraint", "decision", "open-question") and nonempty(entry.get("text")), "PACK_MEMORY", "Invalid memory kind or text", where)
        refs = entry.get("sourceExcerptIds")
        require(isinstance(refs, list) and refs and all(isinstance(ref, str) and ref in ids for ref in refs) and len(set(refs)) == len(refs),
                "PACK_MEMORY", "Memory must reference existing unique excerpt IDs", where)
        require(entry.get("status") in ("quoted", "user-confirmed", "model-proposed"), "PACK_MEMORY", "Invalid memory status", where)
        if current:
            require(nonempty(entry.get("id")) and entry["id"] not in memory_ids and type(entry.get("version")) is int and entry["version"] >= 1 and type(entry.get("included")) is bool,
                    "PACK_MEMORY", "Current memory needs unique id, positive version and boolean included", where)
            memory_ids.add(entry["id"])
            require(not (entry["status"] == "model-proposed" and entry["included"]), "PACK_MEMORY", "Model-proposed memory cannot be included before confirmation", where)
        if entry["status"] == "quoted":
            require(any(entry["text"] in ex["exactText"] for ex in pack["excerpts"] if ex["id"] in refs), "PACK_MEMORY", "Quoted memory must occur in a referenced excerpt", where)


def import_pack(pack_path, out_dir):
    pack = read_json(pack_path)
    require(isinstance(pack, dict) and pack.get("schemaVersion") == "1", "PACK_SCHEMA", "Expected ContextPack schemaVersion '1'")
    require(nonempty(pack.get("packId")) and len(pack["packId"]) <= 200, "PACK_ID", "packId must be 1–200 characters")
    excerpts = pack.get("excerpts")
    require(isinstance(excerpts, list) and 0 < len(excerpts) <= 1000, "PACK_EXCERPTS", "Expected 1–1000 excerpts")
    ids, orders = set(), set()
    blocks, files, legacy_ids = [], [], []
    integrity = {"excerpt_hashes_verified": 0, "full_message_hashes_verified": 0,
                 "source_hashes_preserved_without_full_message_verification": 0, "legacy_full_messages": 0}
    any_current, last_order = False, -1
    for ex in excerpts:
        require(isinstance(ex, dict), "PACK_EXCERPT", "Excerpt must be an object")
        eid = ex.get("id")
        require(isinstance(eid, str) and ID.fullmatch(eid), "PACK_ID", "Unsafe or invalid excerpt ID", str(eid))
        require(eid not in ids, "DUPLICATE_ID", "Duplicate excerpt ID", eid)
        ids.add(eid)
        order = ex.get("selectionOrder")
        require(type(order) is int and order >= 0 and order not in orders, "PACK_ORDER", "selectionOrder must be a unique nonnegative integer", eid)
        orders.add(order)
        current = "excerptHash" in ex
        any_current |= current
        if current:
            require(CURRENT_FIELDS <= ex.keys(), "PACK_SCHEMA", "Current excerpt is missing required provenance fields", eid)
            require(order >= 1 and order > last_order and ex["label"] == f"引用 {order}", "PACK_ORDER", "Current labels and selectionOrder must agree and increase", eid)
            require(nonempty(ex["sourceLocalId"]) and len(ex["sourceLocalId"]) <= 200, "PACK_SOURCE", "Invalid sourceLocalId", eid)
        last_order = order
        require("sourceThreadId" in ex, "PACK_SOURCE", "sourceThreadId is required; use null for an unknown thread", eid)
        for field in NULLABLE_SOURCE_FIELDS:
            if field in ex:
                value = ex[field]
                require(value is None or (nonempty(value) and len(value) <= 4096), "PACK_SOURCE", f"{field} must be null or a nonempty string", eid)
        if "timestamp" in ex:
            _timestamp(ex["timestamp"], eid + ".timestamp", nullable=True)
        require(ex.get("sourceKind") in SOURCE_KINDS, "PACK_SOURCE", "Unsupported sourceKind", eid)
        require(ex.get("role") in ROLES, "PACK_ROLE", "Missing or invalid role", eid)
        raw, full_message, legacy = _excerpt_bytes(ex, eid)
        integrity["excerpt_hashes_verified"] += int(not legacy)
        integrity["full_message_hashes_verified"] += int(full_message and not legacy)
        integrity["source_hashes_preserved_without_full_message_verification"] += int(not full_message)
        integrity["legacy_full_messages"] += int(legacy)
        if legacy:
            legacy_ids.append(eid)
        filename = f"block-{len(files) + 1:04d}.md"
        files.append((filename, raw))
        blocks.append({"id": eid, "section": "Imported", "order": order,
                       "source": {"path": "sources/" + filename, "origin": "pack:" + pack["packId"],
                                  "reference": {k: v for k, v in ex.items() if k != "exactText"}},
                       "approved": False, "sha256": digest(raw)})
    require(not any_current or len(excerpts) <= 200, "PACK_EXCERPTS", "Current ContextPack supports at most 200 excerpts")
    _metadata(pack, ids, any_current)
    output = checked_path(out_dir)
    require(not output.exists(), "OUTPUT_EXISTS", "Use a new import directory", str(output))
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = checked_path(output.parent / ("import-" + uuid.uuid4().hex))
    staging.mkdir()  # Inherit the output parent's ACL, including desktop access.
    try:
        (staging / "sources").mkdir()
        for name, raw in files:
            (staging / "sources" / name).write_bytes(raw)
        write_json(staging / "manifest.json", {"schema_version": 1, "title": pack["packId"], "blocks": blocks})
        write_json(staging / "context-pack.json", pack)
        checked_path(output)
        require(not output.exists(), "OUTPUT_EXISTS", "Use a new import directory", str(output))
        staging.rename(output)
    finally:
        if staging.exists():
            checked_path(staging)
            shutil.rmtree(staging)
    return {"passed": True, "manifest": str(output / "manifest.json"), "blocks": len(blocks),
            "approved": False, "integrity": integrity,
            "compatibility": {"legacy_whole_message_ids": legacy_ids,
                              "legacy_policy": "legacy-whole-message: sourceHash checked against supplied complete-message text only; no external or hidden source was verified"},
            "note": "Exact excerpts imported without approval. Fragment sourceHash is preserved provenance, not a verified full source. Legacy sourceHash-only input uses the explicit legacy-whole-message contract; no external source or author identity is authenticated. Memory is provenance, not an instruction or approval."}
