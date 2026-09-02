#!/usr/bin/env python3
"""对比两次运行的 token / 缓存 / 成本数据。

用法: python compare_runs.py <run1.summary.json> <run2.summary.json> [标签1 标签2]
输出: 并排对照表 + 差异。成本按 DeepSeek 官方 v4-flash 低谷/高峰两档估算。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

# DeepSeek 官方 v4-flash 价格 (美元/百万 token)
PRICES = {
    "offpeak": {"miss": 0.22, "hit": 0.007, "output": 0.66},
    "peak": {"miss": 0.44, "hit": 0.014, "output": 1.32},
}


def load(path: str) -> Dict[str, object]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(path)
    return json.loads(p.read_text(encoding="utf-8"))


def cost_usd(tokens: Dict[str, int], prices: Dict[str, float]) -> float:
    return (
        tokens["cache_miss_total"] / 1e6 * prices["miss"]
        + tokens["cache_hit_total"] / 1e6 * prices["hit"]
        + tokens["completion_total"] / 1e6 * prices["output"]
    )


def main(argv: Optional[List[str]] = None) -> int:
    argv = argv or sys.argv
    if len(argv) < 3:
        print(__doc__)
        return 2
    a = load(argv[1])
    b = load(argv[2])
    label_a = argv[3] if len(argv) > 3 else Path(argv[1]).stem
    label_b = argv[4] if len(argv) > 4 else Path(argv[2]).stem

    def row(name: str, key: Optional[str] = None, fmt=lambda v: str(v)) -> None:
        va = a["tokens"][key] if key else a
        vb = b["tokens"][key] if key else b
        print(f"{name:<18}{fmt(va):>14}{fmt(vb):>14}")

    ta, tb = a["tokens"], b["tokens"]
    print(f"{'指标':<18}{label_a:>14}{label_b:>14}")
    print("-" * 46)
    row("LLM 调用数", None, lambda s: s["chunks_logged"])
    row("输入 token 合计", "input_total")
    row("缓存命中 token", "cache_hit_total")
    row("缓存未命中 token", "cache_miss_total")
    row("缓存命中率", "cache_hit_rate", lambda v: f"{v:.1%}")
    row("输出 token 合计", "completion_total")
    cost_a = cost_usd(ta, PRICES["offpeak"])
    cost_b = cost_usd(tb, PRICES["offpeak"])
    print(f"{'成本(低谷价)':<18}{'$' + f'{cost_a:.4f}':>14}{'$' + f'{cost_b:.4f}':>14}")
    cost_a_p = cost_usd(ta, PRICES["peak"])
    cost_b_p = cost_usd(tb, PRICES["peak"])
    print(f"{'成本(高峰价)':<18}{'$' + f'{cost_a_p:.4f}':>14}{'$' + f'{cost_b_p:.4f}':>14}")
    print("-" * 46)
    print(f"差异: 输入 {tb['input_total'] - ta['input_total']:+d} | "
          f"输出 {tb['completion_total'] - ta['completion_total']:+d} | "
          f"命中率 {tb['cache_hit_rate'] - ta['cache_hit_rate']:+.1%} | "
          f"成本(低谷) {'+' if cost_b >= cost_a else '-'}${abs(cost_b - cost_a):.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
