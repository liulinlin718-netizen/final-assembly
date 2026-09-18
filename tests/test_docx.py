"""Actual package mutation checks; no LLM and no stored-content shortcut."""
import tempfile
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile, ZIP_DEFLATED

from final_assembly.docx_io import read_docx, read_docx_bytes, write_docx, W, R
from final_assembly.errors import AssemblyError
from final_assembly.paths import ROOT


def w(name):
    return f"{{{W}}}{name}"


BLOCKS = [
    {"id": "body-r2", "units": [
        {"kind": "heading", "level": 1, "spans": [{"text": "批准文稿 Approved draft"}]},
        {"kind": "paragraph", "spans": [{"text": "保留精确原文 "}, {"text": "证据", "url": "https://example.org/a?q=1&b=2"}, {"text": "。"}]},
        {"kind": "heading", "level": 2, "spans": [{"text": "执行步骤"}]},
        {"kind": "list_item", "ordered": False, "spans": [{"text": "核对内容"}]},
        {"kind": "list_item", "ordered": True, "number": 7, "spans": [{"text": "保留序号"}]},
    ]},
    {"id": "table-r4", "units": [{"kind": "table", "alignment": ["left", "left", "left"], "rows": [
        [[{"text": "编号"}], [{"text": "说明"}], [{"text": "链接"}]],
        [[{"text": "01"}], [], [{"text": "参考资料", "url": "https://example.org/reference"}]],
        [[{"text": "02"}], [{"text": "完整内容"}], [{"text": "邮件", "url": "mailto:hello@example.org"}]],
    ]}]},
    {"id": "ending-r7", "units": [{"kind": "paragraph", "spans": [{"text": "只有最终结尾。"}]}]},
]


class DocxRoundtripTests(unittest.TestCase):
    def setUp(self):
        root = ROOT / ".runtime" / "tests-docx"
        root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="case-", dir=root)
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "actual.docx"
        write_docx(BLOCKS, self.path)

    def mutate(self, change, part="word/document.xml"):
        with ZipFile(self.path) as package:
            members = {name: package.read(name) for name in package.namelist()}
        xml = ET.fromstring(members[part])
        change(xml)
        members[part] = ET.tostring(xml, encoding="utf-8", xml_declaration=True)
        output = Path(self.temp.name) / "mutated.docx"
        with ZipFile(output, "w", ZIP_DEFLATED) as package:
            for name, value in members.items():
                package.writestr(name, value)
        return output

    def assert_error(self, path, code=None):
        with self.assertRaises(AssemblyError) as raised:
            read_docx(path)
        if code:
            self.assertEqual(raised.exception.code, code)
        self.assertTrue(raised.exception.location)

    def test_actual_file_roundtrip(self):
        self.assertEqual(read_docx(self.path), BLOCKS)

    def test_byte_snapshot_roundtrip(self):
        frozen = self.path.read_bytes()
        self.path.write_bytes(b"replaced after capture")
        self.assertEqual(read_docx_bytes(frozen), BLOCKS)

    def test_docx_bytes_are_reproducible(self):
        second = Path(self.temp.name) / "second.docx"
        write_docx(BLOCKS, second)
        self.assertEqual(self.path.read_bytes(), second.read_bytes())

    def test_missing_table_row_is_observed(self):
        def remove(xml):
            table = xml.find(f".//{w('tbl')}")
            table.remove(table.findall(w("tr"))[1])
        result = read_docx(self.mutate(remove))
        self.assertEqual(len(result[1]["units"][0]["rows"]), 2)
        self.assertNotEqual(result, BLOCKS)

    def test_changed_text_comes_from_file(self):
        def edit(xml):
            xml.find(f".//{w('t')}").text = "未经批准的新标题"
        self.assertEqual(read_docx(self.mutate(edit))[0]["units"][0]["spans"][0]["text"], "未经批准的新标题")

    def test_changed_order_is_observed(self):
        def reorder(xml):
            body = xml.find(w("body"))
            first = body.find(w("sdt"))
            body.remove(first)
            body.insert(2, first)
        self.assertEqual([b["id"] for b in read_docx(self.mutate(reorder))], ["table-r4", "ending-r7", "body-r2"])

    def test_hyperlink_change_is_read_from_relationship(self):
        def change(xml):
            link = next(node for node in xml if node.get("Type") == f"{R}/hyperlink")
            link.set("Target", "https://example.org/changed")
        result = read_docx(self.mutate(change, "word/_rels/document.xml.rels"))
        self.assertEqual(result[0]["units"][1]["spans"][1]["url"], "https://example.org/changed")

    def test_broken_link_is_rejected(self):
        def change(xml):
            xml.find(f".//{w('hyperlink')}").set(f"{{{R}}}id", "missing")
        self.assert_error(self.mutate(change), "DOCX_LINK_INVALID")

    def test_javascript_link_is_rejected(self):
        def change(xml):
            next(node for node in xml if node.get("Type") == f"{R}/hyperlink").set("Target", "javascript:alert(1)")
        self.assert_error(self.mutate(change, "word/_rels/document.xml.rels"), "DOCX_LINK_INVALID")

    def test_unmarked_addition_is_rejected(self):
        def add(xml):
            paragraph = ET.Element(w("p"))
            run = ET.SubElement(paragraph, w("r"))
            ET.SubElement(run, w("t")).text = "偷偷增加"
            xml.find(w("body")).insert(0, paragraph)
        self.assert_error(self.mutate(add))

    def test_tracked_additions_are_rejected(self):
        def add(xml):
            ET.SubElement(xml.find(f".//{w('p')}"), w("ins"))
        self.assert_error(self.mutate(add))

    def test_hidden_run_is_rejected(self):
        def hide(xml):
            run = xml.find(f".//{w('r')}")
            props = ET.Element(w("rPr"))
            ET.SubElement(props, w("vanish"))
            run.insert(0, props)
        self.assert_error(self.mutate(hide))

    def test_duplicate_block_tag_is_rejected(self):
        def duplicate(xml):
            tags = xml.findall(f".//{w('tag')}")
            tags[1].set(w("val"), tags[0].get(w("val")))
        self.assert_error(self.mutate(duplicate), "DOCX_BLOCK_INVALID")

    def test_unknown_cell_content_is_rejected(self):
        def add(xml):
            ET.SubElement(xml.find(f".//{w('tc')}"), w("altChunk"))
        self.assert_error(self.mutate(add))

    def test_cell_merge_is_rejected(self):
        def add(xml):
            ET.SubElement(xml.find(f".//{w('tcPr')}"), w("gridSpan")).set(w("val"), "2")
        self.assert_error(self.mutate(add))

    def test_second_cell_paragraph_is_rejected(self):
        def add(xml):
            ET.SubElement(xml.find(f".//{w('tc')}"), w("p"))
        self.assert_error(self.mutate(add))

    def test_heading_style_mutation_changes_ir(self):
        def change(xml):
            xml.find(f".//{w('pStyle')}").set(w("val"), "Normal")
        self.assertEqual(read_docx(self.mutate(change))[0]["units"][0]["kind"], "paragraph")

    def test_list_marker_mutation_is_rejected(self):
        def change(xml):
            for node in xml.findall(f".//{w('t')}"):
                if node.text == "• ":
                    node.text = "? "
        self.assert_error(self.mutate(change), "DOCX_LIST_INVALID")

    def test_heading_definition_mutation_is_rejected(self):
        def change(xml):
            xml.find(f".//{w('outlineLvl')}").set(w("val"), "4")
        self.assert_error(self.mutate(change, "word/styles.xml"), "DOCX_STYLE_INVALID")

    def test_overwrite_is_rejected(self):
        with self.assertRaises(AssemblyError) as raised:
            write_docx(BLOCKS, self.path)
        self.assertEqual(raised.exception.code, "OUTPUT_EXISTS")

    def test_different_package_main_document_is_rejected(self):
        def change(xml):
            relation = next(node for node in xml if node.get("Type") == f"{R}/officeDocument")
            relation.set("Target", "word/styles.xml")
        self.assert_error(self.mutate(change, "_rels/.rels"), "DOCX_PACKAGE_INVALID")

    def test_macro_content_type_is_rejected(self):
        def change(xml):
            relation = next(node for node in xml if node.get("PartName") == "/word/document.xml")
            relation.set("ContentType", "application/vnd.ms-word.document.macroEnabled.main+xml")
        self.assert_error(self.mutate(change, "[Content_Types].xml"), "DOCX_PACKAGE_INVALID")

    def test_lost_significant_whitespace_is_rejected(self):
        def change(xml):
            for node in xml.findall(f".//{w('t')}"):
                if node.text and node.text.endswith(" "):
                    node.attrib.pop("{http://www.w3.org/XML/1998/namespace}space", None)
                    break
        self.assert_error(self.mutate(change), "DOCX_XML_INVALID")


if __name__ == "__main__":
    unittest.main()
