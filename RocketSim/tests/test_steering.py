"""转向模块用例: 程序角族语义 + TVC/舵法向过载预算."""

from __future__ import annotations

import math

import pytest

from missile_sim.steering import (
    ClimbSchedule,
    NormalAccelBudget,
    PitchOverSchedule,
    SteeringAuthority,
)

_HALF_PI = math.pi / 2.0


def test_climb_schedule_pullup_and_lock() -> None:
    s = ClimbSchedule(math.radians(25.0))
    # 平飞时推力指向上方 25 度 (拉起).
    assert s.angle(0.0, 0.0) == pytest.approx(math.radians(25.0))
    # 航迹角追上目标后锁为重力转弯 (推力沿速度).
    assert s.angle(10.0, math.radians(40.0)) == pytest.approx(math.radians(40.0))


def test_pitch_over_schedule() -> None:
    s = PitchOverSchedule(hold_time_s=2.0, turn_rate_rad_s=math.radians(3.0))
    # 保持段: 垂直.
    assert s.angle(1.0, _HALF_PI) == pytest.approx(_HALF_PI)
    # 下压段: 程序角低于航迹角时压速度矢量.
    prog_at_5s = _HALF_PI - math.radians(3.0) * 3.0
    assert s.angle(5.0, _HALF_PI) == pytest.approx(prog_at_5s)
    # 程序角高于航迹角时保持重力转弯.
    assert s.angle(5.0, math.radians(60.0)) == pytest.approx(math.radians(60.0))


def test_pitch_over_clamps_at_level() -> None:
    s = PitchOverSchedule(hold_time_s=0.0, turn_rate_rad_s=math.radians(30.0))
    # 长时间下压不越过水平面.
    assert s.angle(60.0, math.radians(12.0)) == pytest.approx(0.0)


def test_steering_authority_budget() -> None:
    auth = SteeringAuthority()
    thrust = 200_000.0
    mass = 4000.0
    s_ref = 0.636
    budget = auth.available_normal_accel(thrust, mass, 100_000.0, s_ref)
    assert isinstance(budget, NormalAccelBudget)
    # TVC+燃气舵: (200000/4000) * sin(22 度) (12 摆角 + 10 燃气舵).
    assert budget.tvc_m_s2 == pytest.approx(
        (thrust / mass) * math.sin(math.radians(22.0))
    )
    # 舵项 = q * S * C_N_alpha * alpha_max (小攻角线性, alpha 用弧度).
    assert budget.fins_m_s2 == pytest.approx(
        100_000.0 * s_ref * 8.0 * math.radians(8.0) / mass
    )


def test_fins_vanish_in_vacuum() -> None:
    auth = SteeringAuthority()
    b0 = auth.available_normal_accel(200_000.0, 4000.0, 0.0, 0.636)
    assert b0.fins_m_s2 == 0.0
    assert b0.tvc_m_s2 > 0.0  # TVC 与高度无关.


def test_invalid_inputs() -> None:
    with pytest.raises(ValueError):
        PitchOverSchedule(hold_time_s=-1.0, turn_rate_rad_s=1.0)
    with pytest.raises(TypeError):
        PitchOverSchedule(hold_time_s="x", turn_rate_rad_s=1.0)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        ClimbSchedule(target_angle_rad=0.0)
    with pytest.raises(ValueError):
        ClimbSchedule(target_angle_rad=math.pi)  # type: ignore[arg-type]
    auth = SteeringAuthority()
    with pytest.raises(ValueError):
        auth.available_normal_accel(200_000.0, 0.0, 1000.0, 0.636)
    with pytest.raises(ValueError):
        auth.available_normal_accel(200_000.0, 4000.0, -1.0, 0.636)
    with pytest.raises(ValueError):
        SteeringAuthority(alpha_max_rad=math.pi)
    with pytest.raises(TypeError):
        SteeringAuthority(gimbal_max_rad="x")  # type: ignore[arg-type]


def test_command_allocation_tvc_first_and_saturation() -> None:
    auth = SteeringAuthority()
    thrust = 200_000.0
    mass = 4000.0
    s_ref = 0.636
    q_pa = 50_000.0
    # 小偏转: 全部由 TVC 承担, 无攻角, 不饱和.
    cmd = auth.command(0.1, 0.0, thrust, mass, q_pa, s_ref)
    assert cmd.delta_rad == pytest.approx(0.1)
    assert cmd.alpha_rad == pytest.approx(0.0)
    assert not cmd.saturated
    assert cmd.normal_accel_m_s2 == pytest.approx(
        (thrust / mass) * math.sin(0.1)
    )
    # 大偏转: 摆角 10 度封顶, 攻角 8 度封顶, 饱和.
    cmd2 = auth.command(math.radians(40.0), 0.0, thrust, mass, q_pa, s_ref)
    assert cmd2.delta_rad == pytest.approx(math.radians(22.0))
    assert cmd2.alpha_rad == pytest.approx(math.radians(8.0))
    assert cmd2.saturated
    expected_an = (
        (thrust / mass) * math.sin(math.radians(22.0))
        + q_pa * s_ref * 8.0 * math.radians(8.0) / mass
    )
    assert cmd2.normal_accel_m_s2 == pytest.approx(expected_an)
    # 负偏转对称.
    cmd3 = auth.command(-math.radians(40.0), 0.0, thrust, mass, q_pa, s_ref)
    assert cmd3.delta_rad == pytest.approx(-math.radians(22.0))
    assert cmd3.alpha_rad == pytest.approx(-math.radians(8.0))
    assert cmd3.normal_accel_m_s2 == pytest.approx(-expected_an)


def test_command_alpha_bridges_after_thrust_cap() -> None:
    auth = SteeringAuthority()
    # 期望偏转 25 度: 摆角 12 + 燃气舵 10 = 22, 攻角补 3, 不饱和.
    cmd = auth.command(math.radians(25.0), 0.0, 200_000.0, 4000.0, 0.0, 0.636)
    assert cmd.delta_rad == pytest.approx(math.radians(22.0))
    assert cmd.alpha_rad == pytest.approx(math.radians(3.0))
    assert not cmd.saturated
