"""地球物理与任务级常量 (SI 单位).

注意: 大气模块内部使用 USSA76 位势参考半径 (6356.766 km), 与轨迹用
平均半径 6371 km 不同, 二者不可混用; 位势换算只存在于 atmosphere.py.
"""

# 地球引力参数 (WGS-84 常用值), 单位 m^3 / s^2.
EARTH_MU_SI: float = 3.986004418e14

# 轨迹几何用地球平均半径, 单位 m.
EARTH_RADIUS_TRAJ_M: float = 6371.0e3

# 标准重力加速度 (发动机比冲与大气分层公式用), 单位 m / s^2.
STANDARD_GRAVITY_M_S2: float = 9.80665

__all__ = [
    "EARTH_MU_SI",
    "EARTH_RADIUS_TRAJ_M",
    "STANDARD_GRAVITY_M_S2",
]
