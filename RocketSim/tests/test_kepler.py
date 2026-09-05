"""kepler_flight 解析解单元用例 (性质与输入校验, 数值对拍在 test_flight)."""

from __future__ import annotations

import math

import pytest

from missile_sim.constants import EARTH_MU_SI, EARTH_RADIUS_TRAJ_M
from missile_sim.kepler import kepler_flight


def test_basic_properties() -> None:
    r0 = EARTH_RADIUS_TRAJ_M + 50.0e3
    res = kepler_flight(EARTH_MU_SI, r0, 2600.0, math.radians(35.0), EARTH_RADIUS_TRAJ_M)
    assert res.flight_time_s > 0.0
    assert res.time_to_apogee_s > 0.0
    assert res.time_to_apogee_s < res.flight_time_s
    assert 0.0 < res.range_rad < math.pi
    assert res.perigee_radius_m < EARTH_RADIUS_TRAJ_M  # 亚轨道: 近地点在地内
    assert res.apogee_radius_m > r0
    assert 0.0 < res.eccentricity < 1.0


@pytest.mark.parametrize(
    ("h0_m", "v0", "gamma0_deg"),
    [
        (30.0e3, 2000.0, 55.0),
        (50.0e3, 2600.0, 35.0),
        (80.0e3, 3200.0, 20.0),
        (100.0e3, 2400.0, 45.0),
    ],
)
def test_cases_consistent(h0_m: float, v0: float, gamma0_deg: float) -> None:
    r0 = EARTH_RADIUS_TRAJ_M + h0_m
    res = kepler_flight(
        EARTH_MU_SI, r0, v0, math.radians(gamma0_deg), EARTH_RADIUS_TRAJ_M
    )
    # 目标半径必落在近地点与远地点之间.
    assert res.perigee_radius_m < EARTH_RADIUS_TRAJ_M < res.apogee_radius_m
    assert 0.0 < res.range_rad < 2.0 * math.pi


def test_invalid_inputs() -> None:
    r0 = EARTH_RADIUS_TRAJ_M + 50.0e3
    mu = EARTH_MU_SI
    rt = EARTH_RADIUS_TRAJ_M
    with pytest.raises(ValueError):
        kepler_flight(mu, r0, 2600.0, 0.0, rt)            # 水平发射 (M1 限制)
    with pytest.raises(ValueError):
        kepler_flight(mu, r0, 2600.0, math.pi / 2.0, rt)  # 纯垂直
    with pytest.raises(ValueError):
        kepler_flight(mu, r0, 12_000.0, math.radians(35.0), rt)  # 逃逸速度
    with pytest.raises(ValueError):
        kepler_flight(mu, EARTH_RADIUS_TRAJ_M, 2600.0, math.radians(35.0), rt)  # r0<=rt
    with pytest.raises(ValueError):
        kepler_flight(mu, r0, 2600.0, math.radians(35.0), r0 + 100.0e3)  # 目标过高
    with pytest.raises(ValueError):
        kepler_flight(0.0, r0, 2600.0, math.radians(35.0), rt)
    with pytest.raises(TypeError):
        kepler_flight("mu", r0, 2600.0, math.radians(35.0), rt)  # type: ignore[arg-type]
