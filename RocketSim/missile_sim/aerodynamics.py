"""弹体几何与零升阻力系数 Cd(M, h, v) 半经验合成 (M2).

模型结构:
- 阻力 = 摩阻 (湍流平板, 按当地 Re 与温度) + 底阻 (常数占位) +
  波阻 (细长体理论, 马赫无关平台) x 跨声速过渡因子 f_tr(M).
- 波阻平台系数由弹体几何 (尖拱头部 + 圆柱段) 的面积分布二阶导数
  经 von Karman 细长体双积分得到 (纯几何, 无拟合参数).
- f_tr(M): 0.7 以下为零, M~1.05 过冲 (~1.35 倍平台), M>=1.6 回平台.

简化声明:
- 细长体理论在 M > ~1.3 且长细比 > ~5 时量级可信, 数值绝对值误差
  允许 ~30%; 本模块定位是量级正确 + 形状正确, 供 M3 寻优使用;
- 底阻取常数占位值 (真实底阻随马赫与底部流动状态变化);
- 转捩位置按全湍流处理; 粗糙度以乘子粗糙度因子统一吸收;
- 攻角效应 (诱导阻力) 由调用方按 alpha <= 8 度修正, 本模块只给零升阻力.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy.interpolate import PchipInterpolator  # type: ignore[import-untyped]

# 跨声速过渡因子控制点: (马赫数, 相对平台的乘子).
_TR_M_CTRL: tuple[float, ...] = (0.0, 0.7, 0.85, 0.95, 1.02, 1.05, 1.15, 1.35, 1.6, 3.0, 8.0)
_TR_F_CTRL: tuple[float, ...] = (0.0, 0.0, 0.08, 0.4, 0.95, 1.35, 1.15, 1.03, 1.0, 1.0, 1.0)
_TR_INTERP: PchipInterpolator = PchipInterpolator(_TR_M_CTRL, _TR_F_CTRL)

# Sutherland 黏度常数 (SI).
_MU0_SI: float = 1.716e-5
_T0_SUTHERLAND_K: float = 273.15
_SUTHERLAND_S_K: float = 110.4

_WAVE_GRID_N: int = 2048  # 波阻双积分网格数.


@dataclass
class BodyGeometry:
    """弹体几何 (回转体): 尖拱头部 + 等径圆柱段, 底部无收缩.

    参数:
        diameter_m: 弹径 (m).
        nose_length_m: 尖拱头部长度 (m).
        body_length_m: 圆柱段长度 (m).
    """

    diameter_m: float
    nose_length_m: float
    body_length_m: float

    def __post_init__(self) -> None:
        for name, value in (
            ("diameter_m", self.diameter_m),
            ("nose_length_m", self.nose_length_m),
            ("body_length_m", self.body_length_m),
        ):
            if not isinstance(value, (int, float)) or not math.isfinite(value):
                raise TypeError(f"{name} 必须为有限数值")
            if value <= 0.0:
                raise ValueError(f"{name} 必须为正数, 收到 {value!r}")
        self._radius_m = 0.5 * float(self.diameter_m)
        self._nose_rho_m = (
            self.nose_length_m**2 + self._radius_m**2
        ) / (2.0 * self._radius_m)
        self.total_length_m = float(self.nose_length_m) + float(self.body_length_m)
        self.reference_area_m2 = math.pi * self._radius_m**2
        # 几何积分: 超声速波阻平台系数与湿面积比 (相对参考面积).
        self._wave_grid = self._build_wave_grid()
        self.cd_wave_infinite, self.wet_to_ref_ratio = self._wave_grid

    @property
    def radius_m(self) -> float:
        """弹体半径 (m)."""
        return self._radius_m

    def _nose_radius(self, x_m: np.ndarray) -> np.ndarray:
        """尖拱半径分布 (x 自头部顶点起, 到鼻锥长度为止有效)."""
        u = x_m - self.nose_length_m
        r = np.sqrt(np.maximum(self._nose_rho_m**2 - u * u, 0.0))
        return r + self._radius_m - self._nose_rho_m

    def _radius_profile(self, x_m: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """整弹半径/一阶/二阶导数分布 (头部段解析, 圆柱段为零)."""
        nose_mask = x_m <= self.nose_length_m
        u = x_m - self.nose_length_m
        denom = np.sqrt(np.maximum(self._nose_rho_m**2 - u * u, 1e-300))
        r = np.where(nose_mask, self._nose_radius(x_m), self._radius_m)
        rp = np.where(nose_mask, -u / denom, 0.0)
        rpp = np.where(
            nose_mask, -self._nose_rho_m**2 / denom**3, 0.0
        )
        return r, rp, rpp

    def _build_wave_grid(self) -> tuple[float, float]:
        """细长体波阻双积分与湿面积比 (中点法, 每格一次积分)."""
        n = _WAVE_GRID_N
        length = self.total_length_m
        h = length / n
        x = (np.arange(n) + 0.5) * h  # 格心中点.
        r, rp, rpp = self._radius_profile(x)
        s_pp = 2.0 * math.pi * (rp * rp + r * rpp)  # 面积分布二阶导数.
        dx = np.abs(x[:, None] - x[None, :])
        np.fill_diagonal(dx, h)  # 对角奇异: 以 h 近似 (O(h) 误差, 量级足够).
        kernel = np.log(dx)
        wave_q = -(1.0 / math.pi) * h * h * float(
            np.sum(s_pp[:, None] * s_pp[None, :] * kernel)
        )
        cd_wave_inf = max(wave_q / self.reference_area_m2, 0.0)
        # 湿面积: 头部曲面 + 圆柱侧面积, 不含底面积.
        ds = h * np.sqrt(1.0 + rp * rp)
        wet_area = 2.0 * math.pi * float(np.sum(r * ds))
        wet_ratio = wet_area / self.reference_area_m2
        return cd_wave_inf, wet_ratio


class AerodynamicModel:
    """零升阻力模型 + 可选升力/诱导阻力 (PLAN 11b 扩展).

    Cd(M, rho, v, T) 含摩阻/底阻/波阻; 当 cl_alpha_1_rad > 0 时启用
    升力模型: CL = cl_alpha * alpha (alpha 限幅在 alpha_max_lift 内),
    诱导阻力 Cd_i = induced_drag_factor * CL^2 加入总阻力.
    """

    def __init__(
        self,
        geometry: BodyGeometry,
        base_drag_coeff: float = 0.10,
        roughness_factor: float = 1.0,
        cl_alpha_1_rad: float = 0.0,
        induced_drag_factor: float = 0.0,
        alpha_max_lift_rad: float = math.radians(10.0),
    ) -> None:
        """构造气动模型.

        参数:
            geometry: 弹体几何.
            base_drag_coeff: 底阻系数占位常数 (量级 0.05-0.15).
            roughness_factor: 粗糙度乘子 (1.0 = 光滑湍流平板).
            cl_alpha_1_rad: 升力线斜率 (1/rad); 0 = 关闭升力模型.
            induced_drag_factor: 诱导阻力因子 kappa (CD_i = kappa*CL^2).
            alpha_max_lift_rad: 可控攻角上限 (升力面/舵面).
        """
        for name, value in (
            ("base_drag_coeff", base_drag_coeff),
            ("roughness_factor", roughness_factor),
            ("cl_alpha_1_rad", cl_alpha_1_rad),
            ("induced_drag_factor", induced_drag_factor),
            ("alpha_max_lift_rad", alpha_max_lift_rad),
        ):
            if not isinstance(value, (int, float)) or not math.isfinite(value):
                raise TypeError(f"{name} 必须为有限数值")
            if value < 0.0:
                raise ValueError(f"{name} 必须非负, 收到 {value!r}")
        if alpha_max_lift_rad > math.pi / 3.0:
            raise ValueError("alpha_max_lift_rad 过大 (>60 度)")
        if not isinstance(geometry, BodyGeometry):
            raise TypeError("geometry 必须为 BodyGeometry")
        self.geometry = geometry
        self.base_drag_coeff = float(base_drag_coeff)
        self.roughness_factor = float(roughness_factor)
        self.cl_alpha_1_rad = float(cl_alpha_1_rad)
        self.induced_drag_factor = float(induced_drag_factor)
        self.alpha_max_lift_rad = float(alpha_max_lift_rad)

    @property
    def lift_enabled(self) -> bool:
        """是否启用升力模型."""
        return self.cl_alpha_1_rad > 0.0

    def lift_coefficient(self, alpha_rad: float) -> float:
        """攻角 alpha (已限幅) 对应的升力系数 CL = cl_alpha * alpha."""
        if not self.lift_enabled:
            raise ValueError("升力模型未启用 (cl_alpha_1_rad = 0)")
        return self.cl_alpha_1_rad * float(alpha_rad)

    def induced_drag_coefficient(self, cl: float) -> float:
        """升力系数 CL 对应的诱导阻力系数."""
        return self.induced_drag_factor * float(cl) * float(cl)

    @staticmethod
    def _transonic_factor(mach: float) -> float:
        """跨声速过渡乘子 (0 = 无波阻, 1 = 波阻平台)."""
        if mach <= _TR_M_CTRL[0]:
            return 0.0
        if mach >= _TR_M_CTRL[-1]:
            return float(_TR_F_CTRL[-1])
        return float(_TR_INTERP(mach))

    def cd_zero_lift(
        self,
        mach: float,
        density_kg_m3: float,
        velocity_m_s: float,
        temperature_k: float,
    ) -> float:
        """零升阻力系数 Cd.

        参数:
            mach: 马赫数 (>= 0).
            density_kg_m3: 当地大气密度 (kg/m^3).
            velocity_m_s: 空速 (m/s).
            temperature_k: 当地大气温度 (K).
        """
        for name, value in (
            ("mach", mach),
            ("density_kg_m3", density_kg_m3),
            ("velocity_m_s", velocity_m_s),
            ("temperature_k", temperature_k),
        ):
            if not isinstance(value, (int, float)) or not math.isfinite(value):
                raise TypeError(f"{name} 必须为有限数值")
        if mach < 0.0 or density_kg_m3 <= 0.0 or velocity_m_s <= 0.0 or temperature_k <= 0.0:
            raise ValueError("mach>=0, 密度/速度/温度必须为正")
        geom = self.geometry
        # 摩阻: 湍流平板公式 (Schlichting), 特征长度 = 弹体全长.
        mu = _MU0_SI * (temperature_k / _T0_SUTHERLAND_K) ** 1.5 * (
            _T0_SUTHERLAND_K + _SUTHERLAND_S_K
        ) / (temperature_k + _SUTHERLAND_S_K)
        re = density_kg_m3 * velocity_m_s * geom.total_length_m / mu
        if re <= 10.0:  # 极低雷诺数保护 (高空稀薄), 摩阻置零.
            cd_friction = 0.0
        else:
            cf_flat = 0.455 / (math.log10(re) ** 2.58)
            cd_friction = (
                self.roughness_factor * cf_flat * geom.wet_to_ref_ratio
            )
        cd_wave = geom.cd_wave_infinite * self._transonic_factor(mach)
        return cd_friction + self.base_drag_coeff + cd_wave


__all__ = ["AerodynamicModel", "BodyGeometry"]
