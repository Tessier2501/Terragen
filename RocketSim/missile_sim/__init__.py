"""RocketSim 2D 弹道导弹仿真包.

M1 范围: USSA76 大气, 球面 2D 自由飞行积分与事件, 开普勒解析验证.
"""

from . import constants
from .atmosphere import AtmoState, AtmosphereUSSA76
from .flight import EventRecord, EventSpec, FlightResult, simulate_free_flight
from .kepler import KeplerFlight, kepler_flight

__version__ = "0.1.0"

__all__ = [
    "AtmoState",
    "AtmosphereUSSA76",
    "EventRecord",
    "EventSpec",
    "FlightResult",
    "KeplerFlight",
    "constants",
    "kepler_flight",
    "simulate_free_flight",
]
