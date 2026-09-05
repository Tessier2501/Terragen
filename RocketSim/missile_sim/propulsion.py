"""发动机: 推力-高度模型与固体燃烧率形状族 (M2).

物理模型:
- 比冲只随环境背压变化 (喷管等比例缩放假设): Isp(p_a) = Isp_vac
  - (p_a / p_a_SL) * (Isp_vac - Isp_SL), 推力 F(h, t) = m_dot(t) * g0
  * Isp(p_a(h)).
- 简化声明: 真实喷管面积固定, 流量偏离设计点时 Isp(h) 会有小偏移;
  本模型按等比例缩放吸收, 偏移量级 < 数个百分比, 对轨迹寻优足够.

燃烧率形状族 (设计变量, 推进剂总质量固定后燃烧时间由积分闭合):
- ConstantBurnRate: 恒面 (端燃近似);
- RegressiveLinearBurnRate: 线性减面;
- TwoLevelBurnRate: 助推-续航两段 (星形/翼柱近似).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .constants import STANDARD_GRAVITY_M_S2

# 海平面标准压强 (Pa), 与 atmosphere.py 内部常量保持一致.
_SEA_LEVEL_PRESSURE_PA: float = 101325.0


def specific_impulse_at_pressure(
    isp_sea_level_s: float, isp_vacuum_s: float, ambient_pressure_pa: float
) -> float:
    """环境压强 p_a 下的比冲 (s), 线性背压模型."""
    for name, value in (
        ("isp_sea_level_s", isp_sea_level_s),
        ("isp_vacuum_s", isp_vacuum_s),
        ("ambient_pressure_pa", ambient_pressure_pa),
    ):
        if not isinstance(value, (int, float)) or not math.isfinite(value):
            raise TypeError(f"{name} 必须为有限数值")
    if isp_sea_level_s <= 0.0 or isp_vacuum_s <= isp_sea_level_s:
        raise ValueError("比冲须满足 0 < Isp_SL < Isp_vac")
    if ambient_pressure_pa < 0.0:
        raise ValueError(f"环境压强必须非负, 收到 {ambient_pressure_pa!r}")
    delta = (isp_vacuum_s - isp_sea_level_s) * min(
        ambient_pressure_pa / _SEA_LEVEL_PRESSURE_PA, 1.0
    )
    return isp_vacuum_s - delta


class BurnRateBase:
    """燃烧率形状基类: 推进剂闭合与质量流率接口."""

    def __init__(self, propellant_mass_kg: float) -> None:
        if not isinstance(propellant_mass_kg, (int, float)):
            raise TypeError("propellant_mass_kg 必须为数值")
        if not math.isfinite(propellant_mass_kg) or propellant_mass_kg <= 0.0:
            raise ValueError(f"推进剂质量必须为正数, 收到 {propellant_mass_kg!r}")
        self.propellant_mass_kg = float(propellant_mass_kg)
        self._validate_shape()
        self.burn_time_s = self._compute_burn_time()

    def _validate_shape(self) -> None:
        """子类校验形状参数 (合法性)."""

    def _compute_burn_time(self) -> float:
        """由推进剂闭合解出燃烧时间 (s)."""
        raise NotImplementedError

    def mass_flow_rate(self, t_s: float) -> float:
        """t 时刻质量流率 (kg/s); 燃烧结束后为 0."""
        raise NotImplementedError

    def propellant_consumed(self, t_s: float) -> float:
        """[0, t] 累计消耗的推进剂 (kg), t 超过燃烧时间取总质量."""
        raise NotImplementedError


class ConstantBurnRate(BurnRateBase):
    """恒面燃烧: m_dot(t) = 常数."""

    def __init__(self, propellant_mass_kg: float, mass_flow_kg_s: float) -> None:
        self.mass_flow_kg_s = mass_flow_kg_s
        super().__init__(propellant_mass_kg)

    def _validate_shape(self) -> None:
        if not isinstance(self.mass_flow_kg_s, (int, float)):
            raise TypeError("mass_flow_kg_s 必须为数值")
        if not math.isfinite(self.mass_flow_kg_s) or self.mass_flow_kg_s <= 0.0:
            raise ValueError(f"质量流率必须为正数, 收到 {self.mass_flow_kg_s!r}")

    def _compute_burn_time(self) -> float:
        return self.propellant_mass_kg / self.mass_flow_kg_s

    def mass_flow_rate(self, t_s: float) -> float:
        if t_s < 0.0:
            raise ValueError(f"时间必须非负, 收到 {t_s!r}")
        return self.mass_flow_kg_s if t_s < self.burn_time_s else 0.0

    def propellant_consumed(self, t_s: float) -> float:
        if t_s < 0.0:
            raise ValueError(f"时间必须非负, 收到 {t_s!r}")
        return min(t_s * self.mass_flow_kg_s, self.propellant_mass_kg)


class RegressiveLinearBurnRate(BurnRateBase):
    """线性减面: m_dot 从 m_dot_initial 线性降到 m_dot_final."""

    def __init__(
        self,
        propellant_mass_kg: float,
        mass_flow_initial_kg_s: float,
        mass_flow_final_kg_s: float,
    ) -> None:
        self.mass_flow_initial_kg_s = mass_flow_initial_kg_s
        self.mass_flow_final_kg_s = mass_flow_final_kg_s
        super().__init__(propellant_mass_kg)

    def _validate_shape(self) -> None:
        for name, value in (
            ("mass_flow_initial_kg_s", self.mass_flow_initial_kg_s),
            ("mass_flow_final_kg_s", self.mass_flow_final_kg_s),
        ):
            if not isinstance(value, (int, float)) or not math.isfinite(value):
                raise TypeError(f"{name} 必须为数值")
            if value <= 0.0:
                raise ValueError(f"{name} 必须为正数, 收到 {value!r}")
        if self.mass_flow_final_kg_s > self.mass_flow_initial_kg_s:
            raise ValueError("减面燃烧要求 m_dot_final <= m_dot_initial")

    def _compute_burn_time(self) -> float:
        mean = 0.5 * (self.mass_flow_initial_kg_s + self.mass_flow_final_kg_s)
        return self.propellant_mass_kg / mean

    def _slope(self) -> float:
        return (
            self.mass_flow_initial_kg_s - self.mass_flow_final_kg_s
        ) / self.burn_time_s

    def mass_flow_rate(self, t_s: float) -> float:
        if t_s < 0.0:
            raise ValueError(f"时间必须非负, 收到 {t_s!r}")
        if t_s >= self.burn_time_s:
            return 0.0
        return self.mass_flow_initial_kg_s - self._slope() * t_s

    def propellant_consumed(self, t_s: float) -> float:
        if t_s < 0.0:
            raise ValueError(f"时间必须非负, 收到 {t_s!r}")
        t = min(t_s, self.burn_time_s)
        return self.mass_flow_initial_kg_s * t - 0.5 * self._slope() * t * t


class TwoLevelBurnRate(BurnRateBase):
    """助推-续航: 前 t_boost_s 以 m_dot_high 燃烧, 之后转 m_dot_low."""

    def __init__(
        self,
        propellant_mass_kg: float,
        mass_flow_high_kg_s: float,
        mass_flow_low_kg_s: float,
        boost_time_s: float,
    ) -> None:
        self.mass_flow_high_kg_s = mass_flow_high_kg_s
        self.mass_flow_low_kg_s = mass_flow_low_kg_s
        self.boost_time_s = boost_time_s
        super().__init__(propellant_mass_kg)

    def _validate_shape(self) -> None:
        for name, value in (
            ("mass_flow_high_kg_s", self.mass_flow_high_kg_s),
            ("mass_flow_low_kg_s", self.mass_flow_low_kg_s),
            ("boost_time_s", self.boost_time_s),
        ):
            if not isinstance(value, (int, float)) or not math.isfinite(value):
                raise TypeError(f"{name} 必须为数值")
            if value <= 0.0:
                raise ValueError(f"{name} 必须为正数, 收到 {value!r}")
        if self.mass_flow_low_kg_s > self.mass_flow_high_kg_s:
            raise ValueError("助推段流量须不低于续航段流量")
        if self.mass_flow_high_kg_s * self.boost_time_s >= self.propellant_mass_kg:
            raise ValueError("助推段消耗已超过推进剂总质量")

    def _compute_burn_time(self) -> float:
        remaining = self.propellant_mass_kg - (
            self.mass_flow_high_kg_s * self.boost_time_s
        )
        return self.boost_time_s + remaining / self.mass_flow_low_kg_s

    def mass_flow_rate(self, t_s: float) -> float:
        if t_s < 0.0:
            raise ValueError(f"时间必须非负, 收到 {t_s!r}")
        if t_s >= self.burn_time_s:
            return 0.0
        if t_s < self.boost_time_s:
            return self.mass_flow_high_kg_s
        return self.mass_flow_low_kg_s

    def propellant_consumed(self, t_s: float) -> float:
        if t_s < 0.0:
            raise ValueError(f"时间必须非负, 收到 {t_s!r}")
        t = min(t_s, self.burn_time_s)
        if t <= self.boost_time_s:
            return self.mass_flow_high_kg_s * t
        return self.mass_flow_high_kg_s * self.boost_time_s + self.mass_flow_low_kg_s * (
            t - self.boost_time_s
        )


@dataclass
class Motor:
    """固体发动机装配: 燃烧率形状 + 比冲背压模型 + 质量预算.

    参数:
        dry_mass_kg: 不含推进剂的结构质量 (含喷管/壳体/舵面等).
        propellant_mass_kg: 推进剂质量.
        isp_sea_level_s / isp_vacuum_s: 比冲锚点.
        burn_rate: 燃烧率形状对象.
    """

    dry_mass_kg: float
    propellant_mass_kg: float
    isp_sea_level_s: float
    isp_vacuum_s: float
    burn_rate: BurnRateBase

    def __post_init__(self) -> None:
        for name, value in (
            ("dry_mass_kg", self.dry_mass_kg),
            ("propellant_mass_kg", self.propellant_mass_kg),
            ("isp_sea_level_s", self.isp_sea_level_s),
            ("isp_vacuum_s", self.isp_vacuum_s),
        ):
            if not isinstance(value, (int, float)) or not math.isfinite(value):
                raise TypeError(f"{name} 必须为有限数值")
            if value <= 0.0:
                raise ValueError(f"{name} 必须为正数, 收到 {value!r}")
        if self.propellant_mass_kg != self.burn_rate.propellant_mass_kg:
            raise ValueError("propellant_mass_kg 与 burn_rate 不一致")
        if self.isp_vacuum_s <= self.isp_sea_level_s:
            raise ValueError("比冲须满足 Isp_vac > Isp_SL")
        self.initial_mass_kg = self.dry_mass_kg + self.propellant_mass_kg

    def mass(self, t_s: float) -> float:
        """t 时刻弹体总质量 (kg), 燃烧结束后为干重."""
        return self.dry_mass_kg + self.burn_rate.propellant_mass_kg - (
            self.burn_rate.propellant_consumed(t_s)
        )

    def thrust(self, t_s: float, ambient_pressure_pa: float) -> float:
        """t 时刻推力 (N), 环境压强 p_a 决定比冲."""
        if t_s < 0.0:
            raise ValueError(f"时间必须非负, 收到 {t_s!r}")
        if t_s >= self.burn_rate.burn_time_s:
            return 0.0
        isp = specific_impulse_at_pressure(
            self.isp_sea_level_s, self.isp_vacuum_s, ambient_pressure_pa
        )
        return (
            self.burn_rate.mass_flow_rate(t_s) * STANDARD_GRAVITY_M_S2 * isp
        )


__all__ = [
    "BurnRateBase",
    "ConstantBurnRate",
    "Motor",
    "RegressiveLinearBurnRate",
    "TwoLevelBurnRate",
    "specific_impulse_at_pressure",
]
