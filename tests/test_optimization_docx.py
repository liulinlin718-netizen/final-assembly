"""Independent fidelity, error-contract, and table-access regression checks."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from xml.etree import ElementTree as ET
from zipfile import ZipFile, ZIP_DEFLATED

from docx.table import Table, _Cell, _Row

from final_assembly.core import build, verify_loaded
from final_assembly.docx_io import read_docx, write_docx
from final_assembly.errors import AssemblyError
from final_assembly.manifest import digest, load_manifest
from final_assembly.markdown import parse_markdown
from final_assembly.paths import ROOT, workspace


W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
R = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'
OBSERVATIONS = {}


class OptimizationDocxTests(unittest.TestCase):
    def setUp(self):
        parent = ROOT / '.runtime' / 'optimization-implementation-20260925' / 'docx-tests'
        parent.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.context = workspace(self.root)
        self.context.__enter__()
        self.addCleanup(self.context.__exit__, None, None, None)

    def manifest(self, name, source, block_id='approved'):
        raw = source.encode('utf-8')
        (self.root / f'{name}.md').write_bytes(raw)
        data = {'schema_version': 1, 'title': 'Offline regression fixture', 'blocks': [
            {'id': block_id, 'section': 'Fixture', 'order': 0, 'approved': True,
             'source': {'path': f'{name}.md', 'origin': 'explicit offline test approval'},
             'sha256': digest(raw)}]}
        path = self.root / f'{name}.json'
        path.write_text(json.dumps(data), encoding='utf-8')
        return path

    def test_empty_link_labels_fail_instead_of_losing_the_target(self):
        cases = [
            'Keep [](https://example.org/audit-link) here.',
            '[](mailto:review@example.org)',
            '[Valid](https://example.org/audit-link)[](https://example.org/audit-link)',
            '[][audit]\n\n[audit]: https://example.org/audit-link\n',
            '| Audit |\n| --- |\n| [](https://example.org/audit-link) |\n',
        ]
        for source in cases:
            with self.subTest(source=source), self.assertRaises(AssemblyError) as raised:
                parse_markdown(source)
            self.assertEqual(raised.exception.code, 'UNSUPPORTED_MARKDOWN')
            self.assertIn('nonempty label', raised.exception.message)
        with self.assertRaises(AssemblyError) as raised:
            parse_markdown('Introduction.\n\nKeep [](https://example.org/audit-link) here.')
        self.assertEqual(raised.exception.location, {'line': 3})

    def test_valid_and_formatted_link_labels_have_handwritten_expectations(self):
        self.assertEqual(parse_markdown(
            'Keep [**Audit**](https://example.org/audit-link)[ trail](https://example.org/audit-link) here.'
        ), [{'kind': 'paragraph', 'spans': [
            {'text': 'Keep '},
            {'text': 'Audit', 'bold': True, 'url': 'https://example.org/audit-link'},
            {'text': ' trail', 'url': 'https://example.org/audit-link'},
            {'text': ' here.'},
        ]}])
        # The second link can merge into the preceding span and still has a
        # label: content must not be inferred from a change in span count.
        self.assertEqual(parse_markdown('[a](https://example.org)[b](https://example.org)'), [
            {'kind': 'paragraph', 'spans': [{'text': 'ab', 'url': 'https://example.org'}]},
        ])

    def test_empty_link_build_is_blocked_and_new_approved_label_recovers(self):
        bad = self.manifest('empty-label', 'Keep [](https://example.org/audit-link) here.')
        with self.assertRaises(AssemblyError) as raised:
            build(bad, 'blocked-delivery')
        self.assertEqual(raised.exception.code, 'UNSUPPORTED_MARKDOWN')
        self.assertFalse((self.root / 'blocked-delivery').exists())

        corrected = self.manifest('label-approved', 'Keep [**Audit**](https://example.org/audit-link) here.')
        self.assertTrue(build(corrected, 'recovered-link')['passed'])
        actual = self.root / 'recovered-link' / 'final.docx'
        with ZipFile(actual) as archive:
            document = ET.fromstring(archive.read('word/document.xml'))
            relationships = ET.fromstring(archive.read('word/_rels/document.xml.rels'))
        hyperlinks = document.findall('.//' + W + 'hyperlink')
        self.assertEqual(len(hyperlinks), 1)
        self.assertEqual(''.join(node.text or '' for node in hyperlinks[0].iter(W + 't')), 'Audit')
        self.assertIsNotNone(hyperlinks[0].find(W + 'r/' + W + 'rPr/' + W + 'b'))
        relation = next(node for node in relationships if node.get('Id') == hyperlinks[0].get(R + 'id'))
        self.assertEqual(relation.get('Target'), 'https://example.org/audit-link')
        self.assertTrue(verify_loaded(load_manifest(corrected), actual)['passed'])
        OBSERVATIONS['empty_link_recovery'] = {
            'empty_link_rejected': True, 'failed_delivery_absent': True,
            'recovered_label': 'Audit', 'recovered_url': relation.get('Target'),
        }

    def test_bad_table_counts_return_row_errors_and_rebuild_recovers(self):
        source = '| Item | Result |\n| :--- | ---: |\n| A | 10 |\n| B | 20 |\n'
        manifest = self.manifest('table', source, 'table-block')
        self.assertTrue(build(manifest, 'normal-table')['passed'])
        original = self.root / 'normal-table' / 'final.docx'
        original_bytes = original.read_bytes()
        with ZipFile(original) as archive:
            entries = {name: archive.read(name) for name in archive.namelist()}
        original_xml = ET.fromstring(entries['word/document.xml'])
        original_markers = [ET.tostring(node) for node in original_xml.findall('.//' + W + 'sdtPr')]
        cells = original_xml.findall('.//' + W + 'tc')
        self.assertEqual([''.join(t.text or '' for t in cell.iter(W + 't')) for cell in cells], ['Item', 'Result', 'A', '10', 'B', '20'])
        loaded = load_manifest(manifest)
        mutations = []
        for row_index in (0, 1):
            for action in ('extra', 'missing'):
                with self.subTest(row=row_index + 1, action=action):
                    document = copy.deepcopy(original_xml)
                    row = document.findall('.//' + W + 'tr')[row_index]
                    cell = row.findall(W + 'tc')[-1]
                    if action == 'extra':
                        row.append(copy.deepcopy(cell))
                    else:
                        row.remove(cell)
                    self.assertEqual([ET.tostring(node) for node in document.findall('.//' + W + 'sdtPr')], original_markers)
                    target = self.root / f'{action}-row-{row_index + 1}.docx'
                    changed = {**entries, 'word/document.xml': ET.tostring(document, encoding='utf-8', xml_declaration=True)}
                    with ZipFile(target, 'w', ZIP_DEFLATED) as archive:
                        for name, raw in changed.items():
                            archive.writestr(name, raw)
                    result = verify_loaded(loaded, target)
                    self.assertFalse(result['passed'])
                    self.assertEqual(result['issues'][0]['code'], 'DOCX_TABLE_INVALID')
                    self.assertEqual(result['issues'][0]['location'], f'table-block.units[1].rows[{row_index + 1}]')
                    mutations.append({'action': action, 'row': row_index + 1, 'issue': result['issues'][0]})

        self.assertTrue(verify_loaded(loaded, original)['passed'])
        self.assertTrue(build(manifest, 'recovered-table')['passed'])
        rebuilt = self.root / 'recovered-table' / 'final.docx'
        self.assertEqual(rebuilt.read_bytes(), original_bytes)
        self.assertTrue(verify_loaded(loaded, rebuilt)['passed'])
        OBSERVATIONS['table_count_recovery'] = {
            'mutations': mutations, 'block_markers_unchanged': True,
            'original_passed': True, 'rebuilt_passed': True, 'rebuild_bytes_identical': True,
        }

    def test_row_cache_materializes_each_cell_once_and_preserves_legacy_bytes(self):
        rows = [[[{'text': f'Column {col + 1}'}] for col in range(4)]]
        for number in range(1, 25):
            rows.append([
                [{'text': str(number)}],
                [{'text': f'批准项 {number}', 'bold': True}],
                [{'text': 'value', 'code': True}],
                [{'text': 'Audit', 'url': f'https://example.org/item/{number}'}],
            ])
        blocks = [{'id': 'cached-table', 'units': [{'kind': 'table', 'alignment': ['left', 'center', 'left', 'right'], 'rows': rows}]}]
        normal_row_cells = _Row.cells.fget
        normal_table_cells = Table._cells.fget
        normal_cell_init = _Cell.__init__
        counts = {'grid_calls': 0, 'grid_slots': 0, 'row_calls': 0, 'row_slots': 0, 'cell_proxies': 0}

        def count_grid(table):
            cells = normal_table_cells(table)
            counts['grid_calls'] += 1
            counts['grid_slots'] += len(cells)
            return cells

        def count_row(row):
            cells = normal_row_cells(row)
            counts['row_calls'] += 1
            counts['row_slots'] += len(cells)
            return cells

        def count_cell(cell, *args, **kwargs):
            counts['cell_proxies'] += 1
            normal_cell_init(cell, *args, **kwargs)

        optimized = self.root / 'optimized.docx'
        with patch.object(Table, '_cells', property(count_grid)), patch.object(_Row, 'cells', property(count_row)), patch.object(_Cell, '__init__', count_cell):
            write_docx(blocks, optimized)
        total_cells = len(rows) * 4
        self.assertEqual(counts, {'grid_calls': 0, 'grid_slots': 0, 'row_calls': len(rows), 'row_slots': total_cells, 'cell_proxies': total_cells})
        self.assertEqual(read_docx(optimized), blocks)
        optimized_counts = dict(counts)

        def legacy_row_cells(row):
            # Use the original per-cell public lookup, with the same writer,
            # to independently check proxy access does not change any ZIP bytes.
            return tuple(row.table.cell(row._index, column) for column in range(len(row._tr.tc_lst)))

        legacy = self.root / 'legacy-access.docx'
        counts.update({key: 0 for key in counts})
        with patch.object(_Row, 'cells', property(legacy_row_cells)), patch.object(Table, '_cells', property(count_grid)):
            write_docx(blocks, legacy)
        self.assertEqual(counts['grid_calls'], total_cells)
        self.assertEqual(counts['grid_slots'], total_cells * total_cells)
        self.assertEqual(optimized.read_bytes(), legacy.read_bytes())
        OBSERVATIONS['row_cache'] = {
            'cells': total_cells, 'optimized': optimized_counts,
            'legacy_grid_calls': counts['grid_calls'], 'legacy_grid_slots': counts['grid_slots'],
            'zip_bytes_identical': True,
        }


if __name__ == '__main__':
    unittest.main()
