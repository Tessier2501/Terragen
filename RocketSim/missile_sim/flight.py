"""2D 球面自由飞行积分与事件 (M1 核心).

状态向量 y = (r, theta, v, gamma):
- r: 地心距 (m)
- theta: 射程弧角 (rad), 从发射点起算
- v: 速度 (m/s)
- gamma: 航迹角 (rad), 当地水平面上方为正

弹道段无推力无阻力, 仅球面重力 (mu / r^2). 本模块保留事件与分段
续积骨架, M2 将注入推力/阻力/质量项而骨架不变.

已知边界: gamma 导数含 1/v 因子, 且 r 导数依赖 sin(gamma); 静止
垂直起竖 (v=0) 属奇异初值, M1 禁止, M2 需闭式短步启动或专用分支.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable

import numpy as np
from scipy.integrate import solve_ivp  # type: ignore[import-untyped]

from .atmosphere import AtmosphereUSSA76
from .constants import EARTH_MU_SI, EARTH_RADIUS_TRAJ_M
from .steering import ClimbSchedule, PitchOverSchedule
from .vehicle import Missile

# 状态向量分量索引.
IDX_R: int = 0
IDX_THETA: int = 1
IDX_V: int = 2
IDX_GAMMA: int = 3

_STATE_SIZE: int = 4


def free_flight_rhs(t: float, y: np.ndarray, mu: float = EARTH_MU_SI) -> np.ndarray:
    """自由飞行 (无推力无阻力) 运动方程右端, 球面极坐标.

    参数 t 未参与计算: 右端显式不含时间.
    """
    r = float(y[IDX_R])
    v = float(y[IDX_V])
    gamma = float(y[IDX_GAMMA])
    if v <= 0.0:
        raise ValueError(f"速度非正 (v={v:.6g} m/s), 方程奇异")
    sin_g = math.sin(gamma)
    cos_g = math.cos(gamma)
    g_acc = mu / (r * r)
    return np.array(
        [
            v * sin_g,
            v * cos_g / r,
            -g_acc * sin_g,
            (v / r - g_acc / v) * cos_g,
        ]
    )


@dataclass(frozen=True)
class EventSpec:
    """事件定义: 名称, 过零判定函数, 触发方向.

    direction: -1 表示由正转负的下降沿触发, +1 表示上升沿触发.
    """

    name: str
    func: Callable[[float, np.ndarray], float]
    direction: int


def apogee_event_spec() -> EventSpec:
    """远地点事件: 径向速度 v*sin(gamma) 由正转负."""

    def func(t: float, y: np.ndarray) -> float:
        return float(y[IDX_V]) * math.sin(float(y[IDX_GAMMA]))

    return EventSpec(name="apogee", func=func, direction=-1)


def impact_event_spec(r_target_m: float = EARTH_RADIUS_TRAJ_M) -> EventSpec:
    """命中事件: 地心距由大于 r_target 方向穿越 r_target (下降沿)."""
    if not isinstance(r_target_m, (int, float)) or not math.isfinite(r_target_m):
        raise ValueError("r_target_m 必须为有限数值")
    if r_target_m <= 0.0:
        raise ValueError(f"r_target_m 必须为正数, 收到 {r_target_m!r}")

    def func(t: float, y: np.ndarray) -> float:
        return float(y[IDX_R]) - r_target_m

    return EventSpec(name="impact", func=func, direction=-1)


class _ScipyEvent:
    """把 EventSpec 包装成 scipy 事件回调 (带 terminal/direction 属性)."""

    def __init__(self, spec: EventSpec) -> None:
        if spec.direction not in (-1, 1):
            raise ValueError(f"事件方向必须为 -1 或 1, 收到 {spec.direction!r}")
        self._spec = spec
        self.terminal = True
        self.direction = spec.direction

    def __call__(self, t: float, y: np.ndarray) -> float:
        return self._spec.func(t, y)


@dataclass(frozen=True)
class EventRecord:
    """已触发事件的记录."""

    name: str
    time_s: float
    state: np.ndarray  # 事件时刻的状态 (长度 _STATE_SIZE)


@dataclass
class FlightResult:
    """一次完整飞行积分的结果."""

    times: np.ndarray         # 形状 (N,)
    states: np.ndarray        # 形状 (N, 4)
    events: dict[str, EventRecord]
    success: bool             # 是否命中目标半径
    message: str


def simulate_free_flight(
    r0_m: float,
    v0_m_s: float,
    gamma0_rad: float,
    theta0_rad: float = 0.0,
    *,
    mu: float = EARTH_MU_SI,
    r_target_m: float = EARTH_RADIUS_TRAJ_M,
    t_max_s: float = 7200.0,
    rtol: float = 1e-9,
    atol: float = 1e-9,
) -> FlightResult:
    """积分一条完整自由飞行弹道, 依次处理远地点与命中事件.

    事件顺序: 上升段触发远地点后续积下降段, 直至命中 r_target 或
    到达 t_max. 若逃逸/环绕 (无事件), 到 t_max 自然结束并给出说明.

    异常:
        TypeError: 参数类型错误.
        ValueError: 初值或积分参数非法 (含描述信息).
        RuntimeError: 积分器内部失败.
    """
    params = {
        "r0_m": (r0_m, lambda x: x > r_target_m, "须大于 r_target_m"),
        "v0_m_s": (v0_m_s, lambda x: x > 0.0, "须为正数"),
        "mu": (mu, lambda x: x > 0.0, "须为正数"),
        "r_target_m": (r_target_m, lambda x: x > 0.0, "须为正数"),
        "t_max_s": (t_max_s, lambda x: x > 0.0, "须为正数"),
        "rtol": (rtol, lambda x: x > 0.0, "须为正数"),
        "atol": (atol, lambda x: x > 0.0, "须为正数"),
    }
    for name, (value, ok, why) in params.items():
        if not isinstance(value, (int, float)) or not math.isfinite(value):
            raise TypeError(f"{name} 必须为有限数值")
        if not ok(value):
            raise ValueError(f"{name}={value!r} {why}")
    if not isinstance(gamma0_rad, (int, float)) or not math.isfinite(gamma0_rad):
        raise TypeError("gamma0_rad 必须为有限数值")
    if gamma0_rad <= 0.0 or gamma0_rad >= math.pi / 2.0:
        raise ValueError("gamma0_rad 必须在 (0, pi/2) 开区间 (M1 限制)")
    if not isinstance(theta0_rad, (int, float)) or not math.isfinite(theta0_rad):
        raise TypeError("theta0_rad 必须为有限数值")

    y_now = np.array(
        [float(r0_m), float(theta0_rad), float(v0_m_s), float(gamma0_rad)]
    )
    pending: list[EventSpec] = [apogee_event_spec(), impact_event_spec(r_target_m)]
    seg_times: list[np.ndarray] = []
    seg_states: list[np.ndarray] = []
    events_found: dict[str, EventRecord] = {}
    t_now = 0.0

    def rhs(t: float, y: np.ndarray) -> np.ndarray:
        return free_flight_rhs(t, y, mu)

    while pending and t_now < t_max_s:
        scipy_events = [_ScipyEvent(spec) for spec in pending]
        sol = solve_ivp(
            rhs,
            (t_now, t_max_s),
            y_now,
            events=scipy_events,
            method="RK45",
            rtol=rtol,
            atol=atol,
        )
        if not sol.success:
            raise RuntimeError(f"积分器失败: {sol.message}")
        seg_t = np.asarray(sol.t)
        seg_y = np.asarray(sol.y).T
        if seg_times:
            seg_times.append(seg_t[1:])
            seg_states.append(seg_y[1:])
        else:
            seg_times.append(seg_t)
            seg_states.append(seg_y)
        fired_idx = next(
            (i for i, te in enumerate(sol.t_events) if te.size > 0), None
        )
        if fired_idx is None:
            break
        spec = pending[fired_idx]
        t_ev = float(sol.t_events[fired_idx][0])
        state_ev = np.asarray(sol.y_events[fired_idx][0], dtype=float)
        events_found[spec.name] = EventRecord(name=spec.name, time_s=t_ev, state=state_ev)
        if spec.name == "impact":
            break
        pending = [s for i, s in enumerate(pending) if i != fired_idx]
        t_now = t_ev
        y_now = state_ev

    if "impact" in events_found:
        message = "命中目标半径"
    elif "apogee" in events_found:
        message = "到达远地点后未命中 (t_max 内)"
    else:
        message = "t_max 内无事件触发 (可能逃逸或环绕)"
    return FlightResult(
        times=np.concatenate(seg_times),
        states=np.concatenate(seg_states, axis=0),
        events=events_found,
        success="impact" in events_found,
        message=message,
    )


def impact_ground_range_m(
    result: FlightResult, r_target_m: float = EARTH_RADIUS_TRAJ_M
) -> float:
    """命中点相对发射点沿地表的大圆弧距离 (m).

    异常:
        ValueError: 结果无命中事件.
    """
    if "impact" not in result.events:
        raise ValueError("结果无命中事件, 无法计算射程")
    rec = result.events["impact"]
    theta0 = float(result.states[0, IDX_THETA])
    return (float(rec.state[IDX_THETA]) - theta0) * r_target_m


# --- 动力飞行 (M2): 状态 (r, theta, v, gamma, m), m 为弹体总质量. ---

IDX_MASS: int = 4

ScheduleLike = ClimbSchedule | PitchOverSchedule


def _powered_rhs(
    t: float,
    y: np.ndarray,
    missile: Missile,
    atmosphere: AtmosphereUSSA76,
    schedule: ScheduleLike,
    mu: float,
    enable_thrust: bool,
) -> np.ndarray:
    """动力段右端: 球面重力 + 推力 (方向角 phi) + 大气阻力 + 质量流失."""
    r = float(y[IDX_R])
    v = float(y[IDX_V])
    gamma = float(y[IDX_GAMMA])
    m = float(y[IDX_MASS])
    if v <= 0.0:
        raise ValueError(f"速度非正 (v={v:.6g} m/s), 方程奇异")
    sin_g = math.sin(gamma)
    cos_g = math.cos(gamma)
    # 命中事件所在步的 RK 内部节点可能瞬时低于地表: 采样高度钳到 >= 0
    # (大气特性按海平面近似), 事件根仍精确定位于 r = R_e, 影响仅末半步.
    atmo = atmosphere.sample(max(r - EARTH_RADIUS_TRAJ_M, 0.0))
    if enable_thrust:
        thrust = missile.motor.thrust(t, atmo.pressure_pa)
        m_dot = missile.motor.burn_rate.mass_flow_rate(t)
    else:
        thrust = 0.0
        m_dot = 0.0
    mach = v / atmo.speed_of_sound_m_s
    cd = missile.aero_model.cd_zero_lift(
        mach, atmo.density_kg_m3, v, atmo.temperature_k
    )
    drag = (
        0.5
        * atmo.density_kg_m3
        * v
        * v
        * missile.geometry.reference_area_m2
        * cd
    )
    phi = schedule.angle(t, gamma)
    g_acc = mu / (r * r)
    thrust_axial = thrust * math.cos(phi - gamma) / m
    thrust_normal = thrust * math.sin(phi - gamma) / m
    return np.array(
        [
            v * sin_g,
            v * cos_g / r,
            thrust_axial - drag / m - g_acc * sin_g,
            thrust_normal / v + (v / r - g_acc / v) * cos_g,
            -m_dot,
        ]
    )


def burnout_time_event_spec(burn_time_s: float) -> EventSpec:
    """关机事件: 以燃烧时间 t 触发 (推进剂闭合后精确已知).

    比质量-干重判据更稳健: 质量在关机后保持不变, 不会产生符号翻转.
    """
    if not isinstance(burn_time_s, (int, float)) or not math.isfinite(burn_time_s):
        raise TypeError("burn_time_s 必须为有限数值")
    if burn_time_s <= 0.0:
        raise ValueError(f"burn_time_s 必须为正数, 收到 {burn_time_s!r}")

    def func(t: float, y: np.ndarray) -> float:
        return t - burn_time_s

    return EventSpec(name="burnout", func=func, direction=1)


def simulate_powered_flight(
    missile: Missile,
    atmosphere: AtmosphereUSSA76,
    schedule: ScheduleLike,
    *,
    r0_m: float,
    v0_m_s: float,
    gamma0_rad: float,
    theta0_rad: float = 0.0,
    mu: float = EARTH_MU_SI,
    r_target_m: float = EARTH_RADIUS_TRAJ_M,
    t_max_s: float = 3600.0,
    rtol: float = 1e-9,
    atol: float = 1e-9,
    enable_thrust: bool = True,
) -> FlightResult:
    """积分一条完整动力弹道: 助推 -> 关机 -> 远地点 -> 命中.

    事件顺序不限, 每段取最先触发的终止事件并续积 (关机 / 远地点 /
    命中). 事件后各物理量自动连续: 关机后推力与质量流失为零.

    异常:
        TypeError: 参数类型错误.
        ValueError: 初值或积分参数非法 (含描述信息).
        RuntimeError: 积分器内部失败.
    """
    params = {
        "r0_m": (r0_m, lambda x: x >= r_target_m, "须 >= r_target_m"),
        "v0_m_s": (v0_m_s, lambda x: x > 0.0, "须为正数"),
        "mu": (mu, lambda x: x > 0.0, "须为正数"),
        "r_target_m": (r_target_m, lambda x: x > 0.0, "须为正数"),
        "t_max_s": (t_max_s, lambda x: x > 0.0, "须为正数"),
        "rtol": (rtol, lambda x: x > 0.0, "须为正数"),
        "atol": (atol, lambda x: x > 0.0, "须为正数"),
    }
    for name, (value, ok, why) in params.items():
        if not isinstance(value, (int, float)) or not math.isfinite(value):
            raise TypeError(f"{name} 必须为有限数值")
        if not ok(value):
            raise ValueError(f"{name}={value!r} {why}")
    if not isinstance(gamma0_rad, (int, float)) or not math.isfinite(gamma0_rad):
        raise TypeError("gamma0_rad 必须为有限数值")
    if gamma0_rad < 0.0 or gamma0_rad > math.pi / 2.0:
        raise ValueError("gamma0_rad 必须在 [0, pi/2] 内 (含水平与垂直)")
    if not isinstance(theta0_rad, (int, float)) or not math.isfinite(theta0_rad):
        raise TypeError("theta0_rad 必须为有限数值")
    if not isinstance(enable_thrust, bool):
        raise TypeError("enable_thrust 必须为 bool")
    if not isinstance(missile, Missile):
        raise TypeError("missile 必须为 Missile")
    if not isinstance(atmosphere, AtmosphereUSSA76):
        raise TypeError("atmosphere 必须为 AtmosphereUSSA76")

    m0 = missile.motor.mass(0.0)
    y_now = np.array(
        [
            float(r0_m),
            float(theta0_rad),
            float(v0_m_s),
            float(gamma0_rad),
            float(m0),
        ]
    )
    pending: list[EventSpec] = [apogee_event_spec(), impact_event_spec(r_target_m)]
    if enable_thrust:
        pending.append(burnout_time_event_spec(missile.motor.burn_rate.burn_time_s))
    seg_times: list[np.ndarray] = []
    seg_states: list[np.ndarray] = []
    events_found: dict[str, EventRecord] = {}
    t_now = 0.0

    def rhs(t: float, y: np.ndarray) -> np.ndarray:
        return _powered_rhs(t, y, missile, atmosphere, schedule, mu, enable_thrust)

    while pending and t_now < t_max_s:
        scipy_events = [_ScipyEvent(spec) for spec in pending]
        sol = solve_ivp(
            rhs,
            (t_now, t_max_s),
            y_now,
            events=scipy_events,
            method="RK45",
            rtol=rtol,
            atol=atol,
        )
        if not sol.success:
            raise RuntimeError(f"积分器失败: {sol.message}")
        seg_t = np.asarray(sol.t)
        seg_y = np.asarray(sol.y).T
        if seg_times:
            seg_times.append(seg_t[1:])
            seg_states.append(seg_y[1:])
        else:
            seg_times.append(seg_t)
            seg_states.append(seg_y)
        fired_idx = next(
            (i for i, te in enumerate(sol.t_events) if te.size > 0), None
        )
        if fired_idx is None:
            break
        spec = pending[fired_idx]
        t_ev = float(sol.t_events[fired_idx][0])
        state_ev = np.asarray(sol.y_events[fired_idx][0], dtype=float)
        events_found[spec.name] = EventRecord(name=spec.name, time_s=t_ev, state=state_ev)
        if spec.name == "impact":
            break
        pending = [s for i, s in enumerate(pending) if i != fired_idx]
        t_now = t_ev
        y_now = state_ev

    if "impact" in events_found:
        message = "命中目标半径"
    elif "apogee" in events_found:
        message = "到达远地点后未命中 (t_max 内)"
    else:
        message = "t_max 内无事件触发 (可能逃逸或环绕)"
    return FlightResult(
        times=np.concatenate(seg_times),
        states=np.concatenate(seg_states, axis=0),
        events=events_found,
        success="impact" in events_found,
        message=message,
    )


__all__ = [
    "EventRecord",
    "EventSpec",
    "FlightResult",
    "apogee_event_spec",
    "burnout_time_event_spec",
    "free_flight_rhs",
    "impact_event_spec",
    "impact_ground_range_m",
    "simulate_free_flight",
    "simulate_powered_flight",
]
