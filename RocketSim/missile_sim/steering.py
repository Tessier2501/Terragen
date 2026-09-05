"""转向架构: TVC/气动舵法向过载预算与助推程序角族 (M2).

物理要点 (PLAN 3.5):
- 气动舵法向力 N = q * S * C_N_alpha * alpha, q = 0.5*rho*v^2;
  发射瞬间 v=0 -> q=0, 高空低密度 q 亦趋零, 舵效随高度/速度退化;
- 可用法向过载 = TVC 项 + 舵项; 分配策略: 优先舵, 不足由 TVC 补;
- 弹道方程以推力方向角 phi 为控制, 本模块只计算可用性与程序角,
  可行性判据在 M3 寻优时启用.

助推程序角族 (M2 基线, M3 会扩展参数化):
- PitchOverSchedule: 垂直发射用 - 垂直保持 t_hold 后以恒定角速度
  下压 (phi = min(gamma, program)), 转完后自然重力转弯;
- ClimbSchedule: 空射平飞拉起到目标航迹角 (phi = max(gamma, target)),
  到达后转重力转弯.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

_HALF_PI = math.pi / 2.0


class _ScheduleBase:
    """程序角基类: angle(t, gamma) -> 推力方向角 phi (当地水平上方)."""

    def angle(self, t_s: float, gamma_rad: float) -> float:
        """返回 t 时刻, 当前航迹角 gamma 下的推力方向角 (rad)."""
        raise NotImplementedError

    def _validate_time_gamma(self, t_s: float, gamma_rad: float) -> None:
        if not isinstance(t_s, (int, float)) or not math.isfinite(t_s) or t_s < 0.0:
            raise ValueError(f"t_s 必须为非负有限值, 收到 {t_s!r}")
        if not isinstance(gamma_rad, (int, float)) or not math.isfinite(gamma_rad):
            raise ValueError(f"gamma_rad 必须为有限值, 收到 {gamma_rad!r}")


class PitchOverSchedule(_ScheduleBase):
    """垂直起飞后程序下压: 保持垂直 t_hold_s, 之后以 turn_rate 下压.

    程序角 program(t) = pi/2 - turn_rate * max(0, t - t_hold), 实际
    推力方向角 phi = min(gamma, program): 程序低于航迹角时把速度矢量
    往下压, 程序高于航迹角时保持推力沿速度 (重力转弯).
    """

    def __init__(self, hold_time_s: float, turn_rate_rad_s: float) -> None:
        for name, value in (
            ("hold_time_s", hold_time_s),
            ("turn_rate_rad_s", turn_rate_rad_s),
        ):
            if not isinstance(value, (int, float)) or not math.isfinite(value):
                raise TypeError(f"{name} 必须为有限数值")
            if value < 0.0:
                raise ValueError(f"{name} 必须非负, 收到 {value!r}")
        self.hold_time_s = float(hold_time_s)
        self.turn_rate_rad_s = float(turn_rate_rad_s)

    def angle(self, t_s: float, gamma_rad: float) -> float:
        self._validate_time_gamma(t_s, gamma_rad)
        program = _HALF_PI - self.turn_rate_rad_s * max(0.0, t_s - self.hold_time_s)
        program = max(program, 0.0)
        return min(float(gamma_rad), program)


class ClimbSchedule(_ScheduleBase):
    """空射平飞拉起: 推力方向固定在 target 角直到航迹角追上, 随后重力转弯.

    phi = max(gamma, target): 从水平 (gamma~0) 拉到 target, 追上后
    推力沿速度方向 (不再主动改变航迹角).
    """

    def __init__(self, target_angle_rad: float) -> None:
        if not isinstance(target_angle_rad, (int, float)):
            raise TypeError("target_angle_rad 必须为数值")
        if not math.isfinite(target_angle_rad) or not (0.0 < target_angle_rad <= _HALF_PI):
            raise ValueError("target_angle_rad 必须在 (0, pi/2] 内")
        self.target_angle_rad = float(target_angle_rad)

    def angle(self, t_s: float, gamma_rad: float) -> float:
        self._validate_time_gamma(t_s, gamma_rad)
        return max(float(gamma_rad), self.target_angle_rad)


@dataclass(frozen=True)
class NormalAccelBudget:
    """当前状态下可用的法向加速度分解."""

    tvc_m_s2: float   # 推力矢量贡献
    fins_m_s2: float  # 气动舵贡献 (q 依赖, 高空/低速趋零)


class SteeringAuthority:
    """转向能力预算: 可用法向过载 = TVC + 舵 (q 依赖).

    参数 (PLAN 基线, 占位可调):
        gimbal_max_rad: TVC 最大摆角 (默认 7 度).
        fin_lift_slope_1_rad: 舵面法向力斜率 C_N_alpha (默认 3 /rad).
        alpha_max_rad: 最大攻角 (默认 8 度).
    """

    def __init__(
        self,
        gimbal_max_rad: float = math.radians(7.0),
        fin_lift_slope_1_rad: float = 3.0,
        alpha_max_rad: float = math.radians(8.0),
    ) -> None:
        params = {
            "gimbal_max_rad": gimbal_max_rad,
            "fin_lift_slope_1_rad": fin_lift_slope_1_rad,
            "alpha_max_rad": alpha_max_rad,
        }
        for name, value in params.items():
            if not isinstance(value, (int, float)) or not math.isfinite(value):
                raise TypeError(f"{name} 必须为有限数值")
            if value <= 0.0:
                raise ValueError(f"{name} 必须为正数, 收到 {value!r}")
        if alpha_max_rad >= _HALF_PI:
            raise ValueError("alpha_max_rad 必须小于 90 度")
        self.gimbal_max_rad = float(gimbal_max_rad)
        self.fin_lift_slope_1_rad = float(fin_lift_slope_1_rad)
        self.alpha_max_rad = float(alpha_max_rad)

    def available_normal_accel(
        self,
        thrust_n: float,
        mass_kg: float,
        dynamic_pressure_pa: float,
        reference_area_m2: float,
    ) -> NormalAccelBudget:
        """当前可用法向加速度 (m/s^2).

        TVC 项 = (T/m) * sin(delta_max), 与高度无关;
        舵项 = (q * S * C_N_alpha * alpha_max) / m, 随 q 退化.
        """
        for name, value in (
            ("thrust_n", thrust_n),
            ("mass_kg", mass_kg),
            ("dynamic_pressure_pa", dynamic_pressure_pa),
            ("reference_area_m2", reference_area_m2),
        ):
            if not isinstance(value, (int, float)) or not math.isfinite(value):
                raise TypeError(f"{name} 必须为有限数值")
        if mass_kg <= 0.0 or reference_area_m2 <= 0.0:
            raise ValueError("mass_kg 与 reference_area_m2 必须为正")
        if thrust_n < 0.0 or dynamic_pressure_pa < 0.0:
            raise ValueError("thrust_n 与 dynamic_pressure_pa 必须非负")
        tvc = (thrust_n / mass_kg) * math.sin(self.gimbal_max_rad)
        fins = (
            dynamic_pressure_pa
            * reference_area_m2
            * self.fin_lift_slope_1_rad
            * self.alpha_max_rad
        ) / mass_kg
        return NormalAccelBudget(tvc_m_s2=tvc, fins_m_s2=fins)


__all__ = [
    "ClimbSchedule",
    "NormalAccelBudget",
    "PitchOverSchedule",
    "SteeringAuthority",
]
