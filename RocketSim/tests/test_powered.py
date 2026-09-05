"""动力飞行积分用例 (M2 验收).

验收标准 (PLAN M2):
- 单弹道 q/Mach/gamma 剖面合理 (助推穿过跨声速, 有限正动压);
- 无动力段能量单调耗散 (阻力做功为负);
- 关机/远地点/命中事件顺序正确.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from missile_sim.aerodynamics import AerodynamicModel, BodyGeometry
from missile_sim.atmosphere import AtmosphereUSSA76
from missile_sim.constants import EARTH_MU_SI, EARTH_RADIUS_TRAJ_M
from missile_sim.flight import impact_ground_range_m, simulate_powered_flight
from missile_sim.propulsion import ConstantBurnRate, Motor
from missile_sim.steering import ClimbSchedule, PitchOverSchedule
from missile_sim.vehicle import Missile

_RE = EARTH_RADIUS_TRAJ_M


def _build_missile(name: str) -> Missile:
    burn = ConstantBurnRate(3500.0, 3500.0 / 42.0)
    motor = Motor(
        dry_mass_kg=1500.0,
        propellant_mass_kg=3500.0,
        isp_sea_level_s=245.0,
        isp_vacuum_s=285.0,
        burn_rate=burn,
    )
    return Missile(
        name=name, motor=motor, geometry=BodyGeometry(0.9, 3.6, 3.4)
    )


@pytest.fixture(scope="module")
def atmo() -> AtmosphereUSSA76:
    # 动力弹道远地点可达数百 km, 大气模型须覆盖到 1000 km.
    return AtmosphereUSSA76(max_altitude_m=1_000_000.0)


def _profiles(result: object, atmo: AtmosphereUSSA76) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """按积分结果重算剖面: (高度 m, 马赫数, 动压 Pa)."""
    states = result.states  # type: ignore[attr-defined]
    alt = states[:, 0] - _RE
    v = states[:, 2]
    mach = np.empty_like(v)
    q = np.empty_like(v)
    for i, a in enumerate(alt):
        st = atmo.sample(float(a))
        mach[i] = v[i] / st.speed_of_sound_m_s
        q[i] = 0.5 * st.density_kg_m3 * v[i] * v[i]
    return alt, mach, q


def test_air_launched_full_flight(atmo: AtmosphereUSSA76) -> None:
    """空射基线: 10 km / Mach 0.85 水平投放, 拉起到 25 度后重力转弯."""
    missile = _build_missile("alb")
    v0 = 0.85 * atmo.sample(10_000.0).speed_of_sound_m_s
    res = simulate_powered_flight(
        missile,
        atmo,
        ClimbSchedule(math.radians(25.0)),
        r0_m=_RE + 10_000.0,
        v0_m_s=v0,
        gamma0_rad=0.0,
        t_max_s=3600.0,
        rtol=1e-10,
        atol=1e-8,
    )
    assert res.success, res.message
    assert {"burnout", "apogee", "impact"} <= set(res.events)
    times = [res.events[k].time_s for k in ("burnout", "apogee", "impact")]
    assert times == sorted(times)
    bo = res.events["burnout"].state
    assert bo[2] > v0  # 关机点净加速.
    alt, mach, q = _profiles(res, atmo)
    assert alt.min() >= -1.0
    assert 1.0 < mach.max() < 15.0  # 穿过跨声速, 未出现离谱马赫.
    assert 0.0 < q.max() < 2.0e6
    h_bo = bo[0] - _RE
    h_ap = res.events["apogee"].state[0] - _RE
    assert h_ap > h_bo > 0.0
    impact = res.events["impact"].state
    assert impact[2] > 0.0
    assert impact_ground_range_m(res) > 0.0
    assert res.events["impact"].state[0] == pytest.approx(_RE, abs=1.0)


def test_ground_launched_vertical_pitch_over(atmo: AtmosphereUSSA76) -> None:
    """地射基线: 地面垂直起飞, 保持 2 s 后以 3 度/s 程序下压."""
    missile = _build_missile("glb")
    # 垂直奇点规避: 以点火后 ~0.3 s 的闭式短步状态起步 (M1 记录的边界).
    res = simulate_powered_flight(
        missile,
        atmo,
        PitchOverSchedule(hold_time_s=2.0, turn_rate_rad_s=math.radians(3.0)),
        r0_m=_RE,
        v0_m_s=10.0,
        gamma0_rad=math.pi / 2.0,
        t_max_s=3600.0,
        rtol=1e-10,
        atol=1e-8,
    )
    assert res.success, res.message
    assert {"burnout", "apogee", "impact"} <= set(res.events)
    times = [res.events[k].time_s for k in ("burnout", "apogee", "impact")]
    assert times == sorted(times)
    bo = res.events["burnout"].state
    # 转弯效果: 关机点航迹角明显低于 90 度且高于 0.
    gamma_bo_deg = math.degrees(bo[3])
    assert 5.0 < gamma_bo_deg < 85.0
    assert bo[2] > 1000.0
    assert impact_ground_range_m(res) > 0.0


def test_drag_coast_energy_monotonic_decrease(atmo: AtmosphereUSSA76) -> None:
    """无推力纯大气滑翔: 比机械能单调耗散 (阻力恒做负功)."""
    missile = _build_missile("coast")
    res = simulate_powered_flight(
        missile,
        atmo,
        ClimbSchedule(math.radians(5.0)),
        r0_m=_RE + 10_000.0,
        v0_m_s=700.0,
        gamma0_rad=math.radians(5.0),
        t_max_s=1500.0,
        rtol=1e-10,
        atol=1e-8,
        enable_thrust=False,
    )
    assert res.success, res.message
    v = res.states[:, 2]
    r = res.states[:, 0]
    energy = 0.5 * v * v - EARTH_MU_SI / r
    max_rise = float(np.max(np.diff(energy)))
    assert max_rise <= 1e-9 * abs(energy[0])  # 数值噪声级内的单调下降.
    assert energy[-1] < energy[0] - 1.0e3  # 净耗散显著.


def test_invalid_inputs(atmo: AtmosphereUSSA76) -> None:
    missile = _build_missile("bad")
    with pytest.raises(ValueError):
        simulate_powered_flight(
            missile, atmo, ClimbSchedule(0.5), r0_m=_RE, v0_m_s=0.0, gamma0_rad=0.1
        )
    with pytest.raises(ValueError):
        simulate_powered_flight(
            missile,
            atmo,
            ClimbSchedule(0.5),
            r0_m=_RE,
            v0_m_s=100.0,
            gamma0_rad=math.pi,  # 朝下发射在 M2 不支持.
        )
    with pytest.raises(TypeError):
        simulate_powered_flight(
            missile, atmo, ClimbSchedule(0.5), r0_m=_RE, v0_m_s=100.0,
            gamma0_rad=0.1, enable_thrust="yes",  # type: ignore[arg-type]
        )
    with pytest.raises(TypeError):
        simulate_powered_flight(
            "not-a-missile",  # type: ignore[arg-type]
            atmo,
            ClimbSchedule(0.5),
            r0_m=_RE,
            v0_m_s=100.0,
            gamma0_rad=0.1,
        )


def test_guidance_lift_changes_ballistic_endgame() -> None:
    """关机后升力指令应产生滑翔记账且轨迹仍成功 (PLAN 11b 冒烟)."""
    from missile_sim.steering import PiecewiseNormalGuidance
    aero_lift = AerodynamicModel(
        BodyGeometry(0.9, 3.6, 3.4),
        cl_alpha_1_rad=2.8, induced_drag_factor=0.12,
        alpha_max_lift_rad=math.radians(10.0),
    )
    motor = Motor(
        dry_mass_kg=1500.0, propellant_mass_kg=3500.0,
        isp_sea_level_s=245.0, isp_vacuum_s=285.0,
        burn_rate=ConstantBurnRate(3500.0, 3500.0 / 42.0),
    )
    guidance = PiecewiseNormalGuidance(n1_g=0.5, t1_s=900.0, n2_g=0.0, dur_s=1.0)
    missile = Missile("lift", motor, BodyGeometry(0.9, 3.6, 3.4), aero_lift, post_boost_guidance=guidance)
    res = simulate_powered_flight(
        missile, AtmosphereUSSA76(max_altitude_m=1_000_000.0),
        ClimbSchedule(math.radians(5.0)),
        r0_m=EARTH_RADIUS_TRAJ_M + 10_000.0, v0_m_s=700.0,
        gamma0_rad=math.radians(5.0), t_max_s=1500.0,
        rtol=1e-9, atol=1e-8, enable_thrust=False,
    )
    assert res.success, res.message
