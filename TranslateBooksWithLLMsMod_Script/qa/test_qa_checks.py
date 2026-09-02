#!/usr/bin/env python3
"""qa_checks 模块的单元测试 (纯标准库 unittest, 无需安装依赖).

运行方式: python3 -m unittest test_qa_checks -v   (在 qa/ 目录下)
"""
from __future__ import annotations

import unittest

from qa_checks import (
    ChunkReport,
    check_entity_coverage,
    check_glossary_compliance,
    check_length_ratio,
    check_numbers,
    check_punctuation,
    check_untranslated_english,
    count_words,
    extract_numbers,
    run_all,
)

GLOSSARY = {
    "terms": [
        {"source": "Jon Snow", "target": "琼恩·雪诺", "lock_level": "confirmed"},
        {"source": "Winterfell", "target": "临冬城", "lock_level": "confirmed"},
        {"source": "Mystery Man", "target": "神秘人", "lock_level": "suggested"},
    ]
}


class TestCountWords(unittest.TestCase):
    def test_latin_words(self) -> None:
        self.assertEqual(count_words("Hello world, foo-bar!"), 4)

    def test_cjk_chars_count_individually(self) -> None:
        self.assertEqual(count_words("临冬城的冬天很长"), 8)

    def test_mixed(self) -> None:
        self.assertEqual(count_words("他去了 Winterfell"), 4)


class TestExtractNumbers(unittest.TestCase):
    def test_integers_and_decimals(self) -> None:
        self.assertEqual(extract_numbers("3 个, 17.5%, 1,200 人"), {"3": 1, "17.5%": 1, "1200": 1})

    def test_counts(self) -> None:
        self.assertEqual(extract_numbers("42 与 42 与 7"), {"42": 2, "7": 1})


class TestCheckNumbers(unittest.TestCase):
    def test_missing_number_fails(self) -> None:
        result = check_numbers("他等了 3 天", "他等了三天")
        self.assertFalse(result.passed)
        self.assertTrue(any("3" in issue for issue in result.issues))

    def test_present_number_passes(self) -> None:
        result = check_numbers("他等了 3 天", "他等了 3 天")
        self.assertTrue(result.passed)


class TestGlossaryCompliance(unittest.TestCase):
    def test_locked_term_missing_in_target_fails(self) -> None:
        result = check_glossary_compliance("Jon Snow walked", "雪诺走了。", GLOSSARY)
        self.assertFalse(result.passed)

    def test_locked_term_present_passes(self) -> None:
        result = check_glossary_compliance("Jon Snow walked", "琼恩·雪诺走了。", GLOSSARY)
        self.assertTrue(result.passed)

    def test_suggested_term_not_enforced(self) -> None:
        result = check_glossary_compliance("Mystery Man appeared", "神秘人出现。", GLOSSARY)
        self.assertTrue(result.passed)


class TestEntityCoverage(unittest.TestCase):
    def test_entity_dropped_warns(self) -> None:
        result = check_entity_coverage("Jon Snow entered Winterfell", "他进去了。", GLOSSARY)
        self.assertFalse(result.passed)
        self.assertTrue(any("Jon Snow" in issue for issue in result.issues))


class TestUntranslatedEnglish(unittest.TestCase):
    def test_heavy_residual_fails(self) -> None:
        result = check_untranslated_english("中文", "This sentence is still English.", None, 0.15)
        self.assertFalse(result.passed)

    def test_allowed_term_not_flagged(self) -> None:
        result = check_untranslated_english("Jon Snow reached Winterfell", "琼恩·雪诺到了 Winterfell。", GLOSSARY, 0.15)
        self.assertTrue(result.passed)

    def test_clean_translation_passes(self) -> None:
        result = check_untranslated_english("英文", "这是一段干净的中文翻译。", None, 0.15)
        self.assertTrue(result.passed)


class TestLengthRatio(unittest.TestCase):
    def test_extreme_shrink_fails(self) -> None:
        result = check_length_ratio("A " * 100, "短", 0.3, 3.0)
        self.assertFalse(result.passed)

    def test_normal_ratio_passes(self) -> None:
        result = check_length_ratio("Hello world", "你好世界。", 0.3, 3.0)
        self.assertTrue(result.passed)


class TestPunctuation(unittest.TestCase):
    def test_unbalanced_quote_fails(self) -> None:
        result = check_punctuation("他说：“你好”", "他说：“你好")
        self.assertFalse(result.passed)

    def test_balanced_passes(self) -> None:
        result = check_punctuation("他说：“你好”", "他说：“你好”")
        self.assertTrue(result.passed)


class TestRunAll(unittest.TestCase):
    def test_clean_unit_passes_all(self) -> None:
        checks = run_all("Jon Snow waited 3 days at Winterfell", "琼恩·雪诺在临冬城等了 3 天。", GLOSSARY)
        for check in checks:
            self.assertTrue(check.passed, msg=f"{check.check}: {check.issues}")

    def test_report_passed_property(self) -> None:
        checks = run_all("clean", "干净。", None)
        report = ChunkReport(id=1, source="clean", target="干净。", checks=checks)
        self.assertTrue(report.passed)


if __name__ == "__main__":
    unittest.main()
