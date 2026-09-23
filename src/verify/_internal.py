"""校验器内部状态（不污染公开的数据契约）。

`Sortie` 是**方案上报**的数据结构，不应被校验器塞入私有字段。
校验过程中需要一些派生量（货箱总质量/体积、架次结束时刻等），
统一放在这里，用 `id(sortie)` 作键。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SortieDerived:
    """一个架次的派生量（由校验器从零重算，不信任上报值）。"""

    total_mass_kg: float = 0.0
    total_volume_m3: float = 0.0
    energy_kwh: float = 0.0
    return_soc: float = 1.0
    end_s: float = 0.0
    flight_time_s: float = 0.0


@dataclass
class DerivedStore:
    """按架次 id 存放派生量。"""

    items: dict[str, SortieDerived] = field(default_factory=dict)

    def get(self, sortie_id: str) -> SortieDerived:
        return self.items.setdefault(sortie_id, SortieDerived())

    def __contains__(self, sortie_id: str) -> bool:
        return sortie_id in self.items
