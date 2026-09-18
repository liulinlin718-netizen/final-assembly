import unittest
from final_assembly.compare import reconcile
from final_assembly.paths import parse_json
from final_assembly.errors import AssemblyError


class RegressionTests(unittest.TestCase):
    def test_missing_empty_cell_is_not_passed(self):
        expected = [{"id": "a", "sha256": "a" * 64, "units": [{"kind": "table", "rows": [[[], []]]}]}]
        actual = [{"id": "a", "units": [{"kind": "table", "rows": [[[]]]}]}]
        result = reconcile(expected, actual, "docx", "b" * 64)
        self.assertFalse(result["passed"])
        self.assertIsNone(result["table_cells"][1]["actual"])
        self.assertFalse(result["table_cells"][1]["passed"])

    def test_issue_cap_does_not_hide_later_block_failure(self):
        expected = [{"id": bid, "sha256": "a" * 64, "units": [{"kind": "paragraph", "spans": [{"text": "x"}]}] * 201} for bid in ("a", "b")]
        actual = [{"id": bid, "units": [{"kind": "paragraph", "spans": [{"text": "y"}]}] * 201} for bid in ("a", "b")]
        result = reconcile(expected, actual, "docx", "b" * 64)
        self.assertEqual(len(result["issues"]), 200)
        self.assertEqual(result["issue_count"], 402)
        self.assertFalse(any(b["passed"] for b in result["blocks"]))

    def test_nonstandard_json_numbers_rejected(self):
        for number in (b"NaN", b"Infinity", b"-Infinity"):
            with self.assertRaises(AssemblyError):
                parse_json(b'{"value":' + number + b'}')
