"""AtmosphereUSSA76 模型的物理验证用例.

验收标准 (PLAN M1): 与公开标准表关键点误差 < 0.5%.
"""

from __future__ import annotations

import math

import pytest

from missile_sim.atmosphere import (
    AtmoState,
    AtmosphereUSSA76,
    geometric_to_geopotential,
    geopotential_to_geometric,
)

_GEO_RADIUS_M = 6356.766e3

# 关键校验点 (位势高度 m, 温度 K, 压强 Pa, 密度 kg/m3, 音速 m/s).
# 数值取自 USSA76 公开标准表; 音速按 a = sqrt(1.4 * R_spec * T) 计算.
_CHECKPOINTS: tuple[tuple[float, float, float, float, float], ...] = (
    (0.0, 288.15, 101325.0, 1.22500, 340.294),
    (11000.0, 216.65, 22632.1, 0.363918, 295.070),
    (20000.0, 216.65, 5474.89, 0.0880349, 295.070),
    (32000.0, 228.65, 868.019, 0.0132249, 303.129),
    (47000.0, 270.65, 110.906, 0.00142744, 329.799),
    (51000.0, 270.65, 66.9389, 0.000861546, 329.799),
    (71000.0, 214.65, 3.95642, 6.42078e-5, 293.704),
    (84852.0, 186.946, 0.3734, 6.9584e-6, 274.09),
)

_REL_TOL = 5e-4  # 严格于 PLAN 的 0.5% 验收线.


def _to_geometric(gp_m: float) -> float:
    return gp_m * _GEO_RADIUS_M / (_GEO_RADIUS_M - gp_m)


@pytest.fixture(name="atmo")
def _atmo() -> AtmosphereUSSA76:
    return AtmosphereUSSA76(max_altitude_m=500_000.0)


def test_standard_checkpoints(atmo: AtmosphereUSSA76) -> None:
    for gp_m, t_k, p_pa, rho, a in _CHECKPOINTS:
        state = atmo.sample(_to_geometric(gp_m))
        assert state.temperature_k == pytest.approx(t_k, rel=_REL_TOL)
        assert state.pressure_pa == pytest.approx(p_pa, rel=_REL_TOL)
        assert state.density_kg_m3 == pytest.approx(rho, rel=_REL_TOL)
        assert state.speed_of_sound_m_s == pytest.approx(a, rel=_REL_TOL)


def test_geometric_mapping_roundtrip() -> None:
    for gp_m in (0.0, 11000.0, 84852.0):
        geo = geopotential_to_geometric(gp_m)
        assert geometric_to_geopotential(geo) == pytest.approx(gp_m, rel=1e-12)
    # 84.852 km 位势高度应映射到 86 km 几何高度.
    assert geopotential_to_geometric(84852.0) == pytest.approx(86000.0, rel=1e-6)


def test_iso_extension_continuity(atmo: AtmosphereUSSA76) -> None:
    # 86 km 上下两条分支在边界连续且单调衰减.
    below = atmo.sample(85998.0)
    at_top = atmo.sample(86000.0)
    above = atmo.sample(87000.0)
    assert below.pressure_pa > at_top.pressure_pa > above.pressure_pa
    assert at_top.temperature_k == pytest.approx(186.946, rel=1e-9)
    assert at_top.density_kg_m3 > 0.0
    # 1000 m 几何高度差对应的指数衰减量级检查 (宽松容差).
    ratio = above.pressure_pa / at_top.pressure_pa
    assert math.exp(-1100.0 / 5600.0) < ratio < math.exp(-900.0 / 5400.0)


def test_monotonic_profiles(atmo: AtmosphereUSSA76) -> None:
    # 密度随高度严格递减, 温度在已知层界取极值.
    prev_rho = math.inf
    prev_t = math.inf
    for h_m in range(0, 90_000, 2_000):
        state = atmo.sample(float(h_m))
        assert state.density_kg_m3 < prev_rho
        prev_rho = state.density_kg_m3
        # 温度仅作有限性与正性检查 (层间有增有减).
        assert math.isfinite(state.temperature_k)
        assert state.temperature_k > 150.0
        prev_t = state.temperature_k
    del prev_t


def test_returns_atmo_state(atmo: AtmosphereUSSA76) -> None:
    state = atmo.sample(10_000.0)
    assert isinstance(state, AtmoState)
    assert state.altitude_m == 10_000.0


def test_invalid_inputs() -> None:
    atmo = AtmosphereUSSA76()
    with pytest.raises(ValueError):
        atmo.sample(-1.0)
    with pytest.raises(ValueError):
        atmo.sample(atmo._max_altitude_m + 1.0)  # type: ignore[attr-defined]
    with pytest.raises(ValueError):
        atmo.sample(math.nan)
    with pytest.raises(TypeError):
        atmo.sample("high")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        AtmosphereUSSA76(max_altitude_m=10_000.0)
    with pytest.raises(TypeError):
        AtmosphereUSSA76(max_altitude_m="big")  # type: ignore[arg-type]
