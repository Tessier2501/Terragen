#!/usr/bin/env python3
"""解析 TranslateBooksWithLLMs 运行日志, 汇总 token / 缓存命中 / 耗时数据。

输入: translate.py 的 stdout 日志(含 P1 补丁输出的逐 chunk 行:
  "💬 DeepSeek: <prompt>+<completion> tokens (cache hit <hit>, miss <miss>)")
输出: <log>.summary.json 与终端汇总表。

用法: python summarize_run.py <log路径>
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional

# 逐 chunk 行: prompt+completion tokens, cache hit/miss
_CHUNK_RE = re.compile(
    r"DeepSeek: (\d+)\+(\d+) tokens \(cache hit (\d+), miss (\d+)\)"
)
# 进度行形如:  ✅ Chunk 12/103 之类, 或 "12/103"; 先抓所有 x/y 进度
_PROGRESS_RE = re.compile(r"(\d+)/(\d+)")

# 结束/启动标记 (实际日志为大写/混合大小写)
_START_RE = re.compile(r"Translation Started", re.IGNORECASE)
_END_RE = re.compile(r"Translation completed successfully", re.IGNORECASE)
# 致命失败(排除 benign warning)
_FAIL_RE = re.compile(r"Translation failed|Traceback \(most recent call last\)|HTTPStatusError", re.IGNORECASE)
# 非致命: 标签提取失败走 fallback 的次数
_FALLBACK_RE = re.compile(r"Failed to extract translation", re.IGNORECASE)


def parse_log(text: str) -> Dict[str, object]:
    chunks: List[Dict[str, int]] = []
    for m in _CHUNK_RE.finditer(text):
        chunks.append({
            "prompt_tokens": int(m.group(1)),
            "completion_tokens": int(m.group(2)),
            "cache_hit": int(m.group(3)),
            "cache_miss": int(m.group(4)),
        })

    progress_matches = _PROGRESS_RE.findall(text)
    total_chunks = 0
    if progress_matches:
        last = progress_matches[-1]
        total_chunks = int(last[1])

    started = bool(_START_RE.search(text))
    succeeded = bool(_END_RE.search(text))
    failed = bool(_FAIL_RE.search(text))
    fallback_warnings = len(_FALLBACK_RE.findall(text))

    if chunks:
        prompt_total = sum(c["prompt_tokens"] for c in chunks)
        completion_total = sum(c["completion_tokens"] for c in chunks)
        hit_total = sum(c["cache_hit"] for c in chunks)
        miss_total = sum(c["cache_miss"] for c in chunks)
        hit_rate = hit_total / (hit_total + miss_total) if (hit_total + miss_total) else 0.0
    else:
        prompt_total = completion_total = hit_total = miss_total = 0
        hit_rate = 0.0

    return {
        "chunks_logged": len(chunks),
        "total_chunks_reported": total_chunks,
        "started": started,
        "succeeded": succeeded,
        "failed": failed,
        "fallback_warnings": fallback_warnings,
        "tokens": {
            "prompt_total": prompt_total,
            "completion_total": completion_total,
            "cache_hit_total": hit_total,
            "cache_miss_total": miss_total,
            "input_total": hit_total + miss_total,
            "cache_hit_rate": round(hit_rate, 4),
        },
    }


def main(argv: Optional[List[str]] = None) -> int:
    if not argv or len(argv) < 2:
        print(__doc__)
        return 2
    log_path = Path(argv[1])
    if not log_path.exists():
        print(f"日志不存在: {log_path}")
        return 1
    text = log_path.read_text(encoding="utf-8", errors="replace")
    summary = parse_log(text)

    out_path = log_path.with_suffix(log_path.suffix + ".summary.json")
    out_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    t = summary["tokens"]
    print(f"运行: {'成功' if summary['succeeded'] else '未完成/失败' if summary['failed'] else '状态未知'}"
          f" (fallback 警告 {summary['fallback_warnings']} 次)")
    print(f"记录 chunk 数: {summary['chunks_logged']} (进度报告总数: {summary['total_chunks_reported']})")
    print(f"输入 token 合计: {t['input_total']} (命中 {t['cache_hit_total']} / 未命中 {t['cache_miss_total']})")
    print(f"缓存命中率: {t['cache_hit_rate']:.1%}")
    print(f"输出 token 合计: {t['completion_total']}")
    print(f"汇总已写入: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
