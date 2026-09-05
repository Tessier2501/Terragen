"""M3: 设计参数族求值与寻优驱动 (DE 全局 + SLSQP 精修 + 约束升级).

设计变量 (方案 B, 用户拍板):
- 推力曲线 = 方向可逆两段级: (T/W0, r, tau)
  * T/W0: 起步段推重比 (按起飞总质量定义; 地射下限 1.5 保证离地);
  * r = m_dot_1 / m_dot_2 (r>1 先高后低, r=1 恒面, r<1 先低后高);
  * tau: 第一段消耗的推进剂质量占比;
- 程序角: GLBM (垂直保持时间 + 下压率), ALBM (拉起目标角).

流程:
1. DE 全局搜索 (约束: v_impact >= Vmin, 及越限后追加的物理约束);
2. SLSQP 从 DE 最优可行点精修;
3. 高精度重放 + 约束裕度表; 越限项转为硬约束重跑 (先监测再纳入).

所有评估样本 (参数 + 指标) 被记录, 供前端图与报告使用.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable

import numpy as np
from scipy.optimize import NonlinearConstraint, differential_evolution, minimize  # type: ignore[import-untyped]

from .aerodynamics import AerodynamicModel, BodyGeometry
from .atmosphere import AtmosphereUSSA76
from .constants import EARTH_MU_SI, EARTH_RADIUS_TRAJ_M, STANDARD_GRAVITY_M_S2
from .flight import FlightResult, ScheduleLike, simulate_powered_flight
from .propulsion import Motor, TwoSegmentBurnRate
from .steering import ClimbSchedule, PitchOverSchedule
from .vehicle import Missile

# --- 共享占位弹体与环境 (与 PLAN 基线一致) ---

_DRY_MASS_KG: float = 1500.0
_PROP_MASS_KG: float = 3500.0
_ISP_SL: float = 245.0
_ISP_VAC: float = 285.0
_GEOMETRY = BodyGeometry(diameter_m=0.9, nose_length_m=3.6, body_length_m=3.4)
_AERO = AerodynamicModel(_GEOMETRY)
_ATMOSPHERE = AtmosphereUSSA76(max_altitude_m=1_000_000.0)
_RE = EARTH_RADIUS_TRAJ_M
_G0 = STANDARD_GRAVITY_M_S2

_SEARCH_RTOL: float = 1e-7
_SEARCH_ATOL: float = 1e-7

# 可升级为硬约束的监测项: 名称 -> (指标提取, 阈值).
_EXTRA_LIMITS: dict[str, tuple[Callable[[FlightMetrics], float], float]] = {}


@dataclass(frozen=True)
class FlightMetrics:
    """单次弹道评估的全部输出指标."""

    success: bool
    impact_speed_m_s: float
    range_m: float
    flight_time_s: float
    burnout_speed_m_s: float
    burnout_altitude_m: float
    apogee_altitude_m: float
    max_mach: float
    boost_max_q_pa: float
    reentry_max_q_pa: float
    max_axial_g: float
    max_normal_g: float
    steer_saturation_fraction: float

    @property
    def range_km(self) -> float:
        return self.range_m / 1.0e3

    def vmin_violation(self, vmin_m_s: float) -> float:
        """约束余量: >= 0 表示满足 v_impact >= vmin."""
        return self.impact_speed_m_s - vmin_m_s if self.success else -1.0e9


@dataclass(frozen=True)
class Margin:
    """一项监测约束的实测值/阈值/名称."""

    name: str
    value: float
    limit: float

    @property
    def violated(self) -> bool:
        return self.value > self.limit


# GLBM 参数: (T/W0, r, tau, 垂直保持 s, 下压率 deg/s).
GLB_NAMES: tuple[str, ...] = ("T/W0", "r", "tau", "t_hold_s", "omega_deg_s")
GLB_BOUNDS: tuple[tuple[float, float], ...] = (
    (1.5, 8.0),
    (0.3, 3.0),
    (0.05, 0.95),
    (0.0, 6.0),
    (0.2, 8.0),
)
GLB_X0: np.ndarray = np.array([4.0, 1.0, 0.5, 2.0, 3.0])

# ALBM 参数: (T/W0, r, tau, 拉起目标角 deg).
ALB_NAMES: tuple[str, ...] = ("T/W0", "r", "tau", "climb_deg")
ALB_BOUNDS: tuple[tuple[float, float], ...] = (
    (1.0, 8.0),
    (0.3, 3.0),
    (0.05, 0.95),
    (8.0, 80.0),
)
ALB_X0: np.ndarray = np.array([4.0, 1.0, 0.5, 45.0])


@dataclass(frozen=True)
class PlatformSpec:
    """平台参数布局与设计装配规则."""

    name: str
    param_names: tuple[str, ...]
    bounds: tuple[tuple[float, float], ...]
    x0: np.ndarray
    build: Callable[[np.ndarray], tuple[Missile, ScheduleLike]]


def _make_missile(name: str, m_dot_first: float, m_dot_second: float, tau: float) -> Missile:
    burn = TwoSegmentBurnRate(
        propellant_mass_kg=_PROP_MASS_KG,
        mass_flow_first_kg_s=m_dot_first,
        mass_flow_second_kg_s=m_dot_second,
        first_segment_mass_kg=tau * _PROP_MASS_KG,
    )
    motor = Motor(
        dry_mass_kg=_DRY_MASS_KG,
        propellant_mass_kg=_PROP_MASS_KG,
        isp_sea_level_s=_ISP_SL,
        isp_vacuum_s=_ISP_VAC,
        burn_rate=burn,
    )
    return Missile(name=name, motor=motor, geometry=_GEOMETRY, aero_model=_AERO)


def _shape_mass_flows(tw0: float, ratio: float) -> tuple[float, float]:
    """由 (T/W0, r) 解两段流量: T/W0 = m_dot_1 * Isp_SL / m0."""
    m0 = _DRY_MASS_KG + _PROP_MASS_KG
    m_dot_first = tw0 * m0 / _ISP_SL
    return m_dot_first, m_dot_first / ratio


def _build_glb(x: np.ndarray) -> tuple[Missile, PitchOverSchedule]:
    tw0, ratio, tau, hold_s, omega_deg = (float(v) for v in x)
    m1, m2 = _shape_mass_flows(tw0, ratio)
    return _make_missile("GLBM", m1, m2, tau), PitchOverSchedule(
        hold_time_s=hold_s, turn_rate_rad_s=math.radians(omega_deg)
    )


def _build_alb(x: np.ndarray) -> tuple[Missile, ClimbSchedule]:
    tw0, ratio, tau, climb_deg = (float(v) for v in x)
    m1, m2 = _shape_mass_flows(tw0, ratio)
    return _make_missile("ALBM", m1, m2, tau), ClimbSchedule(
        target_angle_rad=math.radians(climb_deg)
    )


def make_platform_spec(name: str) -> PlatformSpec:
    """返回 GLBM / ALBM 的平台规格."""
    if name == "GLBM":
        return PlatformSpec(
            name="GLBM",
            param_names=GLB_NAMES,
            bounds=GLB_BOUNDS,
            x0=GLB_X0,
            build=_build_glb,  # type: ignore[arg-type]
        )
    if name == "ALBM":
        return PlatformSpec(
            name="ALBM",
            param_names=ALB_NAMES,
            bounds=ALB_BOUNDS,
            x0=ALB_X0,
            build=_build_alb,  # type: ignore[arg-type]
        )
    raise ValueError(f"未知平台: {name!r}, 仅支持 GLBM/ALBM")


def _initial_state(
    spec: PlatformSpec, atmosphere: AtmosphereUSSA76
) -> tuple[float, float, float]:
    """起飞状态: GLBM 地面垂直小初速; ALBM 10 km / Mach 0.85 水平."""
    if spec.name == "GLBM":
        return _RE, 10.0, math.pi / 2.0
    v0 = 0.85 * atmosphere.sample(10_000.0).speed_of_sound_m_s
    return _RE + 10_000.0, v0, 0.0


def compute_metrics(
    result: FlightResult, missile: Missile, schedule: ScheduleLike
) -> FlightMetrics:
    """从积分结果重算输出指标 (含约束裕度相关量)."""
    if not result.success:
        return FlightMetrics(
            success=False, impact_speed_m_s=0.0, range_m=0.0, flight_time_s=0.0,
            burnout_speed_m_s=0.0, burnout_altitude_m=0.0, apogee_altitude_m=0.0,
            max_mach=0.0, boost_max_q_pa=0.0, reentry_max_q_pa=0.0,
            max_axial_g=0.0, max_normal_g=0.0, steer_saturation_fraction=0.0,
        )
    burn_time = missile.motor.burn_rate.burn_time_s
    times = result.times
    states = result.states
    r = states[:, 0]
    alt = r - _RE
    v = states[:, 2]
    gamma = states[:, 3]
    m = states[:, 4]
    impact_rec = result.events["impact"]
    apogee_rec = result.events.get("apogee")
    burnout_rec = result.events.get("burnout")
    t_apogee = apogee_rec.time_s if apogee_rec is not None else math.inf

    mach = np.empty_like(v)
    q = np.empty_like(v)
    p_amb = np.empty_like(v)
    rho_arr = np.empty_like(v)
    temp_arr = np.empty_like(v)
    for i, a in enumerate(alt):
        st = _ATMOSPHERE.sample(max(float(a), 0.0))
        rho_arr[i] = st.density_kg_m3
        temp_arr[i] = st.temperature_k
        p_amb[i] = st.pressure_pa
        mach[i] = v[i] / st.speed_of_sound_m_s
        q[i] = 0.5 * st.density_kg_m3 * v[i] * v[i]

    thrust_arr = np.zeros_like(v)
    drag_arr = np.zeros_like(v)
    saturated = np.zeros(len(times), dtype=bool)
    normal_g = np.zeros_like(v)
    for i in range(len(times)):
        t_i = float(times[i])
        thrust_arr[i] = missile.motor.thrust(t_i, float(p_amb[i]))
        cd = missile.aero_model.cd_zero_lift(
            float(mach[i]), float(rho_arr[i]), float(v[i]), float(temp_arr[i])
        )
        drag_arr[i] = (
            0.5 * float(rho_arr[i]) * v[i] * v[i]
            * missile.geometry.reference_area_m2
            * cd
        )
        if thrust_arr[i] > 0.0:
            phi = schedule.angle(t_i, float(gamma[i]))
            cmd = missile.steering_authority.command(
                phi,
                float(gamma[i]),
                thrust_arr[i],
                m[i],
                float(q[i]),
                missile.geometry.reference_area_m2,
            )
            saturated[i] = cmd.saturated
            normal_g[i] = abs(cmd.normal_accel_m_s2) / _G0

    axial_accel_g = np.abs(thrust_arr - drag_arr) / m / _G0
    boost_mask = times <= burn_time
    reentry_mask = (times >= t_apogee) & (alt <= 80_000.0)
    # 转向饱和时间占比 (助推段按时间加权).
    dt_arr = np.zeros(len(times))
    dt_arr[:-1] = np.diff(times)
    powered_total = float(np.sum(dt_arr[boost_mask]))
    sat_fraction = (
        float(np.sum(dt_arr[boost_mask & saturated])) / powered_total
        if powered_total > 0.0
        else 0.0
    )
    impact_state = impact_rec.state
    return FlightMetrics(
        success=True,
        impact_speed_m_s=float(impact_state[2]),
        range_m=(float(impact_state[1]) - float(states[0, 1])) * _RE,
        flight_time_s=float(impact_rec.time_s),
        burnout_speed_m_s=float(burnout_rec.state[2]) if burnout_rec else 0.0,
        burnout_altitude_m=float(burnout_rec.state[0]) - _RE if burnout_rec else 0.0,
        apogee_altitude_m=float(apogee_rec.state[0]) - _RE if apogee_rec else 0.0,
        max_mach=float(np.max(mach)),
        boost_max_q_pa=float(np.max(q[boost_mask])),
        reentry_max_q_pa=float(np.max(q[reentry_mask])) if np.any(reentry_mask) else 0.0,
        max_axial_g=float(np.max(axial_accel_g)),
        max_normal_g=float(np.max(normal_g[boost_mask & (thrust_arr > 0.0)])),
        steer_saturation_fraction=sat_fraction,
    )


_eval_cache: dict[tuple[str, tuple[float, ...]], FlightMetrics] = {}


def evaluate_design(
    spec: PlatformSpec,
    x: np.ndarray,
    *,
    rtol: float = _SEARCH_RTOL,
    atol: float = _SEARCH_ATOL,
    use_cache: bool = True,
) -> FlightMetrics:
    """评估一组设计参数 -> 完整弹道指标 (积分失败返回 success=False)."""
    x_arr = np.asarray(x, dtype=float)
    if x_arr.shape != (len(spec.param_names),):
        raise ValueError(
            f"参数个数错误: 期望 {len(spec.param_names)}, 收到 {x_arr.shape[0]}"
        )
    cache_key = (spec.name, tuple(float(v) for v in x_arr))
    if use_cache and cache_key in _eval_cache:
        return _eval_cache[cache_key]
    missile, schedule = spec.build(x_arr)
    r0, v0, gamma0 = _initial_state(spec, _ATMOSPHERE)
    try:
        result = simulate_powered_flight(
            missile,
            _ATMOSPHERE,
            schedule,
            r0_m=r0,
            v0_m_s=v0,
            gamma0_rad=gamma0,
            t_max_s=3600.0,
            rtol=rtol,
            atol=atol,
        )
        metrics = compute_metrics(result, missile, schedule)
    except (RuntimeError, ValueError, FloatingPointError, ZeroDivisionError):
        metrics = compute_metrics_from_failure()
    if use_cache:
        _eval_cache[cache_key] = metrics
    return metrics


def compute_metrics_from_failure() -> FlightMetrics:
    """积分失败时的占位指标 (不可行设计)."""
    return FlightMetrics(
        success=False, impact_speed_m_s=0.0, range_m=0.0, flight_time_s=0.0,
        burnout_speed_m_s=0.0, burnout_altitude_m=0.0, apogee_altitude_m=0.0,
        max_mach=0.0, boost_max_q_pa=0.0, reentry_max_q_pa=0.0,
        max_axial_g=0.0, max_normal_g=0.0, steer_saturation_fraction=0.0,
    )


@dataclass
class OptimizationResult:
    """一次平台优化的完整输出 (含全部评估样本, 供前端图/报告)."""

    spec: PlatformSpec
    best_x: np.ndarray
    best_metrics: FlightMetrics
    success: bool
    attempts: int
    vmin_m_s: float
    seed: int
    message: str
    evaluations: list[tuple[tuple[float, ...], FlightMetrics]] = field(default_factory=list)
    margins: list[Margin] = field(default_factory=list)
    extra_constraints_used: list[str] = field(default_factory=list)




def _grid_seed_search(
    spec: PlatformSpec,
    objective: Callable[[np.ndarray], float],
    history: list[tuple[tuple[float, ...], FlightMetrics]],
) -> None:
    """DE 未发现可行点时的确定性粗网格兜底 (每维 3 水平, 共 3^d 次评估)."""
    from itertools import product

    levels = [np.linspace(lo, hi, 3) for lo, hi in spec.bounds]
    for combo in product(*levels):
        objective(np.asarray(combo, dtype=float))
    _ = history


def _default_margins(metrics: FlightMetrics) -> list[Margin]:
    """监测阈值 (占位, 可调; PLAN 3.6)."""
    return [
        Margin(name="boost Max-Q", value=metrics.boost_max_q_pa, limit=250_000.0),
        Margin(name="reentry Max-Q", value=metrics.reentry_max_q_pa, limit=2_500_000.0),
        Margin(name="axial accel", value=metrics.max_axial_g, limit=25.0),
        Margin(name="turn normal g", value=metrics.max_normal_g, limit=8.0),
        Margin(name="steering saturation frac", value=metrics.steer_saturation_fraction, limit=0.15),
    ]


def _get_margin_value(metrics: FlightMetrics, key: str) -> float:
    return {
        "boost_max_q_pa": metrics.boost_max_q_pa,
        "reentry_max_q_pa": metrics.reentry_max_q_pa,
        "max_axial_g": metrics.max_axial_g,
    }[key]


def optimize_platform(
    spec_name: str,
    *,
    vmin_m_s: float = 700.0,
    seed: int = 20250905,
    popsize: int = 12,
    maxiter: int = 25,
    max_attempts: int = 2,
) -> OptimizationResult:
    """寻优主入口: 先只带 Vmin, 越限项转硬约束重跑 (至多 max_attempts 轮)."""
    spec = make_platform_spec(spec_name)
    history: list[tuple[tuple[float, ...], FlightMetrics]] = []
    active_extra: list[str] = []
    margins: list[Margin] = []
    best_x = spec.x0.copy()
    attempts = 0

    for attempt in range(max_attempts):
        attempts += 1

        def objective(x: np.ndarray) -> float:
            metrics = evaluate_design(spec, x)
            history.append((tuple(float(v) for v in x), metrics))
            return -metrics.range_m if metrics.success else 1.0e9

        def vmin_fun(x: np.ndarray) -> float:
            return evaluate_design(spec, x).vmin_violation(vmin_m_s)

        cons: list[NonlinearConstraint] = [
            NonlinearConstraint(vmin_fun, lb=0.0, ub=np.inf)
        ]
        for key in active_extra:
            limit = _EXTRA_LIMITS[key][1]

            def extra_fun(x: np.ndarray, key: str = key, limit: float = limit) -> float:
                return limit - _get_margin_value(evaluate_design(spec, x), key)

            cons.append(NonlinearConstraint(extra_fun, lb=0.0, ub=np.inf))

        de_result = differential_evolution(
            objective,
            bounds=list(spec.bounds),
            constraints=cons,
            seed=seed + attempt,
            popsize=popsize,
            maxiter=maxiter,
            polish=False,
            updating="immediate",
            init="sobol",
            tol=1e-8,
        )
        if not any(
            m.success and m.vmin_violation(vmin_m_s) >= 0.0
            for _, m in history
        ):
            _grid_seed_search(spec, objective, history)
        feasible = [
            (np.asarray(x), m)
            for x, m in history
            if m.success and m.vmin_violation(vmin_m_s) >= 0.0
        ]
        if feasible:
            best_x = max(feasible, key=lambda pair: pair[1].range_m)[0]
        else:
            best_x = np.asarray(de_result.x)

        if feasible:
            def polish_obj(x: np.ndarray) -> float:
                return -evaluate_design(spec, x).range_m

            def vmin_ineq(x: np.ndarray) -> float:
                return evaluate_design(spec, x).vmin_violation(vmin_m_s)

            ineq: list[dict[str, object]] = [{"type": "ineq", "fun": vmin_ineq}]
            for key in active_extra:
                limit = _EXTRA_LIMITS[key][1]

                def extra_ineq(x: np.ndarray, key: str = key, limit: float = limit) -> float:
                    return limit - _get_margin_value(evaluate_design(spec, x), key)

                ineq.append({"type": "ineq", "fun": extra_ineq})
            polish = minimize(
                polish_obj,
                best_x,
                method="SLSQP",
                bounds=list(spec.bounds),
                constraints=ineq,
                options={"ftol": 1e-9, "maxiter": 80},
            )
            if polish.success:
                candidate = polish.x
                m_best = evaluate_design(spec, best_x)
                m_cand = evaluate_design(spec, candidate)
                if m_cand.success and m_cand.range_m > m_best.range_m:
                    best_x = candidate

        best_metrics = evaluate_design(
            spec, best_x, rtol=1e-10, atol=1e-10, use_cache=False
        )
        margins = _default_margins(best_metrics)
        margin_key_map = {
            "boost Max-Q": "boost_max_q_pa",
            "reentry Max-Q": "reentry_max_q_pa",
            "axial accel": "max_axial_g",
            "turn normal g": "max_normal_g",
        }
        new_keys = [
            margin_key_map[m.name]
            for m in margins
            if m.violated and m.name in margin_key_map
        ]
        if not new_keys:
            break
        active_extra = sorted(set(active_extra + new_keys))

    ok = best_metrics.success and best_metrics.vmin_violation(vmin_m_s) >= 0.0
    message = (
        "满足 Vmin 与全部启用约束"
        if ok
        else "无可行解: 约束组合过苛 (报告应显式说明)"
    )
    return OptimizationResult(
        spec=spec,
        best_x=best_x,
        best_metrics=best_metrics,
        success=ok,
        attempts=attempts,
        vmin_m_s=vmin_m_s,
        seed=seed,
        message=message,
        evaluations=history,
        margins=margins,
        extra_constraints_used=active_extra,
    )


def clear_cache() -> None:
    """清空设计评估缓存 (改变模型/参数后调用)."""
    _eval_cache.clear()


# 可升级为硬约束的监测项 (模块尾部填充, 避免前向引用问题).
_EXTRA_LIMITS.update(
    {
        "boost_max_q_pa": (lambda m: m.boost_max_q_pa, 250_000.0),
        "reentry_max_q_pa": (lambda m: m.reentry_max_q_pa, 2_500_000.0),
        "max_axial_g": (lambda m: m.max_axial_g, 25.0),
        "max_normal_g": (lambda m: m.max_normal_g, 8.0),
    }
)

__all__ = [
    "ALB_BOUNDS",
    "ALB_NAMES",
    "ALB_X0",
    "FlightMetrics",
    "GLB_BOUNDS",
    "GLB_NAMES",
    "GLB_X0",
    "Margin",
    "OptimizationResult",
    "PlatformSpec",
    "clear_cache",
    "compute_metrics",
    "evaluate_design",
    "make_platform_spec",
    "optimize_platform",
]
