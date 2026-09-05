"""RocketSim 2D 弹道导弹仿真包.

M1: USSA76 大气, 球面 2D 自由飞行积分与事件, 开普勒解析验证.
M2: Cd(M) 半经验气动, 发动机 F(h)/燃烧形状族, 转向预算与程序角,
    动力段积分 (质量/推力/阻力/关机事件).
"""

from . import (
    aerodynamics,
    constants,
    propulsion,
    steering,
    vehicle,
)
from .aerodynamics import AerodynamicModel, BodyGeometry
from .atmosphere import AtmoState, AtmosphereUSSA76
from .flight import (
    EventRecord,
    EventSpec,
    FlightResult,
    simulate_free_flight,
    simulate_powered_flight,
)
from .kepler import KeplerFlight, kepler_flight
from .propulsion import (
    BurnRateBase,
    ConstantBurnRate,
    Motor,
    RegressiveLinearBurnRate,
    TwoLevelBurnRate,
)
from .steering import (
    ClimbSchedule,
    NormalAccelBudget,
    PitchOverSchedule,
    SteeringAuthority,
)
from .vehicle import Missile

__version__ = "0.2.0"

__all__ = [
    "AerodynamicModel",
    "AtmoState",
    "AtmosphereUSSA76",
    "BodyGeometry",
    "BurnRateBase",
    "ClimbSchedule",
    "ConstantBurnRate",
    "EventRecord",
    "EventSpec",
    "FlightResult",
    "KeplerFlight",
    "Missile",
    "Motor",
    "NormalAccelBudget",
    "PitchOverSchedule",
    "RegressiveLinearBurnRate",
    "SteeringAuthority",
    "TwoLevelBurnRate",
    "aerodynamics",
    "constants",
    "kepler_flight",
    "propulsion",
    "simulate_free_flight",
    "simulate_powered_flight",
    "steering",
    "vehicle",
]
