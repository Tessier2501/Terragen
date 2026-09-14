"""Tests for gd_to_json / json_to_gd incremental workflow safety."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import gd_to_json
import json_to_gd
from gd_format import parse_translations_file

from _fixture import make_gd


class PipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.gd_path = self.root / "REPLACE_TRANSLATIONS.gd"
        self.out_dir = self.root / "out"
        self.metadata_path = self.root / "metadata.json"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _write_gd(
        self,
        en: list[tuple[str, str, int]],
        zh: list[tuple[str, str, int]],
    ) -> None:
        self.gd_path.write_text(make_gd(en=en, zh=zh), encoding="utf-8")

    def test_first_run_then_delta_report_and_archive(self) -> None:
        self._write_gd(
            en=[("A", "Alpha", 10), ("B", "Beta", 20), ("C", "Gamma", 30)],
            zh=[("A", "甲", 10), ("B", "乙", 20), ("C", "丙", 30)],
        )
        summary = gd_to_json.generate(
            self.gd_path, self.out_dir, self.metadata_path
        )
        self.assertTrue(summary["changes"]["first_run"])
        self.assertEqual(summary["changes"]["added"], ["A", "B", "C"])
        self.assertTrue((self.out_dir / "paratranz_source.json").is_file())
        self.assertTrue((self.out_dir / "paratranz_initial_translation.json").is_file())
        self.assertTrue(self.metadata_path.is_file())

        # Source update: A gets new English, D is added, C is removed.
        self._write_gd(
            en=[("A", "Alpha changed", 11), ("B", "Beta", 20), ("D", "Delta", 40)],
            zh=[("A", "甲", 10), ("B", "乙", 20), ("C", "丙", 30)],
        )
        previous_sha = json.loads(
            self.metadata_path.read_text(encoding="utf-8")
        )["source_sha256"]
        gd_to_json.generate(self.gd_path, self.out_dir, self.metadata_path)
        changes = json.loads(
            (self.out_dir / "paratranz_changes.json").read_text(encoding="utf-8")
        )
        self.assertFalse(changes["first_run"])
        self.assertEqual(changes["added"], ["D"])
        self.assertEqual(changes["changed"], ["A"])
        self.assertEqual(changes["removed"], ["C"])
        self.assertEqual(changes["untranslated"], ["D"])
        self.assertEqual(changes["stale"], ["A"])
        archive = self.out_dir / "archive" / previous_sha
        self.assertTrue((archive / "metadata.json").is_file())
        self.assertTrue((archive / "paratranz_source.json").is_file())

    def test_check_mode_writes_nothing(self) -> None:
        self._write_gd(
            en=[("A", "Alpha", 10)],
            zh=[("A", "甲", 10)],
        )
        summary = gd_to_json.generate(
            self.gd_path,
            self.out_dir,
            self.metadata_path,
            write=False,
        )
        self.assertTrue(summary["check_only"])
        self.assertEqual(summary["wrote"], [])
        self.assertFalse(self.metadata_path.exists())
        self.assertFalse(self.out_dir.exists())

    def test_initial_snapshot_blanks_changed_and_added_on_update(self) -> None:
        self._write_gd(
            en=[("A", "Alpha", 10), ("B", "Beta", 20)],
            zh=[("A", "甲", 10), ("B", "乙", 20)],
        )
        gd_to_json.generate(self.gd_path, self.out_dir, self.metadata_path)
        self._write_gd(
            en=[("A", "Alpha changed", 11), ("B", "Beta", 20), ("D", "Delta", 40)],
            zh=[("A", "甲", 10), ("B", "乙", 20)],
        )
        gd_to_json.generate(
            self.gd_path,
            self.out_dir,
            self.metadata_path,
            emit_initial=True,
        )
        initial = {
            item["key"]: item["translation"]
            for item in json.loads(
                (self.out_dir / "paratranz_initial_translation.json").read_text(
                    encoding="utf-8"
                )
            )
        }
        self.assertEqual(initial["A"], "")
        self.assertEqual(initial["B"], "乙")
        self.assertEqual(initial["D"], "")

    def test_stale_guard_blocks_false_sync_without_acceptance(self) -> None:
        parsed = parse_translations_file(
            make_gd(
                en=[("A", "Alpha changed", 11)],
                zh=[("A", "甲", 10)],
            )
        )
        items = [
            json_to_gd.ExportItem(
                key="A",
                original="Alpha changed",
                translation="甲",
                stage=5,
            )
        ]
        plan = json_to_gd.plan_merge(parsed, items)
        self.assertEqual(plan.stale_reviewed, ["A"])
        self.assertEqual(plan.entries[0].version_hash, 10)
        self.assertEqual(plan.still_outdated, ["A"])
        self.assertEqual(plan.changes, [])

        accepted = json_to_gd.plan_merge(
            parsed,
            items,
            accepted_stale_keys=["A"],
        )
        self.assertEqual(accepted.stale_reviewed, ["A"])
        self.assertEqual(accepted.entries[0].version_hash, 11)
        self.assertEqual(accepted.still_outdated, [])
        self.assertEqual(len(accepted.changes), 1)

    def test_reviewed_changed_translation_syncs_normally(self) -> None:
        parsed = parse_translations_file(
            make_gd(
                en=[("A", "Alpha changed", 11)],
                zh=[("A", "甲", 10)],
            )
        )
        items = [
            json_to_gd.ExportItem(
                key="A",
                original="Alpha changed",
                translation="阿尔法改了",
                stage=5,
            )
        ]
        plan = json_to_gd.plan_merge(parsed, items)
        self.assertEqual(plan.stale_reviewed, [])
        self.assertEqual(plan.entries[0].version_hash, 11)
        self.assertIn("阿尔法改了", plan.entries[0].text)

    def test_missing_key_is_fatal_and_extra_key_is_ignored(self) -> None:
        parsed = parse_translations_file(
            make_gd(
                en=[("A", "Alpha", 10)],
                zh=[("A", "甲", 10)],
            )
        )
        missing = [
            json_to_gd.ExportItem(
                key="B",
                original="Beta",
                translation="乙",
                stage=5,
            )
        ]
        with self.assertRaises(ValueError):
            json_to_gd.plan_merge(parsed, missing)

        extra = [
            json_to_gd.ExportItem(
                key="A",
                original="Alpha",
                translation="甲",
                stage=5,
            ),
            json_to_gd.ExportItem(
                key="OLD",
                original="Old",
                translation="旧",
                stage=5,
            ),
        ]
        plan = json_to_gd.plan_merge(parsed, extra)
        self.assertEqual(plan.extra_keys, ["OLD"])
        with self.assertRaises(ValueError):
            json_to_gd.plan_merge(parsed, extra, allow_extra_keys=False)

    def test_added_key_becomes_placeholder_until_translated(self) -> None:
        parsed = parse_translations_file(
            make_gd(
                en=[("A", "Alpha", 10), ("D", "Delta", 40)],
                zh=[("A", "甲", 10)],
            )
        )
        items = [
            json_to_gd.ExportItem("A", "Alpha", "甲", 5),
            json_to_gd.ExportItem("D", "Delta", "", 0),
        ]
        plan = json_to_gd.plan_merge(parsed, items)
        entry_d = next(entry for entry in plan.entries if entry.key == "D")
        self.assertEqual(entry_d.text, "Delta")
        self.assertEqual(entry_d.version_hash, 0)
        self.assertIn("D", plan.placeholder_keys)
        self.assertIn("D", plan.still_outdated)

    def test_removed_zh_only_key_is_deleted(self) -> None:
        parsed = parse_translations_file(
            make_gd(
                en=[("A", "Alpha", 10)],
                zh=[("A", "甲", 10), ("C", "丙", 30)],
            )
        )
        items = [json_to_gd.ExportItem("A", "Alpha", "甲", 5)]
        plan = json_to_gd.plan_merge(parsed, items)
        self.assertEqual(plan.deleted_keys, ["C"])


if __name__ == "__main__":
    unittest.main()
