"""M4 报告生成: 前端图/弹道对比图/校验附录图 + Markdown 报告.

运行: python -m missile_sim.report (生成到 RocketSim/output/).
图内文字用 ASCII (避开 matplotlib 中文字体问题), 报告正文为中文.
"""

from __future__ import annotations

import math
from pathlib import Path

import matplotlib  # type: ignore[import-untyped]

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # type: ignore[import-untyped]
import numpy as np

from .aerodynamics import AerodynamicModel, BodyGeometry
from .atmosphere import AtmosphereUSSA76
from .constants import EARTH_RADIUS_TRAJ_M
from .flight import FlightResult
from .optimize import OptimizationResult, replay_design
from .scenario import ScenarioOutcome, run_scenario

_RE = EARTH_RADIUS_TRAJ_M


def _alt_km(result: FlightResult) -> np.ndarray:
    return (result.states[:, 0] - _RE) / 1.0e3


def _range_km(result: FlightResult) -> np.ndarray:
    return (result.states[:, 1] - result.states[0, 1]) * _RE / 1.0e3


def _event_xy(result: FlightResult, name: str) -> tuple[float, float]:
    state = result.events[name].state
    return ((state[1] - result.states[0, 1]) * _RE / 1.0e3, (state[0] - _RE) / 1.0e3)


def _front_points(res: OptimizationResult, cap: int = 4000) -> np.ndarray:
    pts = np.array(
        [(m.range_km, m.impact_speed_m_s) for _, m in res.evaluations if m.success]
    )
    if pts.size == 0:
        return np.empty((0, 2))
    stride = max(1, int(math.ceil(len(pts) / cap)))
    return pts[::stride]


def _upper_frontier(pts: np.ndarray) -> np.ndarray:
    """按射程升序保留当前最大命中速度, 得射程-末速上包络."""
    if pts.size == 0:
        return pts
    order = np.argsort(pts[:, 0])
    xs, ys, best = [], [], -1.0
    for i in order:
        if pts[i, 1] > best:
            best = float(pts[i, 1])
            xs.append(float(pts[i, 0]))
            ys.append(best)
    return np.column_stack([np.asarray(xs), np.asarray(ys)])


def plot_front(alb: OptimizationResult, glb: OptimizationResult, vmin: float, path: Path) -> None:
    fig, ax = plt.subplots(figsize=(9, 6))
    for res, color, label in ((alb, "#1f77b4", "ALBM samples"), (glb, "#d62728", "GLBM samples")):
        pts = _front_points(res)
        if pts.size:
            ax.scatter(pts[:, 0], pts[:, 1], s=3, alpha=0.35, color=color, label=label)
            front = _upper_frontier(pts)
            ax.plot(front[:, 0], front[:, 1], color=color, lw=1.6,
                    label=f"{label} upper frontier")
        ax.scatter([res.best_metrics.range_km], [res.best_metrics.impact_speed_m_s],
                   marker="*", s=220, color=color, edgecolor="k", zorder=5)
    ax.axhline(vmin, color="k", ls="--", lw=1.2, label=f"Vmin = {vmin:.0f} m/s")
    ax.set_xlabel("Range (km)")
    ax.set_ylabel("Impact speed (m/s)")
    ax.set_title("Range-impact-speed frontier (all evaluated designs)")
    ax.legend(fontsize=8, loc="lower right")
    ax.set_xlim(0, None)
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)


def plot_trajectories(
    res_alb: OptimizationResult,
    res_glb: OptimizationResult,
    res_glb_alb: OptimizationResult | None,
    path: Path,
) -> None:
    fig, ax = plt.subplots(figsize=(9, 6))
    cases: list[tuple[str, OptimizationResult, str]] = [
        ("ALBM optimum", res_alb, "#1f77b4"),
        ("GLBM optimum", res_glb, "#d62728"),
    ]
    if res_glb_alb is not None and res_glb_alb.success:
        cases.append(("GLBM w/ ALBM curve", res_glb_alb, "#7f7f7f"))
    for label, res, color in cases:
        flight = replay_design(res.spec, res.best_x)
        ax.plot(_range_km(flight), _alt_km(flight), color=color, lw=1.8, label=label)
        for name, marker in (("burnout", "o"), ("apogee", "^"), ("impact", "s")):
            if name in flight.events:
                x, y = _event_xy(flight, name)
                ax.plot([x], [y], marker=marker, color=color, mec="k", ms=8, zorder=6)
    ax.set_xlabel("Ground range (km)")
    ax.set_ylabel("Altitude (km)")
    ax.set_title("Optimal trajectories (markers: burnout/apogee/impact)")
    ax.legend(fontsize=9)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)


def _mach_q(result: FlightResult) -> tuple[np.ndarray, np.ndarray]:
    atmo = AtmosphereUSSA76(max_altitude_m=1_000_000.0)
    alt = _alt_km(result) * 1.0e3
    v = result.states[:, 2]
    mach = np.empty_like(v)
    q = np.empty_like(v)
    for i, a in enumerate(alt):
        st = atmo.sample(max(float(a), 0.0))
        mach[i] = v[i] / st.speed_of_sound_m_s
        q[i] = 0.5 * st.density_kg_m3 * v[i] * v[i]
    return mach, q


def plot_appendix(
    res_alb: OptimizationResult, res_glb: OptimizationResult, path: Path
) -> None:
    fig, axes = plt.subplots(2, 2, figsize=(11, 8))
    atmo = AtmosphereUSSA76(max_altitude_m=1_000_000.0)
    for res, color, name in ((res_alb, "#1f77b4", "ALBM"), (res_glb, "#d62728", "GLBM")):
        flight = replay_design(res.spec, res.best_x)
        mach, q = _mach_q(flight)
        axes[0, 0].plot(flight.times, mach, color=color, lw=1.2, label=name)
        axes[0, 1].plot(flight.times, q / 1.0e3, color=color, lw=1.2, label=name)
    axes[0, 0].set_xlabel("t (s)")
    axes[0, 0].set_ylabel("Mach")
    axes[0, 0].set_title("Mach vs time")
    axes[0, 0].legend()
    axes[0, 1].set_xlabel("t (s)")
    axes[0, 1].set_ylabel("q (kPa)")
    axes[0, 1].set_title("Dynamic pressure vs time")
    axes[0, 1].legend()

    geo = BodyGeometry(diameter_m=0.9, nose_length_m=3.6, body_length_m=3.4)
    aero = AerodynamicModel(geo)
    ms = np.linspace(0.1, 8.0, 200)
    cds = [aero.cd_zero_lift(m, 1.225, m * 340.294, 288.15) for m in ms]
    axes[1, 0].plot(ms, cds, color="k", lw=1.5)
    axes[1, 0].set_xlabel("Mach")
    axes[1, 0].set_ylabel("Cd")
    axes[1, 0].set_title("Zero-lift Cd(Mach) (semi-empirical)")

    hs = np.linspace(0.0, 100.0, 201) * 1.0e3
    rhos = [atmo.sample(float(h)).density_kg_m3 for h in hs]
    axes[1, 1].plot(np.asarray(rhos), hs / 1.0e3, color="k", lw=1.5)
    axes[1, 1].set_xscale("log")
    axes[1, 1].set_xlabel("Density (kg/m^3)")
    axes[1, 1].set_ylabel("Altitude (km)")
    axes[1, 1].set_title("USSA76 density profile")
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)


def _fmt_metric(res: OptimizationResult) -> dict[str, float]:
    m = res.best_metrics
    return {
        "range_km": m.range_km,
        "v_imp": m.impact_speed_m_s,
        "t_flight": m.flight_time_s,
        "v_bo": m.burnout_speed_m_s,
        "h_bo": m.burnout_altitude_m / 1.0e3,
        "h_ap": m.apogee_altitude_m / 1.0e3,
    }


def _event_table(res: OptimizationResult) -> str:
    flight = replay_design(res.spec, res.best_x)
    rows = []
    for name in ("burnout", "apogee", "impact"):
        if name not in flight.events:
            continue
        ev = flight.events[name]
        s = ev.state
        h = (s[0] - _RE) / 1.0e3
        gamma = math.degrees(s[3])
        rows.append(
            f"| {name} | {ev.time_s:.1f} | {h:.1f} | {s[2]:.0f} | {gamma:.1f} |"
        )
    header = "| 事件 | t (s) | 高度 (km) | 速度 (m/s) | 航迹角 (deg) |\n|---|---|---|---|---|\n"
    note = ""
    if "impact" in flight.events:
        rng = (flight.events["impact"].state[1] - flight.states[0, 1]) * _RE / 1.0e3
        note = f"\n地表射程: {rng:.1f} km\n"
    return header + "\n".join(rows) + "\n" + note


def _param_row(res: OptimizationResult) -> str:
    cells = " / ".join(f"{n}={v:.3f}" for n, v in zip(res.spec.param_names, res.best_x))
    return f"| {res.spec.name} | {cells} |"


def _margin_rows(res: OptimizationResult) -> str:
    out = []
    for m in res.margins:
        mark = "越限" if m.violated else "OK"
        out.append(f"| {m.name} | {m.value:.4g} | {m.limit:.4g} | {mark} |")
    return "\n".join(out)


def _rotation_appendix() -> str:
    return (
        "地球自转影响估算 (未建模, 2D 平面限制):\n"
        "- 2D 模型仅在发射面为东/西向大圆时能严格计入自转, 本项目默认关闭自转;\n"
        "- 量级估算: 横向/沿程偏差 ~ Omega * v * T^2 量级, Omega=7.29e-5 rad/s,\n"
        "  v~2-3 km/s, 飞行时间 T~400-600 s, 偏差可达数十 km (纬度/方位相关);\n"
        "- 对数百公里级射程约为百分之几的相对误差, 不改变本文空射/地射对比的结论方向.\n"
    )


def generate_report(
    out_dir: Path,
    *,
    seed: int = 20250905,
    popsize: int = 12,
    maxiter: int = 25,
    vmin_m_s: float = 700.0,
) -> Path:
    """运行场景并生成全部图与 Markdown 报告, 返回报告路径."""
    out_dir.mkdir(parents=True, exist_ok=True)
    sc = run_scenario(seed=seed, popsize=popsize, maxiter=maxiter, vmin_m_s=vmin_m_s)
    plot_front(sc.alb, sc.glb, vmin_m_s, out_dir / "fig_front.png")
    plot_trajectories(sc.alb, sc.glb, sc.glb_with_alb_curve, out_dir / "fig_trajectories.png")
    plot_appendix(sc.alb, sc.glb, out_dir / "fig_appendix.png")

    m_alb = _fmt_metric(sc.alb)
    m_glb = _fmt_metric(sc.glb)
    m_ga = _fmt_metric(sc.glb_with_alb_curve)
    m_ag = _fmt_metric(sc.alb_with_glb_curve)
    g_total = m_alb["range_km"] - m_glb["range_km"]
    g_curve = m_ga["range_km"] - m_glb["range_km"]
    g_platform = m_alb["range_km"] - m_ga["range_km"]

    lines: list[str] = []
    lines.append("# 空射 vs 地射弹道导弹: 最大有效射程对比报告 (M4)\n")
    lines.append(f"> 生成: 种子 {seed}, 占位弹体参数, Vmin = {vmin_m_s:.0f} m/s. 所有数值可复现.\n")
    lines.append("## 1. 结论摘要\n")
    lines.append(
        f"- ALBM (10 km/Mach 0.85 投放) 最大有效射程 **{m_alb['range_km']:.0f} km**, "
        f"命中速度 {m_alb['v_imp']:.0f} m/s;\n"
        f"- GLBM (垂直起飞) 最大有效射程 **{m_glb['range_km']:.0f} km**, "
        f"命中速度 {m_glb['v_imp']:.0f} m/s;\n"
        f"- 空射增益 **{g_total:+.0f} km ({g_total / m_glb['range_km'] * 100:+.0f}%)**;\n"
        f"- 分解: 同为空射最优推力曲线口径下, 平台发射条件贡献 "
        f"{g_platform:+.0f} km; 曲线设计贡献 (地射视角, 换用空射最优曲线) "
        f"{g_curve:+.0f} km;\n"
        f"- 生存性解读: 若目标位于地射阵地最大射程处 ({m_glb['range_km']:.0f} km), "
        f"载机可在距目标最远 {m_alb['range_km']:.0f} km 处发射, 即载机相对地射阵地 "
        f"可后撤 {g_total:.0f} km (增益 {g_total / m_glb['range_km'] * 100:.0f}%).\n"
    )
    lines.append("## 2. 最优设计\n")
    lines.append("| 平台 | 参数 (T/W0 / r / tau / 程序角) |\n|---|---|\n")
    lines.append(_param_row(sc.alb) + "\n")
    lines.append(_param_row(sc.glb) + "\n")
    lines.append("## 3. 事件表 (最优解高精度重放)\n")
    lines.append("### ALBM\n" + _event_table(sc.alb))
    lines.append("### GLBM\n" + _event_table(sc.glb))
    lines.append("### GLBM 采用 ALBM 最优曲线 (同曲线对照)\n" + _event_table(sc.glb_with_alb_curve))
    lines.append("## 4. 约束裕度表\n")
    lines.append("### ALBM\n| 项目 | 实测 | 阈值 | 状态 |\n|---|---|---|---|\n")
    lines.append(_margin_rows(sc.alb) + "\n")
    lines.append("### GLBM\n| 项目 | 实测 | 阈值 | 状态 |\n|---|---|---|---|\n")
    lines.append(_margin_rows(sc.glb) + "\n")
    lines.append("## 5. 图\n")
    lines.append("- ![front](fig_front.png)\n- ![trajectories](fig_trajectories.png)\n- ![appendix](fig_appendix.png)\n")
    lines.append("## 6. 对照实验汇总 (km)\n")
    lines.append(
        "| 场景 | 射程 | 命中速度 |\n|---|---|---|\n"
        f"| ALBM 全最优 | {m_alb['range_km']:.1f} | {m_alb['v_imp']:.0f} |\n"
        f"| GLBM 全最优 | {m_glb['range_km']:.1f} | {m_glb['v_imp']:.0f} |\n"
        f"| GLBM + ALBM 曲线 | {m_ga['range_km']:.1f} | {m_ga['v_imp']:.0f} |\n"
        f"| ALBM + GLBM 曲线 | {m_ag['range_km']:.1f} | {m_ag['v_imp']:.0f} |\n"
    )
    lines.append("## 7. 假设与误差附录\n")
    lines.append(_rotation_appendix())
    lines.append(
        "- 其他简化见 PLAN.md 3.7; Cd(M)/大气模型验证见 M1/M2 测试 "
        "(标准表误差 <0.1%, 开普勒对拍 ~1e-9).\n"
    )
    report_path = out_dir / "report.md"
    report_path.write_text("".join(lines), encoding="utf-8")
    return report_path


if __name__ == "__main__":
    out = Path(__file__).resolve().parents[1] / "output"
    print("生成报告:", generate_report(out))


def _plot_traj_series(
    ax,  # matplotlib Axes (库无类型存根, 隐式 Any)
    label: str,
    res: OptimizationResult,
    color: str,
    linestyle: str,
) -> None:
    """在 ax 上画一条最优弹道及事件标记."""
    flight = replay_design(res.spec, res.best_x)
    ax.plot(_range_km(flight), _alt_km(flight), color=color, lw=1.8,
            linestyle=linestyle, label=label)  # type: ignore[attr-defined]
    for name, marker in (("burnout", "o"), ("apogee", "^"), ("impact", "s")):
        if name in flight.events:
            x, y = _event_xy(flight, name)
            ax.plot([x], [y], marker=marker, color=color, mec="k", ms=8,
                    zorder=6)  # type: ignore[attr-defined]


def plot_trajectories_mixed(
    lift_alb: OptimizationResult,
    lift_glb: OptimizationResult,
    ball_alb: OptimizationResult,
    ball_glb: OptimizationResult,
    path: Path,
) -> None:
    """最终图: 升力滑翔 (实线) vs 纯弹道 (虚线) 最优弹道对比."""
    fig, ax = plt.subplots(figsize=(9, 6))  # type: ignore[attr-defined]
    _plot_traj_series(ax, "ALBM lift (v1)", lift_alb, "#1f77b4", "-")
    _plot_traj_series(ax, "GLBM lift (v1)", lift_glb, "#d62728", "-")
    _plot_traj_series(ax, "ALBM ballistic", ball_alb, "#7f7f7f", "--")
    _plot_traj_series(ax, "GLBM ballistic", ball_glb, "#bcbdc0", "--")
    ax.set_xlabel("Ground range (km)")  # type: ignore[attr-defined]
    ax.set_ylabel("Altitude (km)")  # type: ignore[attr-defined]
    ax.set_title("Optimal trajectories: lift-glide (v1) vs ballistic")  # type: ignore[attr-defined]
    ax.legend(fontsize=8)  # type: ignore[attr-defined]
    ax.grid(alpha=0.3)  # type: ignore[attr-defined]
    fig.tight_layout()  # type: ignore[attr-defined]
    fig.savefig(path, dpi=140)  # type: ignore[attr-defined]
    plt.close(fig)


def plot_front_mixed(
    lift_alb: OptimizationResult,
    lift_glb: OptimizationResult,
    ball_alb: OptimizationResult,
    ball_glb: OptimizationResult,
    vmin: float,
    path: Path,
) -> None:
    """最终图: 升力滑翔样本前端 + 两模式最优点 + Vmin 截线."""
    fig, ax = plt.subplots(figsize=(9, 6))  # type: ignore[attr-defined]
    for res, color, label in (
        (lift_alb, "#1f77b4", "ALBM lift samples"),
        (lift_glb, "#d62728", "GLBM lift samples"),
    ):
        pts = _front_points(res)
        if pts.size:
            ax.scatter(pts[:, 0], pts[:, 1], s=3, alpha=0.3, color=color, label=label)  # type: ignore[attr-defined]
    for res, color in ((ball_alb, "#1f77b4"), (ball_glb, "#d62728")):
        ax.scatter([res.best_metrics.range_km], [res.best_metrics.impact_speed_m_s],  # type: ignore[attr-defined]
                   marker="*", s=260, color=color, edgecolor="k", zorder=5)
    ax.axhline(vmin, color="k", ls="--", lw=1.2, label=f"Vmin = {vmin:.0f} m/s")  # type: ignore[attr-defined]
    ax.set_xlabel("Range (km)")  # type: ignore[attr-defined]
    ax.set_ylabel("Impact speed (m/s)")  # type: ignore[attr-defined]
    ax.set_title("Lift-glide (v1) samples vs ballistic optima (stars)")  # type: ignore[attr-defined]
    ax.legend(fontsize=8, loc="lower right")  # type: ignore[attr-defined]
    ax.set_xlim(0, None)  # type: ignore[attr-defined]
    fig.tight_layout()  # type: ignore[attr-defined]
    fig.savefig(path, dpi=140)  # type: ignore[attr-defined]
    plt.close(fig)


def generate_final_report(
    out_dir: Path,
    *,
    seed: int = 20250905,
    popsize: int = 12,
    maxiter: int = 25,
    vmin_m_s: float = 700.0,
) -> Path:
    """最终收尾报告: 纯弹道 vs 升力滑翔 (v1) 双场景 + 图 + Markdown."""
    out_dir.mkdir(parents=True, exist_ok=True)
    ball = run_scenario(seed=seed, popsize=popsize, maxiter=maxiter, vmin_m_s=vmin_m_s)
    lift = run_scenario(
        seed=seed, popsize=popsize, maxiter=maxiter, vmin_m_s=vmin_m_s,
        lift_guidance=True,
    )
    plot_front_mixed(lift.alb, lift.glb, ball.alb, ball.glb, vmin_m_s,
                     out_dir / "fig_front.png")
    plot_trajectories_mixed(lift.alb, lift.glb, ball.alb, ball.glb,
                            out_dir / "fig_trajectories.png")
    plot_appendix(lift.alb, lift.glb, out_dir / "fig_appendix.png")

    mb = _fmt_metric(ball.alb)
    mg = _fmt_metric(ball.glb)
    lines: list[str] = []
    lines.append("# 空射 vs 地射: 升力滑翔 (v1) 最终报告\n")
    lines.append(f"> Vmin={vmin_m_s:.0f}, 种子 {seed}; 滑翔制导 = 分段法向过载指令 (v1).\n")
    lines.append("## 1. 结论摘要\n")
    lines.append(
        f"- 纯弹道: ALBM {mb['range_km']:.0f} km / {mb['v_imp']:.0f} m/s; "
        f"GLBM {mg['range_km']:.0f} km / {mg['v_imp']:.0f} m/s;\n"
        f"- 升力滑翔 v1: ALBM {lift.alb.best_metrics.range_km:.0f} km / "
        f"{lift.alb.best_metrics.impact_speed_m_s:.0f} m/s; GLBM "
        f"{lift.glb.best_metrics.range_km:.0f} km / "
        f"{lift.glb.best_metrics.impact_speed_m_s:.0f} m/s;\n"
        f"- 升力把高末速兑换为射程: ALB 命中速度压至贴 Vmin, 但射程增益 "
        f"仅约 +1% (细长体 L/D 限制, 详见 PLAN 11b).\n"
    )
    lines.append("## 2. 最优设计参数\n| 平台/模式 | 参数 |\n|---|---|\n")
    lines.append(_param_row(lift.alb) + "\n")
    lines.append(_param_row(lift.glb) + "\n")
    lines.append("## 3. 事件表 (升力滑翔最优, 高精度重放)\n")
    lines.append("### ALBM (lift)\n" + _event_table(lift.alb))
    lines.append("### GLBM (lift)\n" + _event_table(lift.glb))
    lines.append("## 4. 约束裕度 (升力滑翔最优)\n")
    lines.append("### ALBM\n| 项目 | 实测 | 阈值 | 状态 |\n|---|---|---|---|\n" + _margin_rows(lift.alb) + "\n")
    lines.append("### GLBM\n| 项目 | 实测 | 阈值 | 状态 |\n|---|---|---|---|\n" + _margin_rows(lift.glb) + "\n")
    lines.append("## 5. 图\n- ![front](fig_front.png)\n- ![trajectories](fig_trajectories.png)\n- ![appendix](fig_appendix.png)\n")
    lines.append("## 6. 手动复现\n")
    lines.append(
        f"`python -m missile_sim.cli --scenario final --vmin {vmin_m_s:.0f} "
        f"--seed {seed} --popsize {popsize} --maxiter {maxiter}`\n"
    )
    report_path = out_dir / "report.md"
    report_path.write_text("".join(lines), encoding="utf-8")
    return report_path
