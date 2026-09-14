"""Tests for the GDScript translation parser/renderer and path resolution."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gd_format import (
    GDParseError,
    LocalizedText,
    parse_translations_file,
    render_locale_block,
    resolve_default_gd,
)

from _fixture import make_gd


class GdFormatTests(unittest.TestCase):
    def test_zh_block_roundtrip_preserves_values_and_hash(self) -> None:
        text = make_gd(
            en=[("A", "Alpha", 11), ("B", "Beta", 22)],
            zh=[("A", "甲", 11), ("B", "乙", 22)],
        )
        parsed = parse_translations_file(text)
        block = render_locale_block(
            "zh_CN",
            [
                LocalizedText(
                    key=entry.key,
                    text=entry.text,
                    version_hash=entry.version_hash,
                )
                for entry in parsed.zh.entries.values()
            ],
        )
        merged = text[: parsed.zh.start] + block + text[parsed.zh.end :]
        reparsed = parse_translations_file(merged)
        self.assertEqual(parsed.en.entries.keys(), reparsed.en.entries.keys())
        self.assertEqual(parsed.zh.entries.keys(), reparsed.zh.entries.keys())
        self.assertEqual(
            {k: (v.text, v.version_hash) for k, v in reparsed.zh.entries.items()},
            {k: (v.text, v.version_hash) for k, v in parsed.zh.entries.items()},
        )

    def test_master_locale_must_be_en(self) -> None:
        text = make_gd(
            en=[("A", "Alpha", 11)],
            zh=[("A", "甲", 11)],
            master_locale="ru",
        )
        with self.assertRaises(GDParseError):
            parse_translations_file(text)

    def test_resolve_default_gd_current_layout(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            tools_dir = root / "IndustriesOfEnceladusRewriteCN_Script"
            source = (
                root
                / "IndustriesOfEnceladusRewriteCN"
                / "HEVLIB_EQUIPMENT_DRIVER_TAGS"
                / "REPLACE_TRANSLATIONS.gd"
            )
            tools_dir.mkdir(parents=True)
            source.parent.mkdir(parents=True)
            source.write_text("const TRANSLATIONS = {}\n", encoding="utf-8")
            self.assertEqual(resolve_default_gd(tools_dir), source)

    def test_resolve_default_gd_legacy_layout(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            tools_dir = root / "Script" / "para-translation"
            source = (
                root
                / "IndustriesOfEnceladusRewriteCN"
                / "HEVLIB_EQUIPMENT_DRIVER_TAGS"
                / "REPLACE_TRANSLATIONS.gd"
            )
            tools_dir.mkdir(parents=True)
            source.parent.mkdir(parents=True)
            source.write_text("const TRANSLATIONS = {}\n", encoding="utf-8")
            self.assertEqual(resolve_default_gd(tools_dir), source)


if __name__ == "__main__":
    unittest.main()
