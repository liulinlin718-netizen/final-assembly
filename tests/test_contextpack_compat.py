"""Real producer export compatibility, provenance, failure and recovery checks.

REAL_EXPORTS below are frozen, byte-for-byte JSON outputs from Context Relay's
actual importHistory/createPack/validatePack run on 2026-09-25. They are synthetic
review materials, not real user approvals. Keeping them here makes the consumer
tests portable without importing a sibling project's runtime or rewriting inputs.
"""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from final_assembly.errors import AssemblyError
from final_assembly.importer import import_pack
from final_assembly.manifest import load_manifest
from final_assembly.paths import ROOT, checked_path, workspace


REAL_EXPORTS = {
    'known-source-full-message': b'{\n  "schemaVersion": "1",\n  "packId": "pack-92eac16f-e396-438a-b958-a4def39f3573",\n  "createdAt": "2026-09-25T07:02:48.694Z",\n  "excerpts": [\n    {\n      "id": "excerpt-98719151-2558-4704-9e81-2dedf10f7f26",\n      "label": "\xe5\xbc\x95\xe7\x94\xa8 1",\n      "selectionOrder": 1,\n      "sourceLocalId": "import-m000001",\n      "sourceThreadId": "synthetic-thread",\n      "sourceTurnId": null,\n      "sourceItemId": null,\n      "sourceUri": null,\n      "sourceKind": "imported-transcript",\n      "role": "assistant",\n      "timestamp": null,\n      "exactText": "# Approved text\\n\\nKeep this paragraph.\\n\\nOther discussion.",\n      "sourceHash": "55c367ac86d89c7bb4f7326a58870b935e454443b3c4abeba5c843f93d017055",\n      "excerptHash": "55c367ac86d89c7bb4f7326a58870b935e454443b3c4abeba5c843f93d017055",\n      "sourceLength": 56,\n      "range": {\n        "start": 0,\n        "end": 56,\n        "unit": "utf16"\n      }\n    }\n  ],\n  "memory": [],\n  "question": ""\n}',
    'known-source-excerpt': b'{\n  "schemaVersion": "1",\n  "packId": "pack-017c40e1-cafd-4c82-a9b9-fa8d04448ef2",\n  "createdAt": "2026-09-25T07:02:48.720Z",\n  "excerpts": [\n    {\n      "id": "excerpt-b31b6b2c-868e-460f-951b-68f137451350",\n      "label": "\xe5\xbc\x95\xe7\x94\xa8 1",\n      "selectionOrder": 1,\n      "sourceLocalId": "import-m000001",\n      "sourceThreadId": "synthetic-thread",\n      "sourceTurnId": null,\n      "sourceItemId": null,\n      "sourceUri": null,\n      "sourceKind": "imported-transcript",\n      "role": "assistant",\n      "timestamp": null,\n      "exactText": "# Approved text",\n      "sourceHash": "55c367ac86d89c7bb4f7326a58870b935e454443b3c4abeba5c843f93d017055",\n      "excerptHash": "7f9177ea6b86c915d7500a0ea41f58b76a904b77dcbee9a0fb23b9c34d70ad70",\n      "sourceLength": 56,\n      "range": {\n        "start": 0,\n        "end": 15,\n        "unit": "utf16"\n      }\n    }\n  ],\n  "memory": [],\n  "question": ""\n}',
    'unknown-source-full-message': b'{\n  "schemaVersion": "1",\n  "packId": "pack-c71bf702-6fba-4094-8fe2-214dc7b54765",\n  "createdAt": "2026-09-25T07:02:48.727Z",\n  "excerpts": [\n    {\n      "id": "excerpt-16e199bf-ada6-4cbf-8a0a-bdd0742edff5",\n      "label": "\xe5\xbc\x95\xe7\x94\xa8 1",\n      "selectionOrder": 1,\n      "sourceLocalId": "import-m000001",\n      "sourceThreadId": null,\n      "sourceTurnId": null,\n      "sourceItemId": null,\n      "sourceUri": null,\n      "sourceKind": "imported-transcript",\n      "role": "assistant",\n      "timestamp": null,\n      "exactText": "# Approved text\\n\\nKeep this paragraph.\\n\\nOther discussion.",\n      "sourceHash": "55c367ac86d89c7bb4f7326a58870b935e454443b3c4abeba5c843f93d017055",\n      "excerptHash": "55c367ac86d89c7bb4f7326a58870b935e454443b3c4abeba5c843f93d017055",\n      "sourceLength": 56,\n      "range": {\n        "start": 0,\n        "end": 56,\n        "unit": "utf16"\n      }\n    }\n  ],\n  "memory": [],\n  "question": ""\n}',
    'rollout-full-message': b'{\n  "schemaVersion": "1",\n  "packId": "pack-82df5698-ee39-4928-8b23-29a3c080a0a3",\n  "createdAt": "2026-09-25T07:02:48.729Z",\n  "excerpts": [\n    {\n      "id": "excerpt-13c407ed-e71c-40ab-be0b-67770e1d4e36",\n      "label": "\xe5\xbc\x95\xe7\x94\xa8 1",\n      "selectionOrder": 1,\n      "sourceLocalId": "import-m000001",\n      "sourceThreadId": "synthetic-thread",\n      "sourceTurnId": null,\n      "sourceItemId": null,\n      "sourceUri": null,\n      "sourceKind": "codex-rollout",\n      "role": "assistant",\n      "timestamp": null,\n      "exactText": "# Approved text\\n\\nKeep this paragraph.\\n\\nOther discussion.",\n      "sourceHash": "55c367ac86d89c7bb4f7326a58870b935e454443b3c4abeba5c843f93d017055",\n      "excerptHash": "55c367ac86d89c7bb4f7326a58870b935e454443b3c4abeba5c843f93d017055",\n      "sourceLength": 56,\n      "range": {\n        "start": 0,\n        "end": 56,\n        "unit": "utf16"\n      }\n    }\n  ],\n  "memory": [],\n  "question": ""\n}',
}
REAL_EXPORT_SHA256 = {'known-source-full-message': '7c919903e29b4217be4ed5f57883482481ea33aade52a67ddb90dd33da935c8a', 'known-source-excerpt': '0ea67d330970bfaa27851e9b46d668d363233c905fcd98f7ed3c422ff4d6f0de', 'unknown-source-full-message': '3a8b0f94fc7c48dbb1d38c222d6db58c9d5932ff16ad9d9cf66e32b3febbf0f7', 'rollout-full-message': '5318ddceb038ec3f90030836b8a88483424b17787a0deebda8dabd553c528487'}


class ContextPackCompatibilityTests(unittest.TestCase):
    def setUp(self):
        test_root = ROOT / ".runtime/tests"
        test_root.mkdir(parents=True, exist_ok=True)
        self.work = Path(tempfile.mkdtemp(prefix="contextpack-", dir=test_root))
        self.scope = workspace(self.work)
        self.scope.__enter__()

    def tearDown(self):
        checked_path(self.work)
        self.scope.__exit__(None, None, None)
        shutil.rmtree(self.work)

    def pack(self, name="known-source-full-message"):
        return json.loads(REAL_EXPORTS[name])

    def write_pack(self, pack, name="input.json"):
        path = self.work / name
        path.write_text(json.dumps(pack, ensure_ascii=True), encoding="utf-8")
        return path

    def imported(self, pack, name="imported"):
        target = self.work / name
        receipt = import_pack(self.write_pack(pack), target)
        manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
        return receipt, manifest, target

    def rejected(self, pack, code=None):
        target = self.work / "rejected"
        with self.assertRaises(AssemblyError) as caught:
            import_pack(self.write_pack(pack), target)
        if code:
            self.assertEqual(caught.exception.code, code)
        self.assertFalse(target.exists())
        self.assertFalse(list(self.work.glob("import-*")))
        return caught.exception

    def test_four_frozen_real_producer_exports_import_without_approval(self):
        self.assertEqual(set(REAL_EXPORTS), {"known-source-full-message", "known-source-excerpt", "unknown-source-full-message", "rollout-full-message"})
        for name, raw in REAL_EXPORTS.items():
            with self.subTest(case=name):
                self.assertEqual(hashlib.sha256(raw).hexdigest(), REAL_EXPORT_SHA256[name])
                source = self.work / (name + ".json")
                source.write_bytes(raw)
                target = self.work / name
                result = import_pack(source, target)
                pack = json.loads(raw)
                manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
                self.assertFalse(result["approved"])
                self.assertEqual(json.loads((target / "context-pack.json").read_text(encoding="utf-8")), pack)
                self.assertEqual(len(manifest["blocks"]), len(pack["excerpts"]))
                for row, excerpt in zip(manifest["blocks"], pack["excerpts"]):
                    original = excerpt["exactText"].encode("utf-8")
                    self.assertEqual((target / row["source"]["path"]).read_bytes(), original)
                    self.assertEqual(row["sha256"], hashlib.sha256(original).hexdigest())
                    self.assertEqual(row["source"]["reference"], {key: value for key, value in excerpt.items() if key != "exactText"})
                    self.assertFalse(row["approved"])
                with self.assertRaises(AssemblyError) as caught:
                    load_manifest(target / "manifest.json")
                self.assertEqual(caught.exception.code, "UNAPPROVED_BLOCK")

    def test_tampered_excerpt_text_excerpt_hash_and_complete_source_hash_fail(self):
        for field, replacement in (("exactText", "# Approved text\n\nDrop this paragraph.\n\nOther discussion."),
                                   ("excerptHash", "0" * 64), ("sourceHash", "0" * 64)):
            with self.subTest(field=field):
                pack = self.pack()
                pack["excerpts"][0][field] = replacement
                self.rejected(pack, "PACK_HASH_MISMATCH")

    def test_fragment_source_hash_is_preserved_not_claimed_verified(self):
        pack = self.pack("known-source-excerpt")
        pack["excerpts"][0]["sourceHash"] = "b" * 64
        receipt, manifest, _ = self.imported(pack)
        self.assertEqual(manifest["blocks"][0]["source"]["reference"]["sourceHash"], "b" * 64)
        self.assertEqual(receipt["integrity"]["excerpt_hashes_verified"], 1)
        self.assertEqual(receipt["integrity"]["full_message_hashes_verified"], 0)
        self.assertEqual(receipt["integrity"]["source_hashes_preserved_without_full_message_verification"], 1)

    def test_invalid_ranges_are_structured_errors_without_output(self):
        changes = [
            {"range": {"start": -1, "end": 55, "unit": "utf16"}},
            {"range": {"start": True, "end": 56, "unit": "utf16"}},
            {"range": {"start": "0", "end": 56, "unit": "utf16"}},
            {"range": {"start": 1, "end": 57, "unit": "utf16"}},
            {"range": {"start": 0, "end": 55, "unit": "utf16"}},
            {"range": {"start": 56, "end": 56, "unit": "utf16"}},
            {"range": {"start": 0, "end": 56, "unit": "bytes"}},
            {"range": None}, {"range": []}, {"sourceLength": False}, {"sourceLength": "56"},
        ]
        for change in changes:
            with self.subTest(change=change):
                pack = self.pack()
                pack["excerpts"][0].update(change)
                self.rejected(pack, "PACK_RANGE")
        pack = self.pack()
        del pack["excerpts"][0]["range"]
        self.rejected(pack, "PACK_SCHEMA")

    def test_utf16_range_counts_astral_character_twice(self):
        pack = self.pack()
        excerpt = pack["excerpts"][0]
        excerpt.update(exactText="A😀B", sourceLength=4, range={"start": 0, "end": 4, "unit": "utf16"})
        excerpt["sourceHash"] = excerpt["excerptHash"] = hashlib.sha256("A😀B".encode("utf-8")).hexdigest()
        receipt, _, target = self.imported(pack)
        self.assertTrue(receipt["passed"])
        self.assertEqual((target / "sources/block-0001.md").read_bytes(), "A😀B".encode("utf-8"))
        excerpt["range"]["end"] = 3
        self.rejected(pack, "PACK_RANGE")

    def test_invalid_unicode_is_a_pack_error(self):
        pack = self.pack()
        pack["excerpts"][0]["exactText"] = "\ud800"
        self.rejected(pack, "PACK_TEXT")

    def test_nullable_locator_fields_remain_null(self):
        pack = self.pack()
        for field in ("sourceThreadId", "sourceTurnId", "sourceItemId", "sourceUri"):
            pack["excerpts"][0][field] = None
        _, manifest, _ = self.imported(pack)
        reference = manifest["blocks"][0]["source"]["reference"]
        for field in ("sourceThreadId", "sourceTurnId", "sourceItemId", "sourceUri"):
            self.assertIn(field, reference)
            self.assertIsNone(reference[field])

    def test_unknown_source_kind_and_invalid_metadata_are_rejected(self):
        changes = [({"sourceKind": "invented-kind"}, "PACK_SOURCE"), ({"sourceKind": []}, "PACK_SOURCE"),
                   ({"sourceThreadId": ""}, "PACK_SOURCE"), ({"sourceThreadId": 1}, "PACK_SOURCE"),
                   ({"role": {}}, "PACK_ROLE"), ({"role": "robot"}, "PACK_ROLE"),
                   ({"timestamp": "not-a-date"}, "PACK_TIMESTAMP"),
                   ({"selectionOrder": True}, "PACK_ORDER")]
        for change, code in changes:
            with self.subTest(change=change):
                pack = self.pack()
                pack["excerpts"][0].update(change)
                self.rejected(pack, code)

    def test_producer_roles_are_data_and_never_approval(self):
        for role in ("user", "assistant", "tool", "system", "developer", "unknown"):
            with self.subTest(role=role):
                pack = self.pack()
                pack["excerpts"][0]["role"] = role
                receipt, manifest, _ = self.imported(pack, role)
                self.assertFalse(receipt["approved"])
                self.assertEqual(manifest["blocks"][0]["source"]["reference"]["role"], role)

    def test_hash_prefix_compatibility_does_not_rewrite_reference(self):
        pack = self.pack()
        for field in ("sourceHash", "excerptHash"):
            pack["excerpts"][0][field] = "sha256:" + pack["excerpts"][0][field]
        _, manifest, _ = self.imported(pack)
        reference = manifest["blocks"][0]["source"]["reference"]
        self.assertEqual(reference["sourceHash"], pack["excerpts"][0]["sourceHash"])
        self.assertEqual(reference["excerptHash"], pack["excerpts"][0]["excerptHash"])

    def test_malformed_or_missing_hashes_are_rejected(self):
        for field, value in (("sourceHash", "no-hash"), ("excerptHash", None), ("sourceHash", [])):
            with self.subTest(field=field, value=value):
                pack = self.pack()
                pack["excerpts"][0][field] = value
                self.rejected(pack, "PACK_HASH")

    def test_legacy_complete_message_has_explicit_compatibility_notice(self):
        for prefixed in (False, True):
            with self.subTest(prefixed=prefixed):
                pack = self.pack()
                ex = pack["excerpts"][0]
                del ex["excerptHash"]
                if prefixed:
                    ex["sourceHash"] = "sha256:" + ex["sourceHash"]
                receipt, manifest, _ = self.imported(pack, "legacy-" + str(prefixed))
                self.assertEqual(receipt["integrity"]["legacy_full_messages"], 1)
                self.assertEqual(receipt["integrity"]["full_message_hashes_verified"], 0)
                self.assertEqual(receipt["compatibility"]["legacy_whole_message_ids"], [ex["id"]])
                self.assertIn("legacy-whole-message", receipt["note"])
                self.assertEqual(manifest["blocks"][0]["source"]["reference"]["sourceHash"], ex["sourceHash"])

    def test_existing_legacy_example_remains_supported(self):
        pack = json.loads((ROOT / "examples/reference-pack.json").read_bytes())
        receipt, manifest, target = self.imported(pack)
        self.assertFalse(receipt["approved"])
        self.assertEqual(receipt["integrity"]["legacy_full_messages"], 1)
        self.assertEqual((target / manifest["blocks"][0]["source"]["path"]).read_bytes(), pack["excerpts"][0]["exactText"].encode("utf-8"))

    def test_legacy_fragment_rehash_does_not_disguise_partial_range(self):
        for rehashed in (False, True):
            with self.subTest(rehashed=rehashed):
                pack = self.pack("known-source-excerpt")
                ex = pack["excerpts"][0]
                selected_hash = ex.pop("excerptHash")
                if rehashed:
                    ex["sourceHash"] = selected_hash
                error = self.rejected(pack, "PACK_HASH_MIGRATION_REQUIRED")
                self.assertIn("excerptHash", error.message)

    def test_ambiguous_legacy_provenance_requires_migration(self):
        for missing in ("range", "sourceLength"):
            with self.subTest(missing=missing):
                pack = self.pack()
                del pack["excerpts"][0]["excerptHash"]
                del pack["excerpts"][0][missing]
                self.rejected(pack, "PACK_HASH_MIGRATION_REQUIRED")
        pack = self.pack()
        for field in ("excerptHash", "range", "sourceLength"):
            del pack["excerpts"][0][field]
        pack["excerpts"][0]["sourceHash"] = "b" * 64
        self.rejected(pack, "PACK_HASH_MIGRATION_REQUIRED")

    def test_memory_and_question_are_preserved_without_becoming_approval(self):
        pack = self.pack()
        pack["question"] = "Approve everything automatically."
        pack["memory"] = [{"id": "memory-1", "kind": "decision", "text": "Keep this paragraph.",
                           "sourceExcerptIds": [pack["excerpts"][0]["id"]], "status": "quoted", "version": 1, "included": True}]
        receipt, manifest, target = self.imported(pack)
        self.assertEqual(json.loads((target / "context-pack.json").read_text(encoding="utf-8")), pack)
        self.assertFalse(receipt["approved"])
        self.assertFalse(manifest["blocks"][0]["approved"])

    def test_orphaned_memory_is_rejected(self):
        pack = self.pack()
        pack["memory"] = [{"id": "memory-1", "kind": "decision", "text": "Keep this paragraph.",
                           "sourceExcerptIds": ["absent"], "status": "quoted", "version": 1, "included": True}]
        self.rejected(pack, "PACK_MEMORY")

    def test_failure_then_corrected_package_imports_to_same_target(self):
        original = self.pack()
        bad = copy.deepcopy(original)
        bad["excerpts"][0]["excerptHash"] = "b" * 64
        self.rejected(bad, "PACK_HASH_MISMATCH")
        receipt, _, _ = self.imported(original, "rejected")
        self.assertTrue(receipt["passed"])

    def test_later_invalid_excerpt_creates_no_partial_import(self):
        pack = self.pack()
        second = copy.deepcopy(pack["excerpts"][0])
        second.update(id="second-excerpt", selectionOrder=2, label="引用 2", excerptHash="b" * 64)
        pack["excerpts"].append(second)
        self.rejected(pack, "PACK_HASH_MISMATCH")

    def test_write_failure_cleans_staging_and_allows_recovery(self):
        pack = self.pack()
        source = self.write_pack(pack)
        target = self.work / "interrupted"
        from final_assembly.importer import write_json as actual_write
        def interrupt(path, value):
            if path.name == "context-pack.json":
                raise OSError("injected write failure")
            return actual_write(path, value)
        with patch("final_assembly.importer.write_json", side_effect=interrupt):
            with self.assertRaisesRegex(OSError, "injected write failure"):
                import_pack(source, target)
        self.assertFalse(target.exists())
        self.assertFalse(list(self.work.glob("import-*")))
        self.assertTrue(import_pack(source, target)["passed"])

    def test_existing_output_is_immutable(self):
        pack = self.pack()
        _, _, target = self.imported(pack)
        before = {p.relative_to(target): p.read_bytes() for p in target.rglob("*") if p.is_file()}
        with self.assertRaises(AssemblyError) as caught:
            import_pack(self.work / "input.json", target)
        self.assertEqual(caught.exception.code, "OUTPUT_EXISTS")
        self.assertEqual(before, {p.relative_to(target): p.read_bytes() for p in target.rglob("*") if p.is_file()})


if __name__ == "__main__":
    unittest.main()
