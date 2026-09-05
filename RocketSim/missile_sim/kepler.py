"""真空开普勒弹道解析解 (验证与初值参考用).

给定发射点 (r0, v0, gamma0) 与目标半径 r_target, 返回射程角, 飞行
时间, 远地点半径的闭式解. 仅支持椭圆亚轨道弹道:
- 0 < gamma0 < 90 度 (向上发射, 非纯垂直, 非水平以下);
- 能量为椭圆 (v0 小于逃逸速度);
- 近地点低于目标半径 (轨道必命中目标半径).

本模块不依赖 numpy/scipy, 仅标准库, 作为数值积分的独立对照.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

_EPS_ABS: float = 1e-9


@dataclass(frozen=True)
class KeplerFlight:
    """开普勒解析解结果."""

    range_rad: float          # 射程角 (rad), 从发射点到命中点
    flight_time_s: float      # 飞行时间 (s)
    time_to_apogee_s: float   # 到远地点时间 (s)
    apogee_radius_m: float    # 远地点地心距 (m)
    perigee_radius_m: float   # 近地点地心距 (m, 通常在地球内部)
    eccentricity: float       # 轨道偏心率


def _clamp_unit(x: float) -> float:
    """把余弦值夹到 [-1, 1], 吸收浮点舍入噪声."""
    if x < -1.0:
        return -1.0
    if x > 1.0:
        return 1.0
    return x


def _eccentric_anomaly(nu_rad: float, e: float) -> float:
    """由真近点角 nu 求偏近点角 E (rad), 保证与 nu 同象限."""
    cos_nu = math.cos(nu_rad)
    x = (e + cos_nu) / (1.0 + e * cos_nu)
    e_rad = math.acos(_clamp_unit(x))
    if nu_rad > math.pi:
        e_rad = 2.0 * math.pi - e_rad
    return e_rad


def kepler_flight(
    mu: float,
    r0: float,
    v0: float,
    gamma0_rad: float,
    r_target: float,
) -> KeplerFlight:
    """椭圆亚轨道弹道解析解.

    参数:
        mu: 引力参数 (m^3 / s^2).
        r0: 发射点地心距 (m).
        v0: 发射速度 (m/s).
        gamma0_rad: 发射航迹角 (rad), 须在 (0, pi/2) 开区间.
        r_target: 目标半径 (m), 须小于 r0 且大于近地点半径.

    异常:
        TypeError: 参数类型错误.
        ValueError: 输入不满足椭圆亚轨道条件 (含描述信息).
    """
    for name, value in (("mu", mu), ("r0", r0), ("v0", v0), ("r_target", r_target)):
        if not isinstance(value, (int, float)):
            raise TypeError(f"{name} 必须为数值")
        if not math.isfinite(value) or value <= 0.0:
            raise ValueError(f"{name} 必须为有限正数, 收到 {value!r}")
    if not isinstance(gamma0_rad, (int, float)):
        raise TypeError("gamma0_rad 必须为数值")
    if not math.isfinite(gamma0_rad):
        raise ValueError("gamma0_rad 必须为有限值")
    if gamma0_rad <= 0.0 or gamma0_rad >= math.pi / 2.0:
        raise ValueError(
            "gamma0_rad 必须在 (0, pi/2) 开区间 (向上且非纯垂直发射)"
        )
    if r0 <= r_target:
        raise ValueError(f"r0={r0} 必须大于 r_target={r_target} (发射点高于目标)")

    h_ang = r0 * v0 * math.cos(gamma0_rad)  # 比角动量 (m^2 / s)
    energy = 0.5 * v0 * v0 - mu / r0        # 比机械能 (m^2 / s^2)
    if energy >= 0.0:
        raise ValueError(
            f"能量非负 ({energy:.6g}), 为抛物线/双曲轨道, 本解析仅支持椭圆亚轨道"
        )
    p = h_ang * h_ang / mu
    e_sq = 1.0 + 2.0 * energy * h_ang * h_ang / (mu * mu)
    e = math.sqrt(max(e_sq, 0.0))
    if e >= 1.0 - _EPS_ABS:
        raise ValueError(f"偏心率 e={e:.9f} 接近或超过 1, 非椭圆轨道")
    perigee = p / (1.0 + e)
    apogee = p / (1.0 - e)
    if perigee >= r_target:
        raise ValueError(
            f"近地点 {perigee:.3g} m 不低于目标半径 {r_target:.3g} m, 轨道不命中"
        )

    # 发射点真近点角: 用 atan2 同时确定象限 (上行段 sin(nu) > 0).
    cos_nu0 = (p / r0 - 1.0) / e
    sin_nu0 = (v0 * math.sin(gamma0_rad)) * h_ang / (mu * e)
    if cos_nu0 < -1.0 - 1e-6 or cos_nu0 > 1.0 + 1e-6:
        raise ValueError(f"发射点不在可达半径范围内 (cos_nu0={cos_nu0:.9f})")
    nu0 = math.atan2(sin_nu0, _clamp_unit(cos_nu0))
    if nu0 <= 0.0:
        raise ValueError(f"发射点真近点角异常: nu0={nu0:.9f}")

    # 命中点真近点角: 下行段首次到达 r_target 处.
    cos_nu_t = (p / r_target - 1.0) / e
    if cos_nu_t < -1.0 - 1e-6 or cos_nu_t > 1.0 + 1e-6:
        raise ValueError(f"目标半径不可达 (cos_nu_t={cos_nu_t:.9f})")
    nu_tilde = math.acos(_clamp_unit(cos_nu_t))
    nu_impact = 2.0 * math.pi - nu_tilde
    range_rad = nu_impact - nu0
    if range_rad <= 1e-9:
        raise ValueError(
            f"目标在发射方向后方或过近 (射程角 {range_rad:.6g} rad)"
        )

    # 飞行时间: 开普勒方程 (M = E - e*sin(E)).
    semi_major = -mu / (2.0 * energy)
    mean_motion = math.sqrt(mu / (semi_major**3))
    e0 = _eccentric_anomaly(nu0, e)
    e_impact = _eccentric_anomaly(nu_impact, e)
    m0 = e0 - e * math.sin(e0)
    m_impact = e_impact - e * math.sin(e_impact)
    flight_time = (m_impact - m0) / mean_motion
    time_to_apogee = (math.pi - m0) / mean_motion
    if flight_time <= 0.0 or time_to_apogee < 0.0:
        raise ValueError(f"飞行时间异常: {flight_time:.6g} s")

    return KeplerFlight(
        range_rad=range_rad,
        flight_time_s=flight_time,
        time_to_apogee_s=time_to_apogee,
        apogee_radius_m=apogee,
        perigee_radius_m=perigee,
        eccentricity=e,
    )


__all__ = ["KeplerFlight", "kepler_flight"]
