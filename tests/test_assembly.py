import copy
import json
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from final_assembly.core import build, preview, verify_loaded
from final_assembly.errors import AssemblyError
from final_assembly.importer import import_pack
from final_assembly.manifest import digest, load_manifest
from final_assembly.markdown import read_markdown, write_markdown
from final_assembly.paths import ROOT, checked_path

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def mutate_docx(source, target, mutation, part="word/document.xml"):
    with zipfile.ZipFile(source) as zf:
        contents = {info.filename: zf.read(info.filename) for info in zf.infolist()}
    tree = ET.fromstring(contents[part])
    mutation(tree)
    contents[part] = ET.tostring(tree, encoding="utf-8", xml_declaration=True)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, raw in contents.items():
            zf.writestr(name, raw)


class AssemblyTests(unittest.TestCase):
    def setUp(self):
        temp_root = ROOT / ".runtime" / "tests"
        temp_root.mkdir(parents=True, exist_ok=True)
        self.work = Path(tempfile.mkdtemp(prefix="case-", dir=temp_root))
        shutil.copytree(ROOT / "examples" / "approved", self.work / "input")
        self.manifest = self.work / "input" / "manifest.json"
        self.document = json.loads(self.manifest.read_text(encoding="utf-8"))

    def tearDown(self):
        checked_path(self.work)
        shutil.rmtree(self.work)

    def save(self):
        self.manifest.write_text(json.dumps(self.document, ensure_ascii=False), encoding="utf-8")

    def expect_error(self, code):
        with self.assertRaises(AssemblyError) as ctx:
            load_manifest(self.manifest)
        self.assertEqual(ctx.exception.code, code)

    def output(self):
        build(self.manifest, self.work / "output")
        return self.work / "output"

    def test_build_reads_both_files_and_all_48_cells(self):
        output = self.output()
        receipt = json.loads((output / "reconciliation.json").read_text(encoding="utf-8"))
        self.assertTrue(receipt["passed"])
        self.assertFalse(receipt["visual_layout_checked"])
        for report in receipt["formats"]:
            self.assertEqual(report["actual_block_order"], ["body-r2", "table-r4", "ending-r7"])
            self.assertEqual(len(report["table_cells"]), 48)
            self.assertTrue(all(cell["passed"] for cell in report["table_cells"]))
            self.assertEqual(len(report["links"]), 2)
        snapshot = load_manifest(output / "manifest.snapshot.json")
        self.assertTrue(verify_loaded(snapshot, output / "final.docx")["passed"])

    def test_duplicate_id(self):
        self.document["blocks"].append(copy.deepcopy(self.document["blocks"][0]))
        self.save()
        self.expect_error("DUPLICATE_ID")

    def test_active_draft(self):
        self.document["blocks"][0]["approved"] = False
        self.save()
        self.expect_error("UNAPPROVED_BLOCK")

    def test_missing_source(self):
        (self.work / "input" / "sources" / "round-2.md").unlink()
        self.expect_error("MISSING_FILE")

    def test_hash_change_and_recovery(self):
        source = self.work / "input" / "sources" / "round-2.md"
        raw = source.read_bytes()
        source.write_bytes(raw + b"change")
        self.expect_error("SOURCE_HASH_MISMATCH")
        source.write_bytes(raw)
        self.assertTrue(preview(self.manifest)["passed"])

    def test_historical_source_audited(self):
        (self.work / "input" / "sources" / "round-5.md").write_text("changed", encoding="utf-8")
        self.expect_error("SOURCE_HASH_MISMATCH")

    def test_duplicate_active_order(self):
        self.document["blocks"][0]["order"] = 20
        self.save()
        self.expect_error("DUPLICATE_ORDER")

    def test_replacement_cycle(self):
        self.document["blocks"][2]["replaces"] = "ending-r7"
        self.save()
        self.expect_error("REPLACEMENT_CYCLE")

    def test_replacement_conflict(self):
        self.document["blocks"][0]["replaces"] = "ending-r5"
        self.save()
        self.expect_error("REPLACEMENT_CONFLICT")

    def test_missing_replacement(self):
        self.document["blocks"][3]["replaces"] = "absent"
        self.save()
        self.expect_error("MISSING_REPLACEMENT")

    def test_source_outside_project(self):
        self.document["blocks"][0]["source"]["path"] = str(ROOT.parent / "outside-workspace.md")
        self.save()
        self.expect_error("PATH_OUTSIDE_WORKSPACE")

    def test_unknown_fields_and_json_duplicates(self):
        self.document["blocks"][0]["approve"] = True
        self.save()
        self.expect_error("UNKNOWN_FIELD")
        self.manifest.write_text('{"schema_version":1,"schema_version":1}', encoding="utf-8")
        self.expect_error("DUPLICATE_JSON_KEY")

    def test_unrepresented_format_rejected(self):
        source = self.work / "input" / "sources" / "round-2.md"
        raw = b"# Title\n\n![unsupported](image.png)\n"
        source.write_bytes(raw)
        self.document["blocks"][0]["sha256"] = digest(raw)
        self.save()
        self.expect_error("UNSUPPORTED_MARKDOWN")

    def test_immutable_output_and_deterministic_markdown(self):
        output = self.output()
        with self.assertRaises(AssemblyError) as ctx:
            build(self.manifest, output)
        self.assertEqual(ctx.exception.code, "OUTPUT_EXISTS")
        build(self.manifest, self.work / "output2")
        self.assertEqual((output / "final.md").read_bytes(), (self.work / "output2/final.md").read_bytes())

    def test_markdown_mutations_and_recovery(self):
        output = self.output()
        expected = load_manifest(self.manifest)
        original = (output / "final.md").read_bytes()
        variants = {
            "missing-row": original.replace(next(x for x in original.splitlines(keepends=True) if x.startswith(b"| 04 |")), b""),
            "bad-link": original.replace(b"https://example.com/body", b"https://example.com/wrong"),
            "extra-content": original + b"Unexpected prose\n",
            "wrong-order": write_markdown(list(reversed(read_markdown(original)))),
        }
        for name, raw in variants.items():
            with self.subTest(name=name):
                file = self.work / (name + ".md")
                file.write_bytes(raw)
                result = verify_loaded(expected, file)
                self.assertFalse(result["passed"])
                self.assertTrue(result["issues"])
        build(self.manifest, self.work / "recovered")
        self.assertTrue(verify_loaded(expected, self.work / "recovered/final.md")["passed"])

    def test_docx_missing_row_exact_location(self):
        output = self.output()
        file = self.work / "missing-row.docx"
        def change(tree):
            table = tree.find(".//" + W + "tbl")
            table.remove(table.findall(W + "tr")[4])
        mutate_docx(output / "final.docx", file, change)
        result = verify_loaded(load_manifest(self.manifest), file)
        self.assertFalse(result["passed"])
        self.assertTrue(any("table-r4.unit[2].table" in str(i.get("location")) for i in result["issues"]))

    def test_docx_wrong_order(self):
        output = self.output()
        file = self.work / "wrong-order.docx"
        def change(tree):
            body = tree.find(W + "body")
            blocks = body.findall(W + "sdt")
            body.remove(blocks[0])
            body.insert(1, blocks[0])
        mutate_docx(output / "final.docx", file, change)
        result = verify_loaded(load_manifest(self.manifest), file)
        self.assertFalse(result["passed"])
        self.assertEqual(result["issues"][0]["code"], "BLOCK_ORDER_OR_SET_MISMATCH")

    def test_docx_wrong_link(self):
        output = self.output()
        file = self.work / "bad-link.docx"
        def change(tree):
            for rel in tree:
                if rel.get("Type", "").endswith("/hyperlink"):
                    rel.set("Target", "https://example.com/wrong")
        mutate_docx(output / "final.docx", file, change, "word/_rels/document.xml.rels")
        result = verify_loaded(load_manifest(self.manifest), file)
        self.assertFalse(result["passed"])
        self.assertTrue(any(not link["passed"] for link in result["links"]))

    def test_docx_extra_content(self):
        output = self.output()
        file = self.work / "extra.docx"
        def change(tree):
            para = ET.Element(W + "p")
            ET.SubElement(ET.SubElement(para, W + "r"), W + "t").text = "Extra"
            tree.find(W + "body").insert(0, para)
        mutate_docx(output / "final.docx", file, change)
        self.assertFalse(verify_loaded(load_manifest(self.manifest), file)["passed"])

    def test_new_approved_version_replaces_previous(self):
        row = copy.deepcopy(self.document["blocks"][3])
        row["id"], row["replaces"] = "ending-r8", "ending-r7"
        raw = "## 新版结尾\n\n已批准修订：交付日期调整为九月二十五日。\n".encode("utf-8")
        (self.work / "input/sources/round-8.md").write_bytes(raw)
        row["source"] = {"path": "sources/round-8.md", "origin": "offline-demo:round-8"}
        row["sha256"] = digest(raw)
        self.document["blocks"].append(row)
        self.save()
        self.assertEqual([b["id"] for b in load_manifest(self.manifest)["active"]], ["body-r2", "table-r4", "ending-r8"])
        output = self.output()
        self.assertIn(raw, (output / "final.md").read_bytes())
        self.assertNotIn((self.work / "input/sources/round-7.md").read_bytes(), (output / "final.md").read_bytes())

    def test_pack_import_is_exact_and_never_approves(self):
        result = import_pack(ROOT / "examples/reference-pack.json", self.work / "import")
        self.assertFalse(result["approved"])
        with self.assertRaises(AssemblyError) as ctx:
            load_manifest(result["manifest"])
        self.assertEqual(ctx.exception.code, "UNAPPROVED_BLOCK")
        raw = (self.work / "import/sources/block-0001.md").read_bytes()
        self.assertEqual(raw, (ROOT / "examples/approved/sources/round-2.md").read_bytes())


if __name__ == "__main__":
    unittest.main()
