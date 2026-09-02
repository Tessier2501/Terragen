#!/usr/bin/env python3
"""确定性 QA 检查模块（不调用 LLM，成本约为 0）。

对"翻译单元"列表（source chunk -> target chunk）做机械检查，输出逐 chunk
报告与汇总。检查项：
  1. number       数字一致性（源文数字在译文中应保留）
  2. glossary     锁定术语合规（源文出现锁定词时，译文应含规范译名或声明别名）
  3. coverage     实体覆盖（glossary 中的源实体在译文中应能找到痕迹，警告级）
  4. untranslated 未译英文检测（ASCII 单词占比超阈值，排除允许列表）
  5. length       长度异常（译文/源文词数比超出区间）
  6. punctuation  引号/括号配对与数量一致性

用法:
  python qa_checks.py --translations units.json --glossary glossary.json [--out report.json]

输入格式（翻译单元）:
  [{"id": 0, "source": "...", "target": "..."}, ...]

glossary 兼容 TranslateBooksWithLLMs 的 JSON 格式:
  {"terms": [{"source": "...", "target": "...", "category": "...", "gender": "...", "lock_level": "confirmed"}]}
  或裸列表 [{"source": ..., "target": ...}]; 无 lock_level 字段时视为全部锁定。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

# ---- 基础工具 --------------------------------------------------------------

_CJK_RANGES = (
    (0x3400, 0x4DBF),   # CJK Extension A
    (0x4E00, 0x9FFF),   # CJK Unified Ideographs
    (0x3040, 0x30FF),   # Hiragana + Katakana
    (0xAC00, 0xD7AF),   # Hangul Syllables
)

_NUMBER_RE = re.compile(r"-?\d{1,3}(?:,\d{3})*(?:\.\d+)?%?|-?\d+(?:\.\d+)?%?")


def is_cjk(char: str) -> bool:
    cp = ord(char)
    return any(lo <= cp <= hi for lo, hi in _CJK_RANGES)


def count_words(text: str) -> int:
    """词数估计: 连续 ASCII 字母/数字串记 1 词, 每个 CJK 字符记 1 词, 标点与空白忽略。"""
    latin_words = len(re.findall(r"[A-Za-z0-9']+", text))
    cjk_chars = sum(1 for ch in text if is_cjk(ch))
    return latin_words + cjk_chars


def extract_numbers(text: str) -> Dict[str, int]:
    """提取数字并规范化, 返回 {规范数字: 出现次数}。"""
    counts: Dict[str, int] = {}
    for m in _NUMBER_RE.finditer(text):
        raw = m.group(0)
        normalized = raw.replace(",", "")
        counts[normalized] = counts.get(normalized, 0) + 1
    return counts


# ---- 检查结果模型 ----------------------------------------------------------

@dataclass
class CheckResult:
    check: str
    passed: bool
    issues: List[str] = field(default_factory=list)


@dataclass
class ChunkReport:
    id: int
    source: str
    target: str
    checks: List[CheckResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)


# ---- 单项检查 --------------------------------------------------------------

def check_numbers(source: str, target: str) -> CheckResult:
    src_counts = extract_numbers(source)
    tgt_counts = extract_numbers(target)
    issues: List[str] = []
    for num, count in sorted(src_counts.items()):
        got = tgt_counts.get(num, 0)
        if got < count:
            issues.append(f"数字 {num} 源文出现 {count} 次, 译文仅 {got} 次")
    return CheckResult("number", not issues, issues)


def _glossary_locked_entries(glossary: Optional[Dict[str, Any]]) -> List[Dict[str, str]]:
    if not glossary:
        return []
    raw = glossary.get("terms") if isinstance(glossary, dict) else glossary
    if not isinstance(raw, list):
        return []
    entries = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        lock_level = entry.get("lock_level") or "confirmed"
        if lock_level != "confirmed":
            continue
        source = (entry.get("source") or "").strip()
        target = (entry.get("target") or "").strip()
        if source and target:
            entries.append(entry)
    return entries


def _aliases_of(entry: Dict[str, Any]) -> List[str]:
    aliases = entry.get("aliases") or []
    if isinstance(aliases, str):
        aliases = [a.strip() for a in aliases.split("|") if a.strip()]
    return [a for a in aliases if isinstance(a, str) and a.strip()]


def check_glossary_compliance(source: str, target: str, glossary: Optional[Dict[str, Any]]) -> CheckResult:
    issues: List[str] = []
    for entry in _glossary_locked_entries(glossary):
        term = (entry.get("source") or "").strip()
        if not term or term not in source:
            continue
        expected = (entry.get("target") or "").strip()
        accepted = [expected] + _aliases_of(entry)
        if not any(alt and alt in target for alt in accepted):
            issues.append(f"锁定术语 '{term}' -> '{expected}' 在译文中未找到")
    return CheckResult("glossary", not issues, issues)


def check_entity_coverage(source: str, target: str, glossary: Optional[Dict[str, Any]]) -> CheckResult:
    """实体覆盖(警告级): 源文出现的锁定实体, 译文应有任何痕迹
    (规范译名 / 声明别名 / 原文形式均可), 否则提示可能消失。"""
    issues: List[str] = []
    for entry in _glossary_locked_entries(glossary):
        term = (entry.get("source") or "").strip()
        if not term or term not in source:
            continue
        accepted = [entry.get("target") or ""] + _aliases_of(entry) + [term]
        if not any(alt and alt in target for alt in accepted):
            issues.append(f"实体 '{term}' 在译文中可能消失")
    return CheckResult("coverage", not issues, issues)


def check_untranslated_english(
    source: str, target: str, glossary: Optional[Dict[str, Any]], threshold: float = 0.15,
) -> CheckResult:
    allowed = {entry.get("source") for entry in _glossary_locked_entries(glossary) if entry.get("source")}
    latin_words = re.findall(r"[A-Za-z]+", target)
    total_units = count_words(target)
    if total_units == 0:
        return CheckResult("untranslated", True, [])
    residual = [w for w in latin_words if w not in allowed]
    ratio = len(residual) / total_units
    issues: List[str] = []
    if ratio > threshold:
        preview = " ".join(residual[:10])
        issues.append(f"疑似未译英文占比 {ratio:.0%} (阈值 {threshold:.0%}), 例如: {preview}")
    return CheckResult("untranslated", not issues, issues)


def check_length_ratio(source: str, target: str, min_ratio: float = 0.3, max_ratio: float = 3.0) -> CheckResult:
    src_words = count_words(source)
    tgt_words = count_words(target)
    issues: List[str] = []
    if src_words > 0:
        ratio = tgt_words / src_words
        if ratio < min_ratio or ratio > max_ratio:
            issues.append(f"长度比 {ratio:.2f} (译文 {tgt_words} / 源文 {src_words}) 超出区间 [{min_ratio}, {max_ratio}]")
    return CheckResult("length", not issues, issues)


def _quote_imbalance(text: str) -> List[str]:
    issues: List[str] = []
    for left, right in (("\u201c", "\u201d"), ("\u2018", "\u2019"), ("(", ")"), ("“", "”")):
        diff = text.count(left) - text.count(right)
        if diff != 0:
            issues.append(f"引号 {left} 比 {right} 多 {diff} 个")
    return issues


def check_punctuation(source: str, target: str) -> CheckResult:
    issues = _quote_imbalance(target)
    if issues:
        src_issues = _quote_imbalance(source)
        if src_issues:
            issues = [f"{i} (源文同样不平衡)" for i in issues]
    return CheckResult("punctuation", not issues, issues)


# ---- 汇总 ------------------------------------------------------------------

def run_all(
    source: str,
    target: str,
    glossary: Optional[Dict[str, Any]] = None,
    untranslated_threshold: float = 0.15,
    length_bounds: Sequence[float] = (0.3, 3.0),
) -> List[CheckResult]:
    return [
        check_numbers(source, target),
        check_glossary_compliance(source, target, glossary),
        check_entity_coverage(source, target, glossary),
        check_untranslated_english(source, target, glossary, untranslated_threshold),
        check_length_ratio(source, target, length_bounds[0], length_bounds[1]),
        check_punctuation(source, target),
    ]


def load_translations(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"翻译单元文件不存在: {path}")
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, list):
        raise ValueError("翻译单元文件必须是 JSON 数组")
    return data


def load_glossary(path: Optional[Path]) -> Optional[Dict[str, Any]]:
    if path is None:
        return None
    if not path.exists():
        raise FileNotFoundError(f"glossary 文件不存在: {path}")
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="确定性 QA 检查 (不调用 LLM)")
    parser.add_argument("--translations", type=Path, required=True, help="翻译单元 JSON 数组文件")
    parser.add_argument("--glossary", type=Path, default=None, help="glossary JSON (TranslateBooksWithLLMs 格式)")
    parser.add_argument("--out", type=Path, default=None, help="报告 JSON 输出路径 (缺省只打印)")
    parser.add_argument("--untranslated-threshold", type=float, default=0.15, help="未译英文占比阈值 (默认 0.15)")
    parser.add_argument("--min-ratio", type=float, default=0.3, help="长度比下限 (默认 0.3)")
    parser.add_argument("--max-ratio", type=float, default=3.0, help="长度比上限 (默认 3.0)")
    args = parser.parse_args(argv)

    units = load_translations(args.translations)
    glossary = load_glossary(args.glossary)

    reports: List[ChunkReport] = []
    for unit in units:
        chunk_id = unit.get("id", 0)
        source = unit.get("source") or ""
        target = unit.get("target") or ""
        if not source or not target:
            reports.append(ChunkReport(id=chunk_id, source=source, target=target,
                                       checks=[CheckResult("format", False, ["source 或 target 为空"])]))
            continue
        checks = run_all(source, target, glossary, args.untranslated_threshold,
                         (args.min_ratio, args.max_ratio))
        reports.append(ChunkReport(id=chunk_id, source=source, target=target, checks=checks))

    failed = [r for r in reports if not r.passed]
    print(f"共 {len(reports)} 个 chunk, 通过 {len(reports) - len(failed)}, 异常 {len(failed)}")
    for report in failed:
        detail = "; ".join(issue for check in report.checks for issue in check.issues)
        print(f"  chunk {report.id}: {detail}")

    if args.out is not None:
        payload = {
            "summary": {"total": len(reports), "failed": len(failed), "passed": len(reports) - len(failed)},
            "chunks": [asdict(r) for r in reports],
        }
        args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"报告已写入: {args.out}")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
