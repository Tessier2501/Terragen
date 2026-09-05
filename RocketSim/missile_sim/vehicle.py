"""弹体装配 (M2): 几何 + 气动 + 发动机 + 名称的打包容器.

vehicle 不 import flight/steering, 仅供调用方组合后传给动力飞行积分.
"""

from __future__ import annotations

from .aerodynamics import AerodynamicModel, BodyGeometry
from .propulsion import Motor


class Missile:
    """一枚可仿真的导弹: 装配好的弹体/气动/发动机.

    参数:
        name: 弹体名 (报告用).
        motor: 发动机 (燃烧形状 + 比冲 + 质量预算).
        geometry: 弹体几何.
        aero_model: 气动模型; 缺省时按几何与默认底阻系数构造.
    """

    def __init__(
        self,
        name: str,
        motor: Motor,
        geometry: BodyGeometry,
        aero_model: AerodynamicModel | None = None,
    ) -> None:
        if not isinstance(name, str) or not name.strip():
            raise ValueError("name 必须为非空字符串")
        for label, value in (("motor", motor), ("geometry", geometry)):
            if not isinstance(value, (Motor, BodyGeometry)):
                raise TypeError(f"{label} 类型错误")
        if aero_model is not None and not isinstance(aero_model, AerodynamicModel):
            raise TypeError("aero_model 必须为 AerodynamicModel")
        self.name = name
        self.motor = motor
        self.geometry = geometry
        self.aero_model: AerodynamicModel = (
            aero_model if aero_model is not None else AerodynamicModel(geometry)
        )

    @property
    def initial_mass_kg(self) -> float:
        """起飞/点火质量 (kg)."""
        return self.motor.initial_mass_kg

    @property
    def dry_mass_kg(self) -> float:
        """关机后结构质量 (kg)."""
        return self.motor.dry_mass_kg


__all__ = ["Missile"]
