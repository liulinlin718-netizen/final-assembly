import shutil
import uuid
from pathlib import Path
from . import __version__
from .errors import AssemblyError
from .paths import checked_path, read_bytes, write_json
from .manifest import digest, load_manifest, require
from .markdown import read_markdown, write_markdown
from .compare import reconcile


def verify_loaded(loaded, path):
    path = checked_path(path)
    raw = read_bytes(path)
    suffix = path.suffix.lower()
    require(suffix in {".md", ".docx"}, "UNSUPPORTED_EXPORT", "Expected .md or .docx", str(path))
    format_name = "markdown" if suffix == ".md" else "docx"
    try:
        if suffix == ".md":
            actual = read_markdown(raw)
        else:
            from .docx_io import read_docx_bytes
            actual = read_docx_bytes(raw)
        report = reconcile(loaded["active"], actual, format_name, digest(raw))
    except AssemblyError as exc:
        report = {"passed": False, "format": format_name, "artifact_sha256": digest(raw),
                  "scope": "supported-content-and-order", "visual_layout_checked": False,
                  "issues": [exc.as_dict()]}
    report["manifest_sha256"] = loaded["sha256"]
    report["artifact"] = str(path)
    return report


def preview(manifest):
    data = load_manifest(manifest)
    return {"passed": True, "title": data["manifest"]["title"], "manifest_sha256": data["sha256"],
            "model_required": False,
            "blocks": [{"id": b["id"], "section": b["section"], "order": b["order"],
                        "source": b["source"], "sha256": b["sha256"], "units": len(b["units"]),
                        "table_cells": sum(sum(len(row) for row in u["rows"]) for u in b["units"] if u["kind"] == "table")}
                       for b in data["active"]],
            "replacements": [{"old": old, "new": new} for old, new in data["replaced_by"].items()]}


def build(manifest, out_dir):
    data = load_manifest(manifest)
    output = checked_path(out_dir)
    require(not output.exists(), "OUTPUT_EXISTS", "Use a new output directory to preserve earlier evidence", str(output))
    temp_root = checked_path(output.parent)
    temp_root.mkdir(parents=True, exist_ok=True)
    # The staged directory becomes the user's delivery. Inherit the chosen
    # parent's access policy: mkdtemp's Windows owner-only ACL survives rename
    # and can make an agent-produced delivery unreadable by desktop apps.
    staging = temp_root / ("assembly-" + uuid.uuid4().hex)
    staging.mkdir()
    try:
        (staging / "final.md").write_bytes(write_markdown(data["active"]))
        from .docx_io import write_docx
        write_docx(data["active"], staging / "final.docx")
        reports = [verify_loaded(data, staging / filename) for filename in ("final.md", "final.docx")]
        require(all(r["passed"] for r in reports), "BUILD_READBACK_FAILED", "Actual files failed content reconciliation", reports)
        # Revalidate sources at publication to catch edits during build.
        fresh = load_manifest(manifest)
        require(fresh["sha256"] == data["sha256"], "MANIFEST_CHANGED", "Manifest changed during build")
        for report in reports:
            report["artifact"] = str(output / Path(report["artifact"]).name)
        snapshot = data["manifest"]
        # Include all approved and historical sources so a delivery is portable.
        (staging / "sources").mkdir()
        for index, row in enumerate(snapshot["blocks"], 1):
            source_name = f"sources/block-{index:04d}.md"
            (staging / source_name).write_bytes(data["records"][row["id"]]["raw"])
            row["source"]["path"] = source_name
        write_json(staging / "manifest.snapshot.json", snapshot)
        report = {"passed": True, "version": __version__, "output_dir": str(output),
                  "manifest_sha256": data["sha256"], "model_used": False,
                  "replacements": data["replaced_by"], "formats": reports,
                  "visual_layout_checked": False}
        write_json(staging / "reconciliation.json", report)
        output.parent.mkdir(parents=True, exist_ok=True)
        checked_path(output)
        # A completed directory becomes visible only after both actual files pass.
        staging.rename(output)
        return report
    finally:
        if staging.exists():
            checked_path(staging)
            shutil.rmtree(staging)
