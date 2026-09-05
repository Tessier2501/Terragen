"""发动机模型用例 (F(h) 背压模型 + 燃烧率形状族闭合).

验收标准 (PLAN M2): 形状族总冲守恒 (同推进剂下各形状总冲一致),
推力随高度增大, 质量流率闭合 int m_dot dt = m_prop.
"""

from __future__ import annotations

import math

import pytest

from missile_sim.propulsion import (
    BurnRateBase,
    ConstantBurnRate,
    Motor,
    RegressiveLinearBurnRate,
    TwoLevelBurnRate,
    specific_impulse_at_pressure,
)

M_PROPELLANT = 3500.0
ISP_SL = 245.0
ISP_VAC = 285.0
# 恒面基线: ~83.3 kg/s, 燃烧 ~42 s (与 PLAN 基线表一致).
M_DOT_BASE = M_PROPELLANT / 42.0

_P_SEA = 101325.0
_P_VAC = 0.0


def _motor(burn_rate: BurnRateBase) -> Motor:
    return Motor(
        dry_mass_kg=1500.0,
        propellant_mass_kg=M_PROPELLANT,
        isp_sea_level_s=ISP_SL,
        isp_vacuum_s=ISP_VAC,
        burn_rate=burn_rate,
    )


def _sample_total_impulse(motor: Motor, p_amb: float) -> float:
    """以固定环境压强近似积分总冲 (形状无关对照: 总冲应相等)."""
    n = 2000
    h = motor.burn_rate.burn_time_s / n
    total = 0.0
    for i in range(n):
        t = (i + 0.5) * h
        total += motor.thrust(t, p_amb) * h
    return total


def test_specific_impulse_anchors() -> None:
    assert specific_impulse_at_pressure(ISP_SL, ISP_VAC, _P_SEA) == pytest.approx(ISP_SL)
    assert specific_impulse_at_pressure(ISP_SL, ISP_VAC, _P_VAC) == pytest.approx(ISP_VAC)
    isp_mid = specific_impulse_at_pressure(ISP_SL, ISP_VAC, _P_SEA / 2.0)
    assert ISP_SL < isp_mid < ISP_VAC


def _shape_variants() -> list[BurnRateBase]:
    const = ConstantBurnRate(M_PROPELLANT, M_DOT_BASE)
    reg = RegressiveLinearBurnRate(M_PROPELLANT, 1.3 * M_DOT_BASE, 0.7 * M_DOT_BASE)
    boost = TwoLevelBurnRate(M_PROPELLANT, 1.6 * M_DOT_BASE, 0.6 * M_DOT_BASE, 10.0)
    return [const, reg, boost]


def test_propellant_closure_all_shapes() -> None:
    """各形状 int m_dot dt == m_prop 且燃烧结束总质量为干重."""
    for burn_rate in _shape_variants():
        n = 2000
        h = burn_rate.burn_time_s / n
        consumed = 0.0
        for i in range(n):
            consumed += burn_rate.mass_flow_rate((i + 0.5) * h) * h
        assert consumed == pytest.approx(M_PROPELLANT, rel=1e-9)
        assert burn_rate.mass_flow_rate(burn_rate.burn_time_s + 1.0) == 0.0
        motor = _motor(burn_rate)
        assert motor.mass(burn_rate.burn_time_s + 1.0) == pytest.approx(1500.0)


def test_total_impulse_conserved_across_shapes() -> None:
    """同推进剂同 Isp 下, 任意形状总冲 (海平面) 应相等 (动量定理)."""
    impulses = [_sample_total_impulse(_motor(br), _P_SEA) for br in _shape_variants()]
    ref = impulses[0]
    for value in impulses[1:]:
        assert value == pytest.approx(ref, rel=1e-9)
    # 理论值: m_prop * g0 * Isp_SL.
    expected = M_PROPELLANT * 9.80665 * ISP_SL
    assert ref == pytest.approx(expected, rel=1e-6)


def test_thrust_grows_with_altitude() -> None:
    motor = _motor(ConstantBurnRate(M_PROPELLANT, M_DOT_BASE))
    t_mid = motor.burn_rate.burn_time_s * 0.5
    f_sea = motor.thrust(t_mid, _P_SEA)
    f_vac = motor.thrust(t_mid, _P_VAC)
    assert f_vac > f_sea
    assert f_sea == pytest.approx(M_DOT_BASE * 9.80665 * ISP_SL)
    assert f_vac == pytest.approx(M_DOT_BASE * 9.80665 * ISP_VAC)


def test_motor_anchors_match_plan_baseline() -> None:
    motor = _motor(ConstantBurnRate(M_PROPELLANT, M_DOT_BASE))
    assert motor.burn_rate.burn_time_s == pytest.approx(42.0)
    # 海平面推力 = m_dot * g0 * Isp_SL ~ 200.2 kN (T/W0 ~ 4.1, 量级符合 PLAN).
    assert motor.thrust(1.0, _P_SEA) == pytest.approx(
        M_DOT_BASE * 9.80665 * ISP_SL, rel=1e-9
    )


def test_invalid_inputs() -> None:
    with pytest.raises(ValueError):
        ConstantBurnRate(0.0, M_DOT_BASE)
    with pytest.raises(ValueError):
        ConstantBurnRate(M_PROPELLANT, -1.0)
    with pytest.raises(ValueError):
        RegressiveLinearBurnRate(M_PROPELLANT, 100.0, 200.0)  # 增面被禁
    with pytest.raises(ValueError):
        TwoLevelBurnRate(M_PROPELLANT, 500.0, 50.0, 10.0)  # 助推段超总质量
    with pytest.raises(TypeError):
        ConstantBurnRate("p", M_DOT_BASE)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        Motor(
            dry_mass_kg=1500.0,
            propellant_mass_kg=3500.0,
            isp_sea_level_s=285.0,
            isp_vacuum_s=245.0,  # 违反 Isp_vac > Isp_SL
            burn_rate=ConstantBurnRate(M_PROPELLANT, M_DOT_BASE),
        )
    with pytest.raises(ValueError):
        specific_impulse_at_pressure(ISP_SL, ISP_VAC, -1.0)
    with pytest.raises(ValueError):
        motor_br = ConstantBurnRate(M_PROPELLANT, M_DOT_BASE)
        _motor(motor_br).thrust(-1.0, _P_SEA)
