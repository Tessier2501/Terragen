"""飞行积分与事件骨架的物理验证用例.

验收标准 (PLAN M1):
- 真空弹道与开普勒解析射程/飞行时间对拍误差 < 0.1% (实测远低于);
- 无推力无阻力能量守恒相对漂移 < 1e-8;
- 远地点/命中事件定位正确.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from missile_sim.constants import EARTH_MU_SI, EARTH_RADIUS_TRAJ_M
from missile_sim.flight import (
    EventSpec,
    impact_ground_range_m,
    impact_event_spec,
    simulate_free_flight,
)
from missile_sim.kepler import kepler_flight

_SOLVER_RTOL = 1e-10
_SOLVER_ATOL = 1e-8


@pytest.mark.parametrize(
    ("h0_m", "v0", "gamma0_deg"),
    [
        (30.0e3, 2000.0, 55.0),
        (50.0e3, 2600.0, 35.0),
        (80.0e3, 3200.0, 20.0),
        (100.0e3, 2400.0, 45.0),
    ],
)
def test_numeric_matches_kepler(h0_m: float, v0: float, gamma0_deg: float) -> None:
    """数值积分射程角/飞行时间/远地点与开普勒解析解对拍."""
    r0 = EARTH_RADIUS_TRAJ_M + h0_m
    gamma0 = math.radians(gamma0_deg)
    ana = kepler_flight(EARTH_MU_SI, r0, v0, gamma0, EARTH_RADIUS_TRAJ_M)
    res = simulate_free_flight(
        r0_m=r0,
        v0_m_s=v0,
        gamma0_rad=gamma0,
        mu=EARTH_MU_SI,
        r_target_m=EARTH_RADIUS_TRAJ_M,
        rtol=_SOLVER_RTOL,
        atol=_SOLVER_ATOL,
    )
    assert res.success, res.message

    num_range = impact_ground_range_m(res) / EARTH_RADIUS_TRAJ_M
    assert num_range == pytest.approx(ana.range_rad, rel=1e-5)
    assert res.events["impact"].time_s == pytest.approx(ana.flight_time_s, rel=1e-5)
    apogee = res.events["apogee"]
    assert apogee.time_s == pytest.approx(ana.time_to_apogee_s, rel=1e-5)
    assert apogee.state[0] == pytest.approx(ana.apogee_radius_m, rel=1e-6)
    # 命中事件状态的地心距必须精确落在目标半径上.
    assert res.events["impact"].state[0] == pytest.approx(
        EARTH_RADIUS_TRAJ_M, abs=1.0
    )
    # 远地点径向速度应接近零 (事件根的插值精度).
    assert abs(
        float(apogee.state[2]) * math.sin(float(apogee.state[3]))
    ) < 1e-6


def test_energy_conservation_no_drag() -> None:
    """无推力无阻力时比机械能 E = v^2/2 - mu/r 全程守恒."""
    r0 = EARTH_RADIUS_TRAJ_M + 80.0e3
    v0 = 3200.0
    gamma0 = math.radians(30.0)
    res = simulate_free_flight(
        r0_m=r0,
        v0_m_s=v0,
        gamma0_rad=gamma0,
        mu=EARTH_MU_SI,
        r_target_m=EARTH_RADIUS_TRAJ_M,
        rtol=1e-11,
        atol=1e-8,
    )
    assert res.success
    v = res.states[:, 2]
    r = res.states[:, 0]
    energy = 0.5 * v * v - EARTH_MU_SI / r
    energy0 = 0.5 * v0 * v0 - EARTH_MU_SI / r0
    drift = np.max(np.abs(energy - energy0) / abs(energy0))
    assert drift < 1e-8


def test_impact_event_low_altitude() -> None:
    """低空快弹道: 直接触发命中事件 (无远地点前命中不现实, 此处验证事件)."""
    # 向上发射必然先经远地点, 故此处仅校验事件接口可用.
    spec: EventSpec = impact_event_spec(EARTH_RADIUS_TRAJ_M)
    assert spec.name == "impact"
    assert spec.direction == -1


def test_invalid_inputs() -> None:
    r0 = EARTH_RADIUS_TRAJ_M + 50.0e3
    with pytest.raises(ValueError):
        simulate_free_flight(r0_m=EARTH_RADIUS_TRAJ_M, v0_m_s=2600.0, gamma0_rad=0.5)
    with pytest.raises(ValueError):
        simulate_free_flight(r0_m=r0, v0_m_s=0.0, gamma0_rad=0.5)
    with pytest.raises(ValueError):
        simulate_free_flight(r0_m=r0, v0_m_s=2600.0, gamma0_rad=0.0)
    with pytest.raises(ValueError):
        simulate_free_flight(r0_m=r0, v0_m_s=2600.0, gamma0_rad=math.pi / 2.0)
    with pytest.raises(ValueError):
        simulate_free_flight(r0_m=r0, v0_m_s=2600.0, gamma0_rad=0.5, t_max_s=0.0)
    with pytest.raises(TypeError):
        simulate_free_flight(r0_m="r0", v0_m_s=2600.0, gamma0_rad=0.5)  # type: ignore[arg-type]
