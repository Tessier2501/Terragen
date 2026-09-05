"""M4 场景编排: 两平台主寻优 + 方案 B 同曲线对照实验.

对照设计:
- alb / glb: 各自独立优化推力曲线与程序角 (最大有效射程);
- glb_with_alb_curve: GLBM 平台 + ALBM 最优推力曲线, 只重优化程序角;
- alb_with_glb_curve: ALBM 平台 + GLBM 最优推力曲线, 只重优化程序角.

由此分解:
- 曲线设计贡献 (地射视角): R(glb_alb_curve) - R(glb_full);
- 平台发射条件贡献 (同曲线口径): R(alb_full) - R(glb_alb_curve).
"""

from __future__ import annotations

from dataclasses import dataclass

from .optimize import (
    OptimizationResult,
    make_steering_only_spec,
    optimize_platform,
)


@dataclass
class ScenarioOutcome:
    """一次完整场景的全部寻优结果."""

    alb: OptimizationResult
    glb: OptimizationResult
    glb_with_alb_curve: OptimizationResult
    alb_with_glb_curve: OptimizationResult
    vmin_m_s: float


def run_scenario(
    *,
    vmin_m_s: float = 700.0,
    seed: int = 20250905,
    popsize: int = 12,
    maxiter: int = 25,
) -> ScenarioOutcome:
    """运行主寻优与全部对照实验 (约 3-6 分钟)."""
    alb = optimize_platform(
        "ALBM", vmin_m_s=vmin_m_s, seed=seed, popsize=popsize, maxiter=maxiter
    )
    glb = optimize_platform(
        "GLBM", vmin_m_s=vmin_m_s, seed=seed + 1000, popsize=popsize, maxiter=maxiter
    )
    if not (alb.success and glb.success):
        raise RuntimeError("主寻优未找到可行解, 无法继续对照实验")
    alb_shape = alb.best_x[:3]
    glb_shape = glb.best_x[:3]
    glb_alb = optimize_platform(
        "GLBM",
        vmin_m_s=vmin_m_s,
        seed=seed + 2000,
        popsize=popsize,
        maxiter=maxiter,
        spec_override=make_steering_only_spec("GLBM", alb_shape),
    )
    alb_glb = optimize_platform(
        "ALBM",
        vmin_m_s=vmin_m_s,
        seed=seed + 3000,
        popsize=popsize,
        maxiter=maxiter,
        spec_override=make_steering_only_spec("ALBM", glb_shape),
    )
    return ScenarioOutcome(
        alb=alb,
        glb=glb,
        glb_with_alb_curve=glb_alb,
        alb_with_glb_curve=alb_glb,
        vmin_m_s=vmin_m_s,
    )


__all__ = ["ScenarioOutcome", "run_scenario"]
