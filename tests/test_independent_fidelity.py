"""Golden expectations independent of the exporter and its parsed source IR."""
import json
from pathlib import Path
import tempfile
import unittest
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from final_assembly.core import build, verify_loaded
from final_assembly.manifest import digest, load_manifest
from final_assembly.markdown import parse_markdown
from final_assembly.paths import ROOT, workspace

W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'


class IndependentFidelityTests(unittest.TestCase):
    def test_ordered_list_start_has_independent_zero_empty_and_nonzero_expectations(self):
        # The expected numbers are handwritten CommonMark semantics, not values
        # obtained from a second call to the parser or from a build report.
        cases = [
            ('0. First\n1. Second\n', [(0, 'First'), (1, 'Second')]),
            ('0.\n1. After empty\n', [(0, ''), (1, 'After empty')]),
            ('7. First\n1. Second\n', [(7, 'First'), (8, 'Second')]),
            ('1. First\n1. Second\n', [(1, 'First'), (2, 'Second')]),
        ]
        for source, expected_items in cases:
            with self.subTest(source=source):
                expected = [
                    {'kind': 'list_item', 'ordered': True, 'number': number,
                     'spans': [{'text': text}] if text else []}
                    for number, text in expected_items
                ]
                self.assertEqual(parse_markdown(source), expected)

    def test_saved_docx_zero_numbering_matches_golden_and_recovers_after_number_damage(self):
        parent = ROOT / '.runtime' / 'independent-tests'
        parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=parent) as temp, workspace(temp):
            root = Path(temp)
            source = (
                '0. First\n1. Second\n\nReset\n\n'
                '0.\n1. After empty\n\nNonzero\n\n'
                '7. Existing start\n1. Next item\n'
            )
            raw = source.encode('utf-8')
            (root / 'source.md').write_bytes(raw)
            manifest = {'schema_version': 1, 'title': 'Offline numbering fixture', 'blocks': [
                {'id': 'numbering', 'section': 'Numbering', 'order': 0, 'approved': True,
                 'source': {'path': 'source.md', 'origin': 'offline test approval'}, 'sha256': digest(raw)}]}
            (root / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
            self.assertTrue(build('manifest.json', 'delivery')['passed'])
            original_bytes = (root / 'delivery/final.docx').read_bytes()
            with ZipFile(root / 'delivery/final.docx') as archive:
                entries = {name: archive.read(name) for name in archive.namelist()}
            tree = ET.fromstring(entries['word/document.xml'])

            def numbered_paragraphs(document):
                return [
                    paragraph for paragraph in document.findall('.//' + W + 'sdtContent/' + W + 'p')
                    if paragraph.find(W + 'pPr/' + W + 'pStyle') is not None
                    and paragraph.find(W + 'pPr/' + W + 'pStyle').get(W + 'val') == 'FAListNumber'
                ]

            def paragraph_texts(paragraphs):
                return [''.join(node.text or '' for node in paragraph.iter(W + 't')) for paragraph in paragraphs]

            # Read real saved OOXML directly. No production reader or source IR
            # constructs the expected visible labels, including the empty item.
            expected = ['0. First', '1. Second', '0. ', '1. After empty', '7. Existing start', '8. Next item']
            paragraphs = numbered_paragraphs(tree)
            self.assertEqual(paragraph_texts(paragraphs), expected)
            markers = [ET.tostring(node) for node in tree.findall('.//' + W + 'sdtPr')]
            first_marker = paragraphs[0].find(W + 'r/' + W + 't')
            self.assertEqual(first_marker.text, '0. ')
            first_marker.text = '5. '
            entries['word/document.xml'] = ET.tostring(tree, encoding='utf-8', xml_declaration=True)
            with ZipFile(root / 'damaged.docx', 'w') as archive:
                for name, value in entries.items():
                    archive.writestr(name, value)
            with ZipFile(root / 'damaged.docx') as archive:
                damaged_tree = ET.fromstring(archive.read('word/document.xml'))
            self.assertEqual([ET.tostring(node) for node in damaged_tree.findall('.//' + W + 'sdtPr')], markers)
            self.assertEqual(paragraph_texts(numbered_paragraphs(damaged_tree)), ['5. First', *expected[1:]])
            report = verify_loaded(load_manifest('manifest.json'), root / 'damaged.docx')
            self.assertFalse(report['passed'])
            self.assertIn(
                {'code': 'STRUCTURE_MISMATCH', 'location': 'numbering.unit[1].number', 'expected': 0, 'actual': 5},
                report['issues'],
            )

            # Rebuild from the same approved bytes; do not silently reapprove the
            # changed number or derive recovery expectations from its output.
            self.assertTrue(build('manifest.json', 'recovered')['passed'])
            self.assertEqual((root / 'source.md').read_bytes(), raw)
            self.assertEqual((root / 'recovered/final.docx').read_bytes(), original_bytes)
            with ZipFile(root / 'recovered/final.docx') as archive:
                recovered_tree = ET.fromstring(archive.read('word/document.xml'))
            self.assertEqual(paragraph_texts(numbered_paragraphs(recovered_tree)), expected)
            self.assertTrue(verify_loaded(load_manifest('manifest.json'), root / 'recovered/final.docx')['passed'])

    def test_repeated_emphasis_keeps_outer_style_until_its_own_close(self):
        for source, key in [
            ('**Budget **approved** remains binding** outside', 'bold'),
            ('*Budget _approved_ remains binding* outside', 'italic'),
            ('~~Budget ~~approved~~ remains binding~~ outside', 'strike'),
        ]:
            with self.subTest(source=source):
                self.assertEqual(parse_markdown(source)[0]['spans'], [
                    {'text': 'Budget approved remains binding', key: True},
                    {'text': ' outside'},
                ])

    def test_nested_style_in_link_and_table_has_independent_expected_spans(self):
        source = '| Scope |\n| --- |\n| [**Budget __approved__ remains binding**](https://example.org/policy) |\n'
        cell = parse_markdown(source)[0]['rows'][1][0]
        self.assertEqual(cell, [{'text': 'Budget approved remains binding', 'bold': True, 'url': 'https://example.org/policy'}])

    def test_saved_docx_matches_golden_text_and_styles_and_rejects_body_damage(self):
        parent = ROOT / '.runtime' / 'independent-tests'
        parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=parent) as temp, workspace(temp):
            root = Path(temp)
            source = '**Budget **approved** remains binding** outside\n\n*Review _scope_ still applies* outside\n\n~~Obsolete ~~draft~~ withdrawn~~ outside\n'
            raw = source.encode()
            (root / 'source.md').write_bytes(raw)
            manifest = {'schema_version': 1, 'title': 'Offline fixture', 'blocks': [
                {'id': 'policy', 'section': 'Policy', 'order': 0, 'approved': True,
                 'source': {'path': 'source.md', 'origin': 'offline test approval'}, 'sha256': digest(raw)}]}
            (root / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
            self.assertTrue(build('manifest.json', 'delivery')['passed'])
            with ZipFile(root / 'delivery/final.docx') as archive:
                entries = {name: archive.read(name) for name in archive.namelist()}
            tree = ET.fromstring(entries['word/document.xml'])
            paragraphs = tree.findall('.//' + W + 'sdtContent/' + W + 'p')
            expected = [('Budget approved remains binding', 'b'), ('Review scope still applies', 'i'), ('Obsolete draft withdrawn', 'strike')]
            for paragraph, (text, prop) in zip(paragraphs, expected, strict=True):
                runs = paragraph.findall(W + 'r')
                self.assertEqual([''.join(t.text or '' for t in run.iter(W+'t')) for run in runs], [text, ' outside'])
                self.assertIsNotNone(runs[0].find(W + 'rPr/' + W + prop))
                self.assertIsNone(runs[1].find(W + 'rPr/' + W + prop))
            # Keep every SDT/block marker intact, only damage the visible text.
            first_text = tree.find('.//' + W + 't')
            first_text.text = 'An unapproved replacement'
            entries['word/document.xml'] = ET.tostring(tree, encoding='utf-8', xml_declaration=True)
            with ZipFile(root / 'damaged.docx', 'w') as archive:
                for name, value in entries.items():
                    archive.writestr(name, value)
            report = verify_loaded(load_manifest('manifest.json'), root / 'damaged.docx')
            self.assertFalse(report['passed'])
            self.assertTrue(any(issue['code'] == 'TEXT_OR_LINK_MISMATCH' for issue in report['issues']))
