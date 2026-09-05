"""USSA76 标准大气模型 (0-86 km 分层公式, 之上等温延拓).

提供几何高度 -> 温度 / 压强 / 密度 / 音速. 用途:
- 阻力计算取密度;
- 喷管推力取环境压强;
- 马赫数取音速 (音速不可假设常数, 须随温度剖面变化).

简化声明:
- 0-84.852 km 位势高度内按 USSA76 分层公式计算 (位势高度定义,
  参考半径 6356.766 km; 84.852 km 位势高度对应 86 km 几何高度);
- 86 km 几何高度以上等温延拓 (T = 186.946 K): 该高度以上密度对
  轨迹作用力影响可忽略, 等温延拓仅保证数值连续有界;
- 不考虑纬度, 季节, 太阳活动, 湿度 (2D 仿真子集).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Final

# USSA76 位势参考半径 (m).
_GEO_REF_RADIUS_M: Final[float] = 6356.766e3
# 干空气比气体常数 (J / (kg * K)), 0-86 km 取 28.9644 g/mol 干空气.
_AIR_R_SPECIFIC: Final[float] = 287.052874
# 空气比热比 (理想气体常数).
_AIR_GAMMA: Final[float] = 1.4
# 标准重力加速度 (m / s^2).
_G0: Final[float] = 9.80665

# 位势分层表: (层底位势高度 m, 层底温度 K, 温度直减率 K / m).
# 末层延伸至 84852 m 位势高度 (对应 86000 m 几何高度).
_LAYERS_TABLE: Final[tuple[tuple[float, float, float], ...]] = (
    (0.0, 288.15, -0.0065),
    (11000.0, 216.65, 0.0),
    (20000.0, 216.65, 0.001),
    (32000.0, 228.65, 0.0028),
    (47000.0, 270.65, 0.0),
    (51000.0, 270.65, -0.0028),
    (71000.0, 214.65, -0.002),
)

# 等温段起点位势高度 (m), 即末层层顶.
_ISO_TOP_GEOPOTENTIAL_M: Final[float] = 84852.0
# 等温段温度 (K): 214.65 + (-0.002) * (84852 - 71000).
_T_ISO_K: Final[float] = 186.946
# 海平面标准压强 (Pa).
_SEA_LEVEL_PRESSURE_PA: Final[float] = 101325.0


def geometric_to_geopotential(altitude_m: float) -> float:
    """几何高度转位势高度 (m), 使用 USSA76 位势参考半径."""
    return altitude_m * _GEO_REF_RADIUS_M / (_GEO_REF_RADIUS_M + altitude_m)


def geopotential_to_geometric(geopotential_m: float) -> float:
    """位势高度转几何高度 (m), 使用 USSA76 位势参考半径."""
    return geopotential_m * _GEO_REF_RADIUS_M / (_GEO_REF_RADIUS_M - geopotential_m)


@dataclass(frozen=True)
class AtmoState:
    """单个几何高度上的大气状态量 (SI)."""

    altitude_m: float
    temperature_k: float
    pressure_pa: float
    density_kg_m3: float
    speed_of_sound_m_s: float


class AtmosphereUSSA76:
    """USSA76 分层大气, 按几何高度采样.

    用法: atmo = AtmosphereUSSA76(); state = atmo.sample(altitude_m).
    """

    def __init__(self, max_altitude_m: float = 500_000.0) -> None:
        """构造模型.

        参数:
            max_altitude_m: 允许的最大几何高度 (m), 必须大于 86 km.

        异常:
            TypeError: 参数类型错误.
            ValueError: 参数非有限值或不超过 86 km.
        """
        if not isinstance(max_altitude_m, (int, float)):
            raise TypeError("max_altitude_m 必须为数值")
        if not math.isfinite(max_altitude_m) or max_altitude_m <= 86_000.0:
            raise ValueError(
                f"max_altitude_m 必须为有限值且大于 86000, 收到 {max_altitude_m!r}"
            )
        self._max_altitude_m = float(max_altitude_m)
        self._layer_bases: tuple[tuple[float, float, float, float], ...] = self._build_bases()
        # 等温段起点压强: 由末层公式推到 84852 m 位势高度, 而非末层底压强.
        last_h_m, last_t_k, last_lapse, last_p_pa = self._layer_bases[-1]
        self._iso_top_pressure_pa = self._pressure_in_layer(
            _ISO_TOP_GEOPOTENTIAL_M, last_h_m, last_t_k, last_lapse, last_p_pa
        )

    @staticmethod
    def _pressure_in_layer(
        h_m: float, h_b_m: float, t_b_k: float, lapse_k_m: float, p_b_pa: float
    ) -> float:
        """层内位势高度 h 处的压强 (Pa), 层底参数为 h_b/t_b/p_b."""
        if lapse_k_m == 0.0:
            return p_b_pa * math.exp(
                -_G0 * (h_m - h_b_m) / (_AIR_R_SPECIFIC * t_b_k)
            )
        t_k = t_b_k + lapse_k_m * (h_m - h_b_m)
        exponent = -_G0 / (_AIR_R_SPECIFIC * lapse_k_m)
        return p_b_pa * (t_k / t_b_k) ** exponent

    @classmethod
    def _build_bases(cls) -> tuple[tuple[float, float, float, float], ...]:
        """预计算各层底 (位势高度, 温度, 直减率, 层底压强), 自海平面向上积分."""
        bases: list[tuple[float, float, float, float]] = []
        p_b_pa = _SEA_LEVEL_PRESSURE_PA
        for i, (h_b_m, t_b_k, lapse_k_m) in enumerate(_LAYERS_TABLE):
            bases.append((h_b_m, t_b_k, lapse_k_m, p_b_pa))
            if i + 1 < len(_LAYERS_TABLE):
                top_m = _LAYERS_TABLE[i + 1][0]
            else:
                top_m = _ISO_TOP_GEOPOTENTIAL_M
            p_b_pa = cls._pressure_in_layer(top_m, h_b_m, t_b_k, lapse_k_m, p_b_pa)
        return tuple(bases)

    def sample(self, altitude_m: float) -> AtmoState:
        """返回几何高度处的完整大气状态.

        异常:
            TypeError: 高度类型错误.
            ValueError: 高度非有限值或超出 [0, max_altitude_m].
        """
        if not isinstance(altitude_m, (int, float)):
            raise TypeError("altitude_m 必须为数值")
        if not math.isfinite(altitude_m):
            raise ValueError(f"altitude_m 必须为有限值, 收到 {altitude_m!r}")
        if altitude_m < 0.0 or altitude_m > self._max_altitude_m:
            raise ValueError(
                f"altitude_m={altitude_m} 超出支持范围 [0, {self._max_altitude_m}] m"
            )
        h_m = geometric_to_geopotential(float(altitude_m))
        if h_m <= _ISO_TOP_GEOPOTENTIAL_M:
            layer = self._layer_bases[0]
            for cand in self._layer_bases:
                if h_m >= cand[0]:
                    layer = cand
                else:
                    break
            h_b_m, t_b_k, lapse_k_m, p_b_pa = layer
            if lapse_k_m == 0.0:
                t_k = t_b_k
                p_pa = p_b_pa * math.exp(
                    -_G0 * (h_m - h_b_m) / (_AIR_R_SPECIFIC * t_b_k)
                )
            else:
                t_k = t_b_k + lapse_k_m * (h_m - h_b_m)
                p_pa = p_b_pa * (t_k / t_b_k) ** (-_G0 / (_AIR_R_SPECIFIC * lapse_k_m))
        else:
            t_k = _T_ISO_K
            p_pa = self._iso_top_pressure_pa * math.exp(
                -_G0 * (h_m - _ISO_TOP_GEOPOTENTIAL_M) / (_AIR_R_SPECIFIC * t_k)
            )
        rho_kg_m3 = p_pa / (_AIR_R_SPECIFIC * t_k)
        a_m_s = math.sqrt(_AIR_GAMMA * _AIR_R_SPECIFIC * t_k)
        return AtmoState(
            altitude_m=float(altitude_m),
            temperature_k=t_k,
            pressure_pa=p_pa,
            density_kg_m3=rho_kg_m3,
            speed_of_sound_m_s=a_m_s,
        )


__all__ = [
    "AtmoState",
    "AtmosphereUSSA76",
    "geometric_to_geopotential",
    "geopotential_to_geometric",
]
