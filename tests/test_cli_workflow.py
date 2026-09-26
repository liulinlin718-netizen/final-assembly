"""Actual command workflows and bounded receipts with complete disk evidence."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from final_assembly.manifest import digest
from final_assembly.paths import ROOT


class WorkflowCliTests(unittest.TestCase):
    def setUp(self):
        parent = ROOT / ".runtime" / "cli-workflow-tests"
        parent.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.materials = self.root / "用户 materials"
        self.materials.mkdir()
        self.env = os.environ.copy()
        self.env["PYTHONPATH"] = str(ROOT) + os.pathsep + self.env.get("PYTHONPATH", "")

    def cli(self, *args, code=0, material=None):
        process = subprocess.run([sys.executable, "-B", "-m", "final_assembly", "--workspace", str(material or self.materials), *args],
                                 cwd=self.root, env=self.env, capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(process.returncode, code, process.stderr + process.stdout)
        self.assertNotIn("Traceback", process.stderr)
        return json.loads(process.stdout), process.stdout

    def approved(self, rows=3):
        raw = ("# 已批准验收材料\n\n| 项目 | 证据 |\n| --- | --- |\n" +
               "".join(f"| value-{i} | [原文](https://example.org/{i}) |\n" for i in range(rows))).encode("utf-8")
        (self.materials / "source.md").write_bytes(raw)
        value = {"schema_version": 1, "title": "Explicit offline test approval", "blocks": [{"id": "chosen", "section": "Table", "order": 0,
                 "source": {"path": "source.md", "origin": "synthetic test fixture"}, "approved": True, "sha256": digest(raw)}]}
        (self.materials / "manifest.json").write_text(json.dumps(value), encoding="utf-8")

    def test_prepare_inspect_partial_approval_build_and_moved_snapshot(self):
        (self.materials / "first.md").write_text("# 采用正文\n\n保留 **原文**。\n", encoding="utf-8")
        (self.materials / "last.md").write_text("## 结尾\n\n0. 核验。\n1. 交付。\n", encoding="utf-8")
        prepared, _ = self.cli("prepare", "first.md", "last.md", "--out-dir", "draft", "--title", "Test", "--origin", "Synthetic selected notes")
        self.assertEqual(prepared["block_ids"], ["block-0001", "block-0002"])
        inspected, _ = self.cli("inspect", "draft/manifest.json", "--full-text")
        self.assertFalse(inspected["ready_to_build"])
        self.assertIn("保留 **原文**", inspected["blocks"][0]["text"])
        original = (self.materials / "draft/manifest.json").read_bytes()
        first, _ = self.cli("approve", "draft/manifest.json", "--ids", "block-0001", "--decision", "Synthetic adoption of first block", "--out-manifest", "decisions/first.json")
        self.assertEqual(first["pending_approval"], ["block-0002"])
        blocked, _ = self.cli("build", "decisions/first.json", "--out-dir", "blocked", "--summary", code=2)
        self.assertEqual(blocked["error"]["code"], "UNAPPROVED_BLOCK")
        self.assertTrue(Path(blocked["report_file"]).is_file())
        self.assertFalse((self.materials / "blocked").exists())
        self.cli("approve", "decisions/first.json", "--ids", "block-0002", "--decision", "Synthetic adoption of ending", "--out-manifest", "decisions/all.json")
        inspected, _ = self.cli("inspect", "decisions/all.json")
        self.assertTrue(inspected["ready_to_build"])
        built, _ = self.cli("build", "decisions/all.json", "--out-dir", "delivery", "--summary")
        self.assertTrue(built["passed"])
        self.assertEqual(original, (self.materials / "draft/manifest.json").read_bytes())
        moved = self.root / "moved delivery"
        shutil.move(self.materials / "delivery", moved)
        shutil.rmtree(self.materials)
        verified, _ = self.cli("verify", "manifest.snapshot.json", "--file", "final.docx", "--summary", "--report", "recheck.json", material=moved)
        self.assertTrue(verified["passed"])
        self.assertFalse(verified["visual_layout_checked"])

    def test_summary_is_small_and_complete_cell_evidence_stays_on_disk(self):
        self.approved(rows=263)  # 528 cells in both saved formats.
        receipt, stdout = self.cli("build", "manifest.json", "--out-dir", "delivery", "--summary")
        self.assertLess(len(stdout.encode("utf-8")), 8192)
        full = json.loads(Path(receipt["report_file"]).read_text(encoding="utf-8"))
        self.assertEqual([r["table_cells_checked"] for r in receipt["formats"]], [528, 528])
        self.assertEqual([len(r["table_cells"]) for r in full["formats"]], [528, 528])
        self.assertIn("actual", full["formats"][1]["table_cells"][-1])
        legacy, _ = self.cli("verify", "manifest.json", "--file", "delivery/final.md")
        self.assertEqual(len(legacy["table_cells"]), 528)
        self.assertNotIn("summary", legacy)

    def test_failed_verify_and_recovery_keep_full_reports_and_exit_contract(self):
        self.approved()
        self.cli("build", "manifest.json", "--out-dir", "delivery")
        target = self.materials / "delivery/final.md"
        original = target.read_bytes()
        target.write_bytes(original.replace(b"value-0", b"wrong-0"))
        failed, _ = self.cli("verify", "manifest.json", "--file", "delivery/final.md", "--summary", "--report", "failed.json", code=3)
        self.assertFalse(failed["passed"])
        self.assertGreater(failed["issue_count"], 0)
        full_bytes = (self.materials / "failed.json").read_bytes()
        self.assertIn("expected", json.loads(full_bytes)["issues"][0])
        target.write_bytes(original)
        self.cli("verify", "manifest.json", "--file", "delivery/final.md", "--summary", "--report", "recovered.json")
        self.cli("verify", "manifest.json", "--file", "delivery/final.md", "--summary", "--report", "failed.json", code=2)
        self.assertEqual(full_bytes, (self.materials / "failed.json").read_bytes())

    def test_summary_input_error_has_saved_evidence_and_no_delivery(self):
        self.approved()
        (self.materials / "source.md").write_text("Changed since approval\n", encoding="utf-8")
        result, _ = self.cli("build", "manifest.json", "--out-dir", "delivery", "--summary", code=2)
        self.assertEqual(result["error"]["code"], "SOURCE_HASH_MISMATCH")
        self.assertFalse((self.materials / "delivery").exists())
        full = json.loads(Path(result["report_file"]).read_text(encoding="utf-8"))
        self.assertEqual(full["error"]["code"], result["error"]["code"])


if __name__ == "__main__":
    unittest.main()
