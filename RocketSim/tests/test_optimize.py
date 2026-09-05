"""M3 寻优管线用例 (结构性与确定性, 非全量搜索)."""

from __future__ import annotations

import numpy as np
import pytest

from missile_sim.optimize import (
    clear_cache,
    evaluate_design,
    make_platform_spec,
    optimize_platform,
)


@pytest.fixture(autouse=True)
def _clean_cache() -> None:
    clear_cache()


def test_x0_evaluation_glb() -> None:
    spec = make_platform_spec("GLBM")
    m = evaluate_design(spec, spec.x0)
    assert m.success
    assert m.range_m > 0.0
    assert m.impact_speed_m_s > 0.0
    assert m.max_mach > 0.5
    assert m.boost_max_q_pa > 0.0


def test_design_mapping_reversible_levels() -> None:
    """r<1 (先低后高) 与 r>1 (先高后低) 都允许且物理量正常."""
    spec = make_platform_spec("ALBM")
    lo = evaluate_design(spec, np.array([2.5, 0.7, 0.5, 45.0]))
    hi = evaluate_design(spec, np.array([4.0, 1.5, 0.5, 45.0]))
    assert lo.success and hi.success
    assert lo.range_m > 0.0 and hi.range_m > 0.0


def test_bad_parameter_count_rejected() -> None:
    spec = make_platform_spec("ALBM")
    with pytest.raises(ValueError):
        evaluate_design(spec, np.array([4.0, 1.0, 0.5]))


def test_smoke_optimize_alb_deterministic() -> None:
    """小规模 DE 冒烟: 可复现, 结构完整."""
    r1 = optimize_platform(
        "ALBM", vmin_m_s=700.0, seed=42, popsize=4, maxiter=2
    )
    clear_cache()
    r2 = optimize_platform(
        "ALBM", vmin_m_s=700.0, seed=42, popsize=4, maxiter=2
    )
    assert np.array_equal(r1.best_x, r2.best_x)
    assert r1.success
    assert r1.best_metrics.vmin_violation(700.0) >= 0.0
    assert len(r1.evaluations) > 0
    assert len(r1.margins) >= 4
    assert r1.attempts >= 1


def test_margins_structure() -> None:
    spec = make_platform_spec("GLBM")
    m = evaluate_design(spec, spec.x0)
    assert m.success
    assert m.boost_max_q_pa >= 0.0
    assert m.reentry_max_q_pa >= 0.0
    assert m.max_axial_g >= 0.0
    assert 0.0 <= m.steer_saturation_fraction <= 1.0
