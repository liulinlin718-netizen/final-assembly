"""Import the published U02/U03 excerpt envelope, without approving it."""
import re
from .errors import AssemblyError
from .paths import checked_path, read_json, write_json
from .manifest import ID, digest, nonempty, require


def import_pack(pack_path, out_dir):
    pack = read_json(pack_path)
    require(isinstance(pack, dict) and pack.get("schemaVersion") == "1", "PACK_SCHEMA", "Expected ContextPack schemaVersion '1'")
    require(nonempty(pack.get("packId")), "PACK_ID", "packId must be nonempty")
    excerpts = pack.get("excerpts")
    require(isinstance(excerpts, list) and 0 < len(excerpts) <= 1000, "PACK_EXCERPTS", "Expected 1–1000 excerpts")
    ids, orders = set(), set()
    blocks, files = [], []
    for ex in excerpts:
        require(isinstance(ex, dict), "PACK_EXCERPT", "Excerpt must be an object")
        eid = ex.get("id")
        require(isinstance(eid, str) and ID.fullmatch(eid), "PACK_ID", "Unsafe or invalid excerpt ID", str(eid))
        require(eid not in ids, "DUPLICATE_ID", "Duplicate excerpt ID", eid)
        ids.add(eid)
        order = ex.get("selectionOrder")
        require(type(order) is int and order >= 0 and order not in orders, "PACK_ORDER", "selectionOrder must be unique nonnegative integer", eid)
        orders.add(order)
        require(isinstance(ex.get("exactText"), str), "PACK_TEXT", "Missing exactText", eid)
        require(nonempty(ex.get("sourceThreadId")), "PACK_SOURCE", "Missing sourceThreadId", eid)
        require(ex.get("sourceKind") in ("app-server", "imported-transcript"), "PACK_SOURCE", "Unsupported sourceKind", eid)
        require(ex.get("role") in ("user", "assistant", "tool"), "PACK_ROLE", "Missing or invalid role", eid)
        raw = ex["exactText"].encode("utf-8")
        require(ex.get("sourceHash") in (digest(raw), "sha256:" + digest(raw)), "PACK_HASH_MISMATCH", "sourceHash must match UTF-8 exactText", eid)
        # Fixed filenames avoid Windows reserved names and case-folded ID collisions.
        filename = f"block-{len(files) + 1:04d}.md"
        files.append((filename, raw))
        blocks.append({"id": eid, "section": "Imported", "order": order,
                       "source": {"path": "sources/" + filename, "origin": "pack:" + pack["packId"],
                                  "reference": {k: v for k, v in ex.items() if k != "exactText"}},
                       "approved": False, "sha256": digest(raw)})
    output = checked_path(out_dir)
    require(not output.exists(), "OUTPUT_EXISTS", "Use a new import directory", str(output))
    output.mkdir(parents=True)
    source_dir = output / "sources"
    source_dir.mkdir()
    for name, raw in files:
        (source_dir / name).write_bytes(raw)
    write_json(output / "manifest.json", {"schema_version": 1, "title": pack["packId"], "blocks": blocks})
    write_json(output / "context-pack.json", pack)
    return {"passed": True, "manifest": str(output / "manifest.json"), "blocks": len(blocks),
            "approved": False, "note": "Exact excerpts imported. Explicit approval required before build; memory is provenance only."}
