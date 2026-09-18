"""Release behavior: independent workspaces, portable deliveries, changed formatting."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile, ZIP_DEFLATED

from final_assembly.core import build, verify_loaded
from final_assembly.manifest import digest, load_manifest
from final_assembly.markdown import parse_markdown
from final_assembly.paths import ROOT, workspace

SOURCE = '''# 项目发布决定

采用 **方案 B**，费用为 $25，变量是 `project_id`。保留 *条件* 和 ~~旧结论~~。
第二行说明。  
这一行必须换行。

> 原文引述 **不可改写**。

## 实施步骤

1. 读取 [**官方资料**](https://example.org/docs?q=1&x=2)
1. 执行 `check()`

| 项目 | 金额 | 结果 |
| :--- | ---: | :---: |
| **工具** | $25 | *通过* |
| `a_b` | $12 | 保留 |

```python
value = "a_b"
print(value)
```
'''


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        parent = ROOT / ".runtime" / "release-tests"
        parent.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.materials = self.root / "用户 materials"
        self.materials.mkdir()
        raw = SOURCE.encode("utf-8")
        (self.materials / "approved.md").write_bytes(raw)
        manifest = {"schema_version": 1, "title": "Offline release fixture", "blocks": [{"id": "approved", "section": "Report", "order": 0, "source": {"path": "approved.md", "origin": "offline-test"}, "approved": True, "sha256": digest(raw)}]}
        (self.materials / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

    def test_common_markdown_roundtrip_and_portable_delivery(self):
        with workspace(self.materials):
            result = build("manifest.json", "delivery")
            self.assertTrue(result["passed"])
        moved = self.root / "moved delivery"
        shutil.move(self.materials / "delivery", moved)
        shutil.rmtree(self.materials)
        with workspace(moved):
            snapshot = load_manifest("manifest.snapshot.json")
            self.assertTrue(verify_loaded(snapshot, "final.docx")["passed"])
            self.assertTrue(verify_loaded(snapshot, "final.md")["passed"])

    def test_installed_skill_works_from_unrelated_cwd(self):
        install = self.root / "installed skill with spaces"
        install.mkdir()
        shutil.copy(ROOT / "skills/final-assembly/scripts/run.py", install / "run.py")
        shutil.copytree(ROOT / "final_assembly", install / "final_assembly", ignore=shutil.ignore_patterns("__pycache__"))
        # The material directory is outside the installation directory.
        process = subprocess.run([sys.executable, "-B", str(install / "run.py"), "--workspace", str(self.materials), "build", "manifest.json", "--out-dir", "delivery"], cwd=self.root, env=os.environ.copy(), capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(process.returncode, 0, process.stderr + process.stdout)
        self.assertTrue(json.loads(process.stdout)["passed"])
        self.assertEqual(sorted(p.name for p in install.iterdir()), ["final_assembly", "run.py"])

    def test_actual_formatting_mutations_fail_reconciliation(self):
        with workspace(self.materials):
            build("manifest.json", "delivery")
            loaded = load_manifest("manifest.json")
            source = self.materials / "delivery/final.docx"
            W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
            for tag in ("b", "i", "strike", "rFonts", "jc"):
                with self.subTest(tag=tag), ZipFile(source) as package:
                    entries = {name: package.read(name) for name in package.namelist()}
                tree = ET.fromstring(entries["word/document.xml"])
                node = tree.find(".//" + W + tag)
                self.assertIsNotNone(node)
                if tag == "rFonts":
                    node.set(W + "ascii", "Arial")
                elif tag == "jc":
                    node.set(W + "val", "right")
                else:
                    node.set(W + "val", "false")
                entries["word/document.xml"] = ET.tostring(tree, encoding="utf-8", xml_declaration=True)
                target = self.materials / f"mutated-{tag}.docx"
                with ZipFile(target, "w", ZIP_DEFLATED) as package:
                    for name, data in entries.items(): package.writestr(name, data)
                self.assertFalse(verify_loaded(loaded, target)["passed"], tag)

    def test_quotes_code_empty_lists_and_escaped_pipes_are_not_dropped(self):
        source = "> quote\n\n-\n- item\n\n| a | b |\n| --- | --- |\n| a\\|b | `code` |\n\n```\n```\n"
        raw = source.encode()
        manifest_path = self.materials / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["blocks"][0]["sha256"] = digest(raw)
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        (self.materials / "approved.md").write_bytes(raw)
        with workspace(self.materials):
            self.assertTrue(build("manifest.json", "delivery")["passed"])
