"""Draft preparation/adoption keeps source bytes and explicit approval separate."""
import json
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch
import uuid

from final_assembly import preparation
from final_assembly.core import build, verify_loaded
from final_assembly.errors import AssemblyError
from final_assembly.manifest import digest, load_manifest
from final_assembly.paths import ROOT, workspace


class PreparationTests(unittest.TestCase):
    def setUp(self):
        parent = ROOT / ".runtime" / "preparation-tests"
        parent.mkdir(parents=True, exist_ok=True)
        self.root = parent / uuid.uuid4().hex
        self.root.mkdir()
        self.addCleanup(shutil.rmtree, self.root)
        self.scope = workspace(self.root)
        self.scope.__enter__()
        self.addCleanup(self.scope.__exit__, None, None, None)

    def source(self, name="用户 inputs/one.md", raw=b"Selected original text.\n"):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        return path

    def draft(self, sources=None, out="draft", title="User-selected content"):
        if sources is None:
            sources = [self.source()]
        result = preparation.prepare(sources, out, title, "user-supplied files")
        return Path(result["manifest"])

    def edit_manifest(self, manifest, change):
        value = json.loads(manifest.read_bytes())
        change(value)
        manifest.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        return value

    def assert_error(self, code, call):
        with self.assertRaises(AssemblyError) as caught:
            call()
        self.assertEqual(caught.exception.code, code, caught.exception.as_dict())

    def test_prepare_snapshots_exact_bytes_and_inspects_without_approval(self):
        first_raw = "# 原文\r\n\r\n采用 **方案 B**。\r\n".encode("utf-8")
        second_raw = ("Long paragraph " + "x" * 650).encode("utf-8")
        first = self.source(raw=first_raw)
        second = self.source("用户 inputs/第二份.txt", second_raw)
        result = preparation.prepare([first, second], "draft with spaces", "项目计划", "user selection", "正文")
        manifest = Path(result["manifest"])
        value = json.loads(manifest.read_bytes())
        self.assertEqual(result["block_ids"], ["block-0001", "block-0002"])
        self.assertEqual([b["order"] for b in value["blocks"]], [10, 20])
        for block, raw in zip(value["blocks"], [first_raw, second_raw]):
            self.assertFalse(block["approved"])
            self.assertNotIn("approval", block)
            self.assertEqual(block["section"], "正文")
            self.assertEqual(block["source"]["origin"], "user selection")
            self.assertEqual((manifest.parent / block["source"]["path"]).read_bytes(), raw)
            self.assertEqual(block["sha256"], digest(raw))
        self.assertEqual(value["blocks"][0]["source"]["reference"], {"prepared_from": "用户 inputs/one.md"})
        self.assertEqual(first.read_bytes(), first_raw)
        self.assertEqual(second.read_bytes(), second_raw)
        self.assert_error("UNAPPROVED_BLOCK", lambda: load_manifest(manifest))
        report = preparation.inspect_manifest(manifest)
        self.assertTrue(report["passed"])
        self.assertFalse(report["ready_to_build"])
        self.assertEqual(report["pending_approval"], result["block_ids"])
        self.assertEqual(report["issues"], [])
        self.assertEqual(report["blocks"][0]["text"], first_raw.decode())
        self.assertTrue(report["blocks"][0]["source_verified"])
        self.assertEqual(len(report["blocks"][1]["text"]), 600)
        self.assertTrue(report["blocks"][1]["text_truncated"])
        full = preparation.inspect_manifest(manifest, full_text=True)
        self.assertEqual(full["blocks"][1]["text"], second_raw.decode())
        self.assertFalse(full["blocks"][1]["text_truncated"])

    def test_adoption_rebases_sources_preserves_decision_and_builds_both_formats(self):
        manifest = self.draft([self.source(raw="# 采用内容\n\n零号清单：\n\n0. 第一步\n1. 第二步\n".encode()),
                               self.source("two.md", b"A [source](https://example.org).\n")])
        before = manifest.read_bytes()
        chosen = ["block-0001", "block-0002"]
        result = preparation.approve(manifest, chosen, "I adopt these two exact blocks.", "decisions/reviewed/approved.json")
        approved = Path(result["manifest"])
        self.assertTrue(result["ready_to_build"])
        self.assertEqual(result["approved_ids"], chosen)
        self.assertEqual(manifest.read_bytes(), before)
        original = json.loads(before)
        rows = json.loads(approved.read_bytes())["blocks"]
        for row, prior in zip(rows, original["blocks"]):
            self.assertEqual(row["approval"], {"decision": "I adopt these two exact blocks.", "sha256": prior["sha256"]})
            self.assertEqual(row["source"]["reference"], prior["source"]["reference"])
            self.assertEqual((approved.parent / row["source"]["path"]).resolve(), (manifest.parent / prior["source"]["path"]).resolve())
        self.assertTrue(preparation.inspect_manifest(approved)["ready_to_build"])
        result = build(approved, "delivery")
        self.assertTrue(result["passed"])
        snapshot = load_manifest(self.root / "delivery/manifest.snapshot.json")
        for name in ("final.md", "final.docx"):
            self.assertTrue(verify_loaded(snapshot, self.root / "delivery" / name)["passed"])
        self.assertEqual(snapshot["manifest"]["blocks"][0]["approval"], rows[0]["approval"])

    def test_partial_adoption_retains_prior_decision_when_finishing_other_block(self):
        manifest = self.draft([self.source(), self.source("two.md", b"Second text.\n")])
        first = preparation.approve(manifest, ["block-0001"], "Adopt first.", "first.json")
        self.assertFalse(first["ready_to_build"])
        self.assertEqual(first["pending_approval"], ["block-0002"])
        prior = Path(first["manifest"]).read_bytes()
        self.assert_error("UNAPPROVED_BLOCK", lambda: load_manifest(first["manifest"]))
        final = preparation.approve(first["manifest"], ["block-0002"], "Adopt second.", "decisions/final.json")
        self.assertTrue(final["ready_to_build"])
        rows = load_manifest(final["manifest"])["manifest"]["blocks"]
        self.assertEqual(rows[0]["approval"]["decision"], "Adopt first.")
        self.assertEqual(rows[1]["approval"]["decision"], "Adopt second.")
        self.assertEqual(Path(first["manifest"]).read_bytes(), prior)

    def test_unsupported_draft_is_visible_and_selected_failure_writes_nothing(self):
        manifest = self.draft([self.source(), self.source("image.md", b"![Image](https://example.org/image.png)\n")])
        report = preparation.inspect_manifest(manifest)
        self.assertTrue(report["passed"])
        self.assertFalse(report["blocks"][1]["supported"])
        self.assertEqual(report["blocks"][1]["text"], "![Image](https://example.org/image.png)\n")
        self.assertTrue(report["issues"])
        code = report["issues"][0]["code"]
        for ids in (["block-0002"], ["block-0001", "block-0002"]):
            with self.subTest(ids=ids):
                self.assert_error(code, lambda: preparation.approve(manifest, ids, "Adopt selection.", "blocked.json"))
                self.assertFalse((self.root / "blocked.json").exists())
        partial = preparation.approve(manifest, ["block-0001"], "Adopt supported first block.", "partial.json")
        self.assertFalse(partial["ready_to_build"])
        self.assertTrue(partial["issues"])
        self.assert_error("UNAPPROVED_BLOCK", lambda: build(partial["manifest"], "must-not-exist"))
        self.assertFalse((self.root / "must-not-exist").exists())

    def test_invalid_selection_and_empty_decision_never_partially_write(self):
        manifest = self.draft()
        cases = [(["unknown"], "Adopt.", "UNKNOWN_BLOCK"),
                 (["block-0001", "unknown"], "Adopt.", "UNKNOWN_BLOCK"),
                 (["block-0001", "block-0001"], "Adopt.", "DUPLICATE_SELECTION"),
                 ([], "Adopt.", "INVALID_SELECTION"),
                 (["block-0001"], "  ", "INVALID_APPROVAL")]
        for ids, decision, code in cases:
            with self.subTest(code=code, ids=ids):
                self.assert_error(code, lambda: preparation.approve(manifest, ids, decision, "invalid.json"))
                self.assertFalse((self.root / "invalid.json").exists())

    def test_source_drift_is_inspectable_blocks_adoption_and_restoring_recovers(self):
        manifest = self.draft()
        original_manifest = manifest.read_bytes()
        snapshot = manifest.parent / "sources/block-0001.md"
        original = snapshot.read_bytes()
        snapshot.write_bytes(b"Unapproved changed content.\n")
        report = preparation.inspect_manifest(manifest, full_text=True)
        self.assertEqual(report["issues"][0]["code"], "SOURCE_HASH_MISMATCH")
        self.assertFalse(report["blocks"][0]["source_verified"])
        self.assertEqual(report["blocks"][0]["sha256"], digest(original))
        self.assertEqual(report["blocks"][0]["text"], "Unapproved changed content.\n")
        self.assert_error("SOURCE_HASH_MISMATCH", lambda: preparation.approve(manifest, ["block-0001"], "Adopt.", "approved.json"))
        self.assertFalse((self.root / "approved.json").exists())
        self.assertEqual(manifest.read_bytes(), original_manifest)
        snapshot.write_bytes(original)
        self.assertTrue(preparation.approve(manifest, ["block-0001"], "Adopt restored bytes.", "approved.json")["ready_to_build"])
        self.assertEqual(manifest.read_bytes(), original_manifest)

    def test_missing_empty_and_non_utf8_drafts_report_issues_and_cannot_be_adopted(self):
        for index, (raw, expected) in enumerate([(b"\n \n", "EMPTY_BLOCK"), (b"\xff", "INVALID_UTF8"), (None, "MISSING_FILE")]):
            with self.subTest(expected=expected):
                source = self.source(f"input-{index}.md", raw if raw is not None else b"Present initially.\n")
                manifest = self.draft([source], out=f"draft-{index}")
                if raw is None:
                    (manifest.parent / "sources/block-0001.md").unlink()
                report = preparation.inspect_manifest(manifest)
                self.assertTrue(report["passed"])
                self.assertFalse(report["ready_to_build"])
                self.assertEqual(report["issues"][0]["code"], expected)
                self.assert_error(expected, lambda: preparation.approve(manifest, ["block-0001"], "Adopt.", f"blocked-{index}.json"))
                self.assertFalse((self.root / f"blocked-{index}.json").exists())

    def test_historical_source_audit_and_legacy_approval_are_preserved(self):
        manifest = self.draft([self.source(), self.source("replacement.md", b"Replacement content.\n")])

        def make_replacement(value):
            value["blocks"][0]["approved"] = True  # Legacy manifests have no approval record.
            value["blocks"][0]["source"]["reference"] = {"message_id": "original-reference"}
            value["blocks"][1]["replaces"] = "block-0001"

        self.edit_manifest(manifest, make_replacement)
        report = preparation.inspect_manifest(manifest)
        self.assertEqual(report["active_order"], ["block-0002"])
        self.assertEqual(report["blocks"][0]["replaced_by"], "block-0002")
        self.assertFalse(report["blocks"][0]["active"])
        self.assert_error("INACTIVE_BLOCK", lambda: preparation.approve(manifest, ["block-0001"], "Adopt.", "bad-history.json"))
        prior = manifest.parent / "sources/block-0001.md"
        original = prior.read_bytes()
        prior.write_bytes(b"Changed history.\n")
        self.assert_error("SOURCE_HASH_MISMATCH", lambda: preparation.approve(manifest, ["block-0002"], "Adopt.", "approved.json"))
        prior.write_bytes(original)
        approved = preparation.approve(manifest, ["block-0002"], "Adopt replacement.", "approved.json")
        loaded = load_manifest(approved["manifest"])
        self.assertEqual(loaded["records"]["block-0001"]["source"]["reference"], {"message_id": "original-reference"})
        self.assertNotIn("approval", loaded["records"]["block-0001"])
        self.assertEqual(loaded["replaced_by"], {"block-0001": "block-0002"})

    def test_legacy_active_approval_loads_but_mismatched_new_record_fails(self):
        manifest = self.draft()
        self.edit_manifest(manifest, lambda value: value["blocks"][0].update(approved=True))
        self.assertEqual(len(load_manifest(manifest)["active"]), 1)
        self.assertTrue(preparation.inspect_manifest(manifest)["ready_to_build"])
        self.edit_manifest(manifest, lambda value: value["blocks"][0].update(approval={"decision": "Adopt.", "sha256": "0" * 64}))
        self.assert_error("APPROVAL_HASH_MISMATCH", lambda: load_manifest(manifest))
        self.assert_error("APPROVAL_HASH_MISMATCH", lambda: preparation.inspect_manifest(manifest))

    def test_existing_outputs_are_never_overwritten_and_duplicate_inputs_fail(self):
        source = self.source()
        manifest = self.draft([source])
        prior = manifest.read_bytes()
        self.assert_error("OUTPUT_EXISTS", lambda: self.draft([source]))
        self.assert_error("OUTPUT_EXISTS", lambda: preparation.approve(manifest, ["block-0001"], "Adopt.", manifest))
        self.assertEqual(manifest.read_bytes(), prior)
        self.assert_error("DUPLICATE_SOURCE", lambda: self.draft([source, source], out="duplicate"))
        self.assertFalse((self.root / "duplicate").exists())

    def test_prepare_cleans_only_own_staging_after_failure_then_retries(self):
        source = self.source()
        sentinel = self.source("prepare-unrelated/keep.txt", b"Keep unrelated evidence.")
        before = set(self.root.iterdir())
        with patch.object(preparation, "write_json", side_effect=OSError("Simulated disk write failure")):
            with self.assertRaisesRegex(OSError, "Simulated"):
                self.draft([source])
        self.assertEqual(set(self.root.iterdir()), before)
        self.assertEqual(sentinel.read_bytes(), b"Keep unrelated evidence.")
        self.assertTrue(self.draft([source]).is_file())

    def test_prepare_detects_edit_after_snapshot_and_leaves_no_published_draft(self):
        source = self.source()
        original_read = preparation.read_bytes
        reads = 0

        def edit_before_second_source_read(path):
            nonlocal reads
            if Path(path) == source:
                reads += 1
                if reads == 2:
                    source.write_bytes(b"Changed during preparation.\n")
            return original_read(path)

        with patch.object(preparation, "read_bytes", side_effect=edit_before_second_source_read):
            self.assert_error("SOURCE_CHANGED_DURING_PREPARE", lambda: self.draft([source]))
        self.assertFalse((self.root / "draft").exists())
        self.assertEqual(list(self.root.glob("prepare-*")), [])
        recovered = self.draft([source])
        self.assertEqual((recovered.parent / "sources/block-0001.md").read_bytes(), source.read_bytes())

    def test_approve_rechecks_manifest_and_sources_before_writing(self):
        manifest = self.draft()
        original_load = preparation.load_manifest
        calls = 0

        def changed_manifest(path, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                self.edit_manifest(manifest, lambda value: value.update(title="Changed while adopting"))
            return original_load(path, **kwargs)

        with patch.object(preparation, "load_manifest", side_effect=changed_manifest):
            self.assert_error("MANIFEST_CHANGED", lambda: preparation.approve(manifest, ["block-0001"], "Adopt.", "approved.json"))
        self.assertFalse((self.root / "approved.json").exists())
        calls = 0

        def changed_source(path, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                (manifest.parent / "sources/block-0001.md").write_bytes(b"Changed source while adopting.\n")
            return original_load(path, **kwargs)

        with patch.object(preparation, "load_manifest", side_effect=changed_source):
            self.assert_error("SOURCE_HASH_MISMATCH", lambda: preparation.approve(manifest, ["block-0001"], "Adopt.", "approved.json"))
        self.assertFalse((self.root / "approved.json").exists())

    def test_adoption_failed_readback_removes_own_partial_file_then_recovers(self):
        manifest = self.draft()
        original = manifest.read_bytes()
        with patch.object(preparation, "read_bytes", return_value=b"Unexpected output bytes"):
            self.assert_error("APPROVAL_READBACK_FAILED", lambda: preparation.approve(manifest, ["block-0001"], "Adopt.", "approved.json"))
        self.assertFalse((self.root / "approved.json").exists())
        self.assertEqual(manifest.read_bytes(), original)
        self.assertTrue(preparation.approve(manifest, ["block-0001"], "Adopt after recovery.", "approved.json")["ready_to_build"])


if __name__ == "__main__":
    unittest.main()
