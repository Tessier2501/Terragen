"""Cd(M) 半经验合成模型用例.

验收标准 (PLAN M2): Cd(M) 量级与公开细长体数据对照 (0.05-0.6 带内,
形状: 跨声速峰高于超声速平台, 平台随头部细长度增大而下降).
"""

from __future__ import annotations

import math

import pytest

from missile_sim.aerodynamics import AerodynamicModel, BodyGeometry

# 典型占位弹体: 直径 0.9 m, 头部细长度 4, 全长 ~7 m.
GEO = BodyGeometry(diameter_m=0.9, nose_length_m=3.6, body_length_m=3.4)
# 海平面附近标准状态 (T=288.15 K, rho=1.225, a~340.3).
_RHO_SL = 1.225
_T_SL = 288.15


def _cd(model: AerodynamicModel, mach: float) -> float:
    return model.cd_zero_lift(mach, _RHO_SL, mach * 340.294, _T_SL)


def test_default_geometry_basic() -> None:
    assert GEO.reference_area_m2 == pytest.approx(math.pi * 0.45**2)
    assert GEO.total_length_m == pytest.approx(7.0)
    assert 0.0 <= GEO.cd_wave_infinite < 0.4
    assert GEO.wet_to_ref_ratio > 5.0  # 长细比 ~7.8 的湿面积比.


def test_cd_magnitude_band() -> None:
    model = AerodynamicModel(GEO)
    for mach in (0.3, 0.8, 1.05, 2.0, 4.0, 6.0):
        cd = _cd(model, mach)
        assert 0.05 <= cd <= 0.6, f"M={mach} 时 Cd={cd} 超出量级带"


def test_cd_shape_transonic_peak() -> None:
    model = AerodynamicModel(GEO)
    cd_sub = _cd(model, 0.5)
    cd_peak = max(_cd(model, m) for m in (0.9, 1.0, 1.05, 1.1))
    cd_plateau = _cd(model, 4.0)
    assert cd_peak > cd_sub
    assert cd_peak > cd_plateau
    assert cd_plateau <= 1.6 * cd_peak  # 峰高有界.


def test_cd_increases_with_mach_in_transonic_ramp() -> None:
    model = AerodynamicModel(GEO)
    cds = [_cd(model, m) for m in (0.75, 0.85, 0.95, 1.0)]
    assert cds == sorted(cds)  # 0.75 -> 1.0 单调上升.


def test_drag_force_grows_with_density() -> None:
    # 阻力系数随 Re 增大而略降, 但阻力力 D = 0.5*rho*v^2*S*Cd 随密度增大.
    model = AerodynamicModel(GEO)
    v = 170.0
    cd_hi = model.cd_zero_lift(0.5, _RHO_SL, v, _T_SL)
    cd_lo = model.cd_zero_lift(0.5, _RHO_SL * 0.1, v, _T_SL)
    d_hi = 0.5 * _RHO_SL * v * v * GEO.reference_area_m2 * cd_hi
    d_lo = 0.5 * (_RHO_SL * 0.1) * v * v * GEO.reference_area_m2 * cd_lo
    assert d_hi > d_lo


def test_wave_drag_vanishes_subsonic() -> None:
    model = AerodynamicModel(GEO)
    # 同一速度下 0.1 与 0.5 马赫均无波阻, 摩阻雷诺数相同, Cd 应完全相等.
    cd_m01 = model.cd_zero_lift(0.1, _RHO_SL, 170.0, _T_SL)
    cd_m05 = model.cd_zero_lift(0.5, _RHO_SL, 170.0, _T_SL)
    assert abs(cd_m01 - cd_m05) < 1e-12


def test_longer_nose_lowers_wave_drag() -> None:
    geo_slender = BodyGeometry(diameter_m=0.9, nose_length_m=5.4, body_length_m=1.6)
    assert geo_slender.cd_wave_infinite < GEO.cd_wave_infinite


def test_invalid_inputs() -> None:
    with pytest.raises(ValueError):
        BodyGeometry(diameter_m=0.0, nose_length_m=3.6, body_length_m=3.4)
    with pytest.raises(TypeError):
        BodyGeometry(diameter_m="x", nose_length_m=3.6, body_length_m=3.4)  # type: ignore[arg-type]
    model = AerodynamicModel(GEO)
    with pytest.raises(ValueError):
        model.cd_zero_lift(-0.1, _RHO_SL, 100.0, _T_SL)
    with pytest.raises(ValueError):
        model.cd_zero_lift(1.0, 0.0, 100.0, _T_SL)
    with pytest.raises(TypeError):
        model.cd_zero_lift("m", _RHO_SL, 100.0, _T_SL)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        AerodynamicModel(geometry="not-a-body")  # type: ignore[arg-type]
