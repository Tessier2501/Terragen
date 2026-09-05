"""手动运行接口 (README 详述用法).

用法示例:
    python -m missile_sim.cli --scenario final          # 弹道 vs 升力滑翔 v1 最终图/报告
    python -m missile_sim.cli --scenario ballistic      # 纯弹道场景表格
    python -m missile_sim.cli --scenario lift           # 升力滑翔 v1 场景表格
    python -m missile_sim.report                        # M4 纯弹道报告 (旧接口保留)

常用调参: --vmin 700 --seed 20250905 --popsize 12 --maxiter 25 --outdir output
快速冒烟: 追加 --quick (popsize=5, maxiter=8).
"""

from __future__ import annotations

import argparse
from pathlib import Path

from .optimize import clear_cache
from .report import generate_final_report, generate_report
from .scenario import run_scenario


def _print_scenario(tag: str, outcome: object) -> None:
    for key, res in (
        ("ALBM 全最优", outcome.alb),  # type: ignore[attr-defined]
        ("GLBM 全最优", outcome.glb),  # type: ignore[attr-defined]
        ("GLBM+ALB曲线", outcome.glb_with_alb_curve),  # type: ignore[attr-defined]
        ("ALBM+GLB曲线", outcome.alb_with_glb_curve),  # type: ignore[attr-defined]
    ):
        m = res.best_metrics
        print(
            f"{tag} | {key}: 射程 {m.range_km:.1f} km | 命中 {m.impact_speed_m_s:.0f} m/s "
            f"| 飞行 {m.flight_time_s:.0f} s | ok={res.success}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="RocketSim 手动运行接口")
    parser.add_argument("--scenario", choices=("final", "ballistic", "lift"),
                        default="final")
    parser.add_argument("--vmin", type=float, default=700.0)
    parser.add_argument("--seed", type=int, default=20250905)
    parser.add_argument("--popsize", type=int, default=12)
    parser.add_argument("--maxiter", type=int, default=25)
    parser.add_argument("--outdir", default="output")
    parser.add_argument("--quick", action="store_true",
                        help="小搜索预算快速冒烟")
    args = parser.parse_args()
    popsize = 5 if args.quick else args.popsize
    maxiter = 8 if args.quick else args.maxiter
    out = Path(args.outdir)
    if args.scenario == "final":
        target = out / "lift_v1"
        path = generate_final_report(
            target, seed=args.seed, popsize=popsize, maxiter=maxiter,
            vmin_m_s=args.vmin,
        )
        print("最终报告:", path)
        return
    if args.scenario == "ballistic":
        clear_cache()
        sc = run_scenario(seed=args.seed, popsize=popsize, maxiter=maxiter,
                          vmin_m_s=args.vmin, lift_guidance=False)
        _print_scenario("纯弹道", sc)
        return
    if args.scenario == "lift":
        clear_cache()
        sc = run_scenario(seed=args.seed, popsize=popsize, maxiter=maxiter,
                          vmin_m_s=args.vmin, lift_guidance=True)
        _print_scenario("升力滑翔 v1", sc)
        return
    raise ValueError(f"未知场景 {args.scenario}")


if __name__ == "__main__":
    main()
