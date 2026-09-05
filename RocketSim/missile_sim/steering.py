"""转向架构: TVC/气动舵指令分配与助推程序角族 (M2, M3 强化).

物理要点 (PLAN 3.5):
- 气动舵/弹体法向力 N = q * S * C_N_alpha * alpha, q = 0.5*rho*v^2;
  发射瞬间 v=0 -> q=0, 高空低密度 q 亦趋零, 舵效随高度/速度退化;
- 指令分配 (M3): TVC 摆角优先 (任何高度/动压可用), 攻角补足 (舵
  法向力依赖 q), 超出总能力即饱和; 轨迹按饱和后的实际法向加速度
  积分, 不产生虚构过载;
- 弹道方程以"期望推力方向角 phi"为控制, 经本模块分配为物理可实现
  的 (delta, alpha) 与实际法向加速度.

助推程序角族:
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
    """程序角基类: angle(t, gamma) -> 期望推力方向角 phi (当地水平上方)."""

    def angle(self, t_s: float, gamma_rad: float) -> float:
        """返回 t 时刻, 当前航迹角 gamma 下的期望推力方向角 (rad)."""
        raise NotImplementedError

    def _validate_time_gamma(self, t_s: float, gamma_rad: float) -> None:
        if not isinstance(t_s, (int, float)) or not math.isfinite(t_s) or t_s < 0.0:
            raise ValueError(f"t_s 必须为非负有限值, 收到 {t_s!r}")
        if not isinstance(gamma_rad, (int, float)) or not math.isfinite(gamma_rad):
            raise ValueError(f"gamma_rad 必须为有限值, 收到 {gamma_rad!r}")


class PitchOverSchedule(_ScheduleBase):
    """垂直起飞后程序下压: 保持垂直 t_hold_s, 之后以 turn_rate 下压.

    程序角 program(t) = pi/2 - turn_rate * max(0, t - t_hold), 期望
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
    """空射平飞拉起: 期望推力方向固定在 target 角直到航迹角追上.

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
class PiecewiseNormalGuidance:
    """关机后法向过载分段指令 (g, 向上为正; 有升力滑翔扩展用).

    时间轴为"相对关机时刻": [0, t1) 段指令 n1_g, [t1, t1+dur_s) 段
    指令 n2_g, 之后回到 0 (纯弹道). 指令仅在动压 q >= q_min_pa 时
    生效 (舵面/升力面需要足够动压), 高空稀薄段自动退化为纯弹道.
    """

    n1_g: float
    t1_s: float
    n2_g: float
    dur_s: float
    q_min_pa: float = 2000.0
    accel_cap_g: float = 5.0

    def __post_init__(self) -> None:
        for name, value in (
            ("n1_g", self.n1_g),
            ("t1_s", self.t1_s),
            ("n2_g", self.n2_g),
            ("dur_s", self.dur_s),
            ("q_min_pa", self.q_min_pa),
            ("accel_cap_g", self.accel_cap_g),
        ):
            if not isinstance(value, (int, float)) or not math.isfinite(value):
                raise TypeError(f"{name} 必须为有限数值")
        if self.n1_g < 0.0 or self.n2_g < 0.0:
            raise ValueError("法向过载指令必须非负 (向上拉起)")
        if self.t1_s < 0.0 or self.dur_s < 0.0 or self.q_min_pa < 0.0:
            raise ValueError("时间与 q_min 必须非负")
        if self.accel_cap_g <= 0.0:
            raise ValueError("accel_cap_g 必须为正数")

    def load_factor_g(self, t_since_burnout_s: float) -> float:
        """相对关机时间对应的指令法向过载 (g)."""
        if t_since_burnout_s < 0.0:
            raise ValueError(f"t_since_burnout_s 必须非负, 收到 {t_since_burnout_s!r}")
        if t_since_burnout_s < self.t1_s:
            return self.n1_g
        if t_since_burnout_s < self.t1_s + self.dur_s:
            return self.n2_g
        return 0.0


@dataclass(frozen=True)
class NormalAccelBudget:
    """当前状态下可用的法向加速度分解."""

    tvc_m_s2: float   # 推力矢量贡献
    fins_m_s2: float  # 气动舵贡献 (q 依赖, 高空/低速趋零)


@dataclass(frozen=True)
class SteeringCommand:
    """一次转向指令的物理分配结果.

    分配顺序: TVC 摆角 -> 燃气舵 (同为推力偏转, 与高度无关) -> 攻角
    (气动舵, 依赖动压) -> 超出总能力即饱和.
    """

    delta_rad: float            # 推力偏转角合计 (摆角+燃气舵, 有符号)
    alpha_rad: float            # 攻角 (有符号, |alpha| <= alpha_max)
    normal_accel_m_s2: float    # 实际产生的法向加速度
    saturated: bool             # 指令超出总能力时为 True


class SteeringAuthority:
    """转向能力与指令分配.

    参数 (PLAN 基线, 占位可调):
        gimbal_max_rad: TVC 最大摆角 (默认 12 度).
        jet_vane_max_rad: 燃气舵额外偏转能力 (默认 10 度; 喷流舵,
            低动压/高空仍有效, 受材料与烧蚀限制见监测约束).
        fin_lift_slope_1_rad: 舵面法向力斜率 C_N_alpha (默认 8 /rad).
        alpha_max_rad: 最大攻角 (默认 8 度).
    """

    def __init__(
        self,
        gimbal_max_rad: float = math.radians(12.0),
        jet_vane_max_rad: float = math.radians(10.0),
        fin_lift_slope_1_rad: float = 8.0,
        alpha_max_rad: float = math.radians(8.0),
    ) -> None:
        params = {
            "gimbal_max_rad": gimbal_max_rad,
            "jet_vane_max_rad": jet_vane_max_rad,
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
        self.jet_vane_max_rad = float(jet_vane_max_rad)
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
        tvc = (thrust_n / mass_kg) * math.sin(
            self.gimbal_max_rad + self.jet_vane_max_rad
        )
        fins = (
            dynamic_pressure_pa
            * reference_area_m2
            * self.fin_lift_slope_1_rad
            * self.alpha_max_rad
        ) / mass_kg
        return NormalAccelBudget(tvc_m_s2=tvc, fins_m_s2=fins)

    def command(
        self,
        phi_desired_rad: float,
        gamma_rad: float,
        thrust_n: float,
        mass_kg: float,
        dynamic_pressure_pa: float,
        reference_area_m2: float,
    ) -> SteeringCommand:
        """把期望推力方向角转为物理可实现指令 (TVC+燃气舵 优先, 攻角补足).

        分配: 摆角先承担 (与高度/动压无关), 燃气舵接力 (喷流舵, 低动压
        仍有效), 攻角补足 (气动舵法向力依赖动压 q), 仍不足则饱和. 饱和
        时轨迹按实际产生的法向加速度继续, 不虚构过载.
        """
        for name, value in (
            ("phi_desired_rad", phi_desired_rad),
            ("gamma_rad", gamma_rad),
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
        delta_desired = float(phi_desired_rad) - float(gamma_rad)
        gimbal = max(
            -self.gimbal_max_rad, min(self.gimbal_max_rad, delta_desired)
        )
        remainder = delta_desired - gimbal
        vane = max(
            -self.jet_vane_max_rad, min(self.jet_vane_max_rad, remainder)
        )
        remainder2 = remainder - vane
        alpha = max(
            -self.alpha_max_rad, min(self.alpha_max_rad, remainder2)
        )
        saturated = abs(remainder2) > self.alpha_max_rad + 1e-12
        deflection = gimbal + vane
        a_n = (
            (thrust_n / mass_kg) * math.sin(deflection)
            + dynamic_pressure_pa
            * reference_area_m2
            * self.fin_lift_slope_1_rad
            * alpha
            / mass_kg
        )
        return SteeringCommand(
            delta_rad=deflection,
            alpha_rad=alpha,
            normal_accel_m_s2=a_n,
            saturated=saturated,
        )


__all__ = [
    "ClimbSchedule",
    "NormalAccelBudget",
    "PiecewiseNormalGuidance",
    "PitchOverSchedule",
    "SteeringAuthority",
    "SteeringCommand",
]
