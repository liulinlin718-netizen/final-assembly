"""Deterministic source preparation, draft inspection and adoption records."""
import copy
import json
import os
import shutil
import uuid

from .errors import AssemblyError
from .manifest import digest, load_manifest, nonempty, require
from .paths import checked_path, read_bytes, workspace_root, write_json


def prepare(sources, out_dir, title, origin, section="Content"):
    """Snapshot selected bytes into a new, deliberately unapproved draft."""
    require(isinstance(sources, (list, tuple)) and 0 < len(sources) <= 1000,
            "INVALID_SOURCES", "Select 1–1000 source files in their intended order")
    require(nonempty(title), "INVALID_TITLE", "Title must be nonempty")
    require(nonempty(origin), "INVALID_SOURCE", "Origin must describe the source of these selected files")
    require(nonempty(section), "INVALID_SECTION", "Section must be nonempty")
    output = checked_path(out_dir)
    require(not output.exists(), "OUTPUT_EXISTS", "Use a new draft directory", str(output))
    inputs, seen = [], set()
    for source in sources:
        path = checked_path(source)
        require(path not in seen, "DUPLICATE_SOURCE", "The same source file was selected more than once", str(path))
        seen.add(path)
        inputs.append((path, read_bytes(path)))

    parent = checked_path(output.parent)
    parent.mkdir(parents=True, exist_ok=True)
    staging = checked_path(parent / ("prepare-" + uuid.uuid4().hex))
    staging.mkdir()  # A published draft must inherit the user's parent ACL.
    try:
        (staging / "sources").mkdir()
        blocks = []
        for index, (source, raw) in enumerate(inputs, 1):
            name = f"block-{index:04d}"
            relative = f"sources/{name}.md"
            target = checked_path(staging / relative)
            with target.open("xb") as handle:
                handle.write(raw)
            expected = digest(raw)
            require(digest(read_bytes(target)) == expected, "PREPARE_READBACK_FAILED", "Source snapshot differs from selected bytes", name)
            blocks.append({
                "id": name, "section": section, "order": index * 10,
                "source": {"path": relative, "origin": origin,
                           "reference": {"prepared_from": source.relative_to(workspace_root().resolve()).as_posix()}},
                "approved": False, "sha256": expected,
            })
        write_json(staging / "manifest.json", {"schema_version": 1, "title": title, "blocks": blocks})
        for source, raw in inputs:
            require(digest(read_bytes(source)) == digest(raw), "SOURCE_CHANGED_DURING_PREPARE", "Selected source changed while its draft was prepared; retry after the edit is complete", str(source))
        checked_path(output)
        require(not output.exists(), "OUTPUT_EXISTS", "Draft output appeared while preparing; choose a new directory", str(output))
        staging.rename(output)
        return {"passed": True, "manifest": str(output / "manifest.json"),
                "output_dir": str(output), "blocks": len(blocks),
                "block_ids": [block["id"] for block in blocks], "approved": False,
                "note": "Selected bytes were snapshotted. Inspect the draft and record an explicit adoption decision before building."}
    finally:
        if staging.exists():
            checked_path(staging)
            shutil.rmtree(staging)


def inspect_manifest(path, full_text=False):
    """Inspect draft/current/history content without granting approval."""
    data = load_manifest(path, allow_unapproved=True, collect_issues=True)
    blocks = []
    for row in data["records"].values():
        active = row["id"] not in data["replaced_by"]
        text = row.get("text")
        item = {"id": row["id"], "section": row["section"], "order": row["order"],
                "active": active, "approved": row["approved"], "source": row["source"],
                "sha256": row["sha256"], "actual_sha256": row.get("actual_sha256"),
                "source_verified": row["source_verified"],
                "supported": ("units" in row and not row["issues"]) if active else None,
                "units": len(row.get("units", [])) if active else None,
                "text": text if full_text or text is None else text[:600],
                "text_truncated": text is not None and not full_text and len(text) > 600,
                "issues": row["issues"]}
        if "replaces" in row:
            item["replaces"] = row["replaces"]
        if not active:
            item["replaced_by"] = data["replaced_by"][row["id"]]
        if "approval" in row:
            item["approval"] = row["approval"]
        blocks.append(item)
    pending = [row["id"] for row in data["active"] if not row["approved"]]
    return {"passed": True, "inspection_completed": True,
            "ready_to_build": not pending and not data["issues"],
            "manifest": str(data["path"]), "manifest_sha256": data["sha256"],
            "title": data["manifest"]["title"], "blocks": blocks,
            "active_order": [row["id"] for row in data["active"]],
            "pending_approval": pending, "issues": data["issues"],
            "replacements": [{"old": old, "new": new} for old, new in data["replaced_by"].items()],
            "note": "Inspection is not approval. A successful inspection may still contain blocking issues or unapproved blocks."}


def _assert_adoptable(data, selected):
    # A new manifest must not conceal missing/drifting historical sources.
    for row in data["records"].values():
        if not row["source_verified"]:
            issue = row["issues"][0]
            raise AssemblyError(issue["code"], issue["message"], issue["location"])
        if row["id"] in selected and row["issues"]:
            issue = row["issues"][0]
            raise AssemblyError(issue["code"], issue["message"], issue["location"])


def approve(manifest, ids, decision, out_manifest):
    """Record an explicit decision for selected active IDs in a new manifest."""
    require(isinstance(ids, (list, tuple)) and bool(ids), "INVALID_SELECTION", "Provide at least one active block ID")
    require(all(isinstance(name, str) for name in ids), "INVALID_SELECTION", "Selected block IDs must be strings")
    require(len(set(ids)) == len(ids), "DUPLICATE_SELECTION", "Selected block IDs must be unique")
    require(nonempty(decision), "INVALID_APPROVAL", "Record the user's explicit adoption decision")
    output = checked_path(out_manifest)
    require(not output.exists(), "OUTPUT_EXISTS", "Use a new output manifest; prior decisions are preserved", str(output))
    data = load_manifest(manifest, allow_unapproved=True, collect_issues=True)
    active_ids = {row["id"] for row in data["active"]}
    for name in ids:
        require(name in data["records"], "UNKNOWN_BLOCK", "Selected block ID does not exist", name)
        require(name in active_ids, "INACTIVE_BLOCK", "Select the current active block; historical records cannot be adopted in place", name)
    selected = set(ids)
    _assert_adoptable(data, selected)
    result = copy.deepcopy(data["manifest"])
    for row in result["blocks"]:
        row["source"]["path"] = os.path.relpath(data["records"][row["id"]]["source_path"], output.parent).replace("\\", "/")
        if row["id"] in selected:
            row["approved"] = True
            row["approval"] = {"decision": decision, "sha256": row["sha256"]}

    # Re-read the original manifest and sources immediately before recording.
    fresh = load_manifest(manifest, allow_unapproved=True, collect_issues=True)
    require(fresh["sha256"] == data["sha256"], "MANIFEST_CHANGED", "Manifest changed while recording adoption; inspect it again")
    _assert_adoptable(fresh, selected)
    raw = (json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    output.parent.mkdir(parents=True, exist_ok=True)
    checked_path(output)
    created = False
    try:
        with output.open("xb") as handle:
            created = True
            handle.write(raw)
        require(read_bytes(output) == raw, "APPROVAL_READBACK_FAILED", "The recorded manifest differs from the intended adoption record", str(output))
    except BaseException:
        if created:
            checked_path(output)
            output.unlink()
        raise
    pending = [row["id"] for row in result["blocks"] if row["id"] in active_ids and not row["approved"]]
    return {"passed": True, "manifest": str(output), "manifest_sha256": digest(raw),
            "approved_ids": list(ids), "decision": decision, "pending_approval": pending,
            "issues": data["issues"], "ready_to_build": not pending and not data["issues"],
            "note": "Explicit adoption recorded against current source hashes. This record does not authenticate a person's identity."}
