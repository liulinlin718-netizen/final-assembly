"""Markdown acceptance and independently mutated export checks."""

import unittest

from final_assembly.errors import AssemblyError
from final_assembly.markdown import parse_markdown, read_markdown, write_markdown


class MarkdownTests(unittest.TestCase):
    def test_source_bytes_preserved_including_crlf_and_eof(self):
        originals = [b"# Heading\r\n\r\nSoft\r\nwrap.\r\n", "末尾没有换行。".encode(), b"Text.\n\n"]
        blocks = [{"id": f"b{index}", "raw": raw} for index, raw in enumerate(originals)]
        exported = write_markdown(blocks)
        recovered = read_markdown(exported)
        self.assertEqual([block["raw"] for block in recovered], originals)
        self.assertEqual(recovered[0]["units"][1]["spans"], [{"text": "Soft wrap."}])

    def test_structural_content_table_links_and_list_numbers(self):
        units = parse_markdown("## Title\n\n- First\n- Second\n\n3. Third\n4. Fourth\n\n| Name | Link |\n| --- | --- |\n| 叶子 | [Docs](https://example.org/a_b?q=1&x=2) |\n| Empty | |\n")
        self.assertEqual(units[0], {"kind": "heading", "level": 2, "spans": [{"text": "Title"}]})
        self.assertNotIn("number", units[1])
        self.assertEqual(units[3]["number"], 3)
        self.assertEqual(units[5]["rows"][1][1], [{"text": "Docs", "url": "https://example.org/a_b?q=1&x=2"}])
        self.assertEqual(units[5]["rows"][2][1], [])

    def test_adjacent_equivalent_link_spans_merge(self):
        self.assertEqual(parse_markdown("[a](https://e.test)[b](https://e.test)")[0]["spans"], [{"text": "ab", "url": "https://e.test"}])

    def test_link_destination_scope_matches_docx(self):
        accepted = ["https://example.org/a_b?q=1&x=2", "http://example.org", "mailto:author@example.org"]
        rejected = ["#anchor", "./relative.md", "file:///D:/document.md", "javascript:alert", "https:///path", "mailto:", "https://"]
        for url in accepted:
            with self.subTest(url=url):
                self.assertEqual(parse_markdown(f"[link]({url})")[0]["spans"], [{"text": "link", "url": url}])
        for url in rejected:
            with self.subTest(url=url), self.assertRaises(AssemblyError):
                parse_markdown(f"[link]({url})")

    def test_rejects_unrepresented_markdown(self):
        cases = ["![alt](a.png)", "<div>x</div>", "- outer\n  - nested", "---", '[label](https://x.test "title")', "\ufefftext", "Paragraph\rline", "\u0000", "- [x] task"]
        for source in cases:
            with self.subTest(source=source), self.assertRaises(AssemblyError):
                parse_markdown(source)

    def test_table_row_length_fails_with_location(self):
        with self.assertRaises(AssemblyError) as raised:
            parse_markdown("| a | b |\n| --- | --- |\n| missing |\n")
        self.assertEqual(raised.exception.code, "NON_RECTANGULAR_TABLE")

    def test_commonmark_normalization_is_explicit(self):
        self.assertEqual(parse_markdown("Title\n=====")[0]["kind"], "heading")
        units = parse_markdown("1. one\n8. eight")
        self.assertEqual([u["number"] for u in units], [1, 2])
        self.assertEqual(parse_markdown("A &amp; B")[0]["spans"], [{"text": "A & B"}])
        self.assertEqual(parse_markdown("price $25 and snake_case")[0]["spans"], [{"text": "price $25 and snake_case"}])

    def test_frame_rejects_added_content_duplicate_and_malformed_markers(self):
        valid = write_markdown([{"id": "body", "raw": b"Approved."}])
        for bad in [b"Extra\n" + valid, valid + b"\n", valid + valid, valid.replace(b"end body", b"end other"), valid.replace(b"block body", b"block wrong id")]:
            with self.subTest(bad=bad), self.assertRaises(AssemblyError):
                read_markdown(bad)

    def test_mutated_raw_is_returned_as_mutated_without_guessing(self):
        valid = write_markdown([{"id": "body", "raw": b"Approved."}])
        self.assertEqual(read_markdown(valid.replace(b"Approved.", b"Changed."))[0]["raw"], b"Changed.")

    def test_different_units_cannot_be_written_over_source(self):
        with self.assertRaises(AssemblyError):
            write_markdown([{"id": "body", "raw": b"Actual.", "units": []}])

    def test_invalid_utf8_and_marker_injection_fail(self):
        for raw in [b"\xff", b"<!-- final-assembly:block other -->"]:
            with self.subTest(raw=raw), self.assertRaises(AssemblyError):
                write_markdown([{"id": "body", "raw": raw}])


if __name__ == "__main__":
    unittest.main()
