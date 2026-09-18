"""Caller-provided workspace paths use one consistent lexical boundary."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from final_assembly.manifest import digest
from final_assembly.paths import ROOT, checked_path, workspace


class WorkspaceInputTests(unittest.TestCase):
    def setUp(self):
        parent = ROOT / ".runtime" / "resume-review" / "workspace-tests"
        parent.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "parent").mkdir()
        self.materials = self.root / "用户 materials"
        self.materials.mkdir()
        self.alias = self.root / "parent" / ".." / self.materials.name
        raw = "# 批准材料\n\n保留本轮批准的 **交付条款**。\n".encode("utf-8")
        (self.materials / "正文.md").write_bytes(raw)
        manifest = {"schema_version": 1, "title": "Offline workspace regression", "blocks": [{"id": "body", "section": "正文", "order": 0, "source": {"path": "正文.md", "origin": "offline-test"}, "approved": True, "sha256": digest(raw)}]}
        (self.materials / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

    def test_parent_segment_workspace_matches_canonical_boundary(self):
        with workspace(self.alias) as actual:
            self.assertEqual(actual, self.materials)
            self.assertEqual(checked_path("manifest.json"), self.materials / "manifest.json")

    def test_cli_accepts_relative_parent_segment_with_unicode_and_spaces(self):
        relative_alias = str(Path("parent") / ".." / self.materials.name)
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(ROOT) + os.pathsep + environment.get("PYTHONPATH", "")
        result = subprocess.run([sys.executable, "-B", "-m", "final_assembly", "--workspace", relative_alias, "preview", "manifest.json"], cwd=self.root, env=environment, capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(json.loads(result.stdout)["passed"])


if __name__ == "__main__":
    unittest.main()
