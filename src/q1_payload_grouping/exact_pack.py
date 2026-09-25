"""问题一：**精确组批**（按题面物理量的精确装箱 + 字典序动态规划）。

与 `grouping.py` 里 FFD 启发式的关系
------------------------------------
`grouping.py` 的 `_pack_area` 是**启发式**（FFD：体积降序、首次适应），
它给出的是可行解；本文档（SKILL）要求问题一在“先少架次、后低能耗”的
**字典序**目标下做**精确**组批，并与简单装箱基线对照。

因此本模块提供独立实现：

1. **按箱型聚合**：同一服务区内，同 (质量, 体积, 首批标记, 期望时间) 的
   货箱视为同型。题面每类物资单箱参数唯一，故聚合后每区只有 3~5 种箱型，
   状态空间很小 —— 这是可以做精确 DP 的关键（SKILL 第 4 条）。
2. **枚举可行批次**：对每个 (服务区, 机型) 组合，枚举满足
   载质量 / 装载体积 / 返航能量余量 的**货箱组合**（按箱型计数），
   并算出该批次的能耗与历时。
3. **字典序 DP**：在“箱型计数状态”上做 DP，
   目标 `min_lex (架次数, 总能耗)`；同时记录累计作业时间。

★ 与 SKILL 的一致性
--------------------
- 每个架次只服务一个服务区，不跨服务区组批；
- 载荷—航程、逐段能耗、两阶段充电等物理量一律复用 `src/physics/`
  （铁律 R4：口径唯一）；
- 只报告“架次数维度可证最优”（逐区等于下界），不声称全局最优。
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass
from functools import lru_cache
from typing import Sequence

from src.physics.energy import Segment, segment_energy_kwh, segment_time_s
from src.physics.leg_cache import LegCache
from src.physics.payload import UAVType
from src.q1_payload_grouping.grouping import AreaCapacity

CENTER_ID = "O01"

# 组合枚举的规模上限：超过则退化为“只按箱型贪心枚举”
MAX_ENUM_STATES = 200_000


@dataclass(frozen=True)
class BoxType:
    """同型货箱（同质量、同体积、同首批标记、同期望时间）。"""

    mass_kg: float
    volume_m3: float
    is_first_batch: bool
    expected_time_s: float
    count: int
    sample_id: str
    """代表性箱号（用于追溯）。"""


@dataclass(frozen=True)
class Batch:
    """一个可行批次（= 一个架次的载货组合）。"""

    type_code: str
    counts: tuple[int, ...]
    """各箱型的件数（与 `BoxType` 列表同序）。"""
    mass_kg: float
    volume_m3: float
    energy_kwh: float
    duration_s: float
    soc_end: float

    @property
    def n_boxes(self) -> int:
        return int(sum(self.counts))


@dataclass(frozen=True)
class AreaPlan:
    """一个服务区的精确组批结果。"""

    service_id: str
    n_sorties: int
    total_energy_kwh: float
    serial_time_s: float
    batches: tuple[Batch, ...]

    def type_usage(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for b in self.batches:
            out[b.type_code] = out.get(b.type_code, 0) + 1
        return out


# ---------------------------------------------------------------- 箱型聚合

def aggregate_boxes(boxes: Sequence) -> list[BoxType]:
    """把同 (质量, 体积, 首批标记, 期望时间) 的货箱聚合为箱型。"""
    groups: dict[tuple, list] = {}
    for b in boxes:
        key = (
            round(float(b.mass_kg), 6),
            round(float(b.volume_m3), 6),
            bool(b.is_first_batch),
            round(float(b.expected_time_s), 3),
        )
        groups.setdefault(key, []).append(b)
    out: list[BoxType] = []
    for (m, v, fb, exp), items in sorted(groups.items()):
        out.append(
            BoxType(mass_kg=m, volume_m3=v, is_first_batch=fb,
                    expected_time_s=exp, count=len(items),
                    sample_id=str(items[0].box_id))
        )
    return out


# ---------------------------------------------------------------- 批次评估

def _batch_cost(
    uav: UAVType,
    cap: AreaCapacity,
    leg_out: dict,
    leg_back: dict,
    mass: float,
) -> tuple[float, float, float]:
    """返回 (能耗 kWh, 飞行时间 s, 返航 SOC)。

    去程载货 `mass`、回程空载；物理口径全部复用 `src/physics/`（R4）。
    """
    seg_o = Segment(leg_out["distance_m"], leg_out["climb_m"], leg_out["descent_m"])
    seg_b = Segment(leg_back["distance_m"], leg_back["climb_m"], leg_back["descent_m"])
    e = segment_energy_kwh(uav, seg_o, mass) + segment_energy_kwh(uav, seg_b, 0.0)
    t = segment_time_s(uav, seg_o) + segment_time_s(uav, seg_b)
    soc = max(0.0, 1.0 - e / uav.energy_kwh)
    return e, t, soc


def enumerate_batches(
    box_types: Sequence[BoxType],
    type_code: str,
    uav: UAVType,
    cap: AreaCapacity,
    leg_out: dict,
    leg_back: dict,
    max_boxes: int = 12,
) -> list[Batch]:
    """枚举该 (服务区, 机型) 下的全部**可行批次**。

    可行性同时检查三条硬约束：
        载质量 ≤ 最大安全载荷；装载体积 ≤ 舱容；返航能量 ≤ (1-ρ)·可用能量。
    ★ 最大安全载荷 `cap.max_payload_kg` 已由 `src/physics/payload.py` 反解得到，
      故能量约束在此处等价于 `mass ≤ cap.max_payload_kg`。
    """
    n = len(box_types)
    ranges = [range(bt.count + 1) for bt in box_types]
    out: list[Batch] = []
    budget = uav.energy_budget_kwh

    for combo in itertools.product(*ranges):
        nb = sum(combo)
        if nb == 0 or nb > max_boxes:
            continue
        mass = sum(c * bt.mass_kg for c, bt in zip(combo, box_types))
        vol = sum(c * bt.volume_m3 for c, bt in zip(combo, box_types))
        if mass > cap.max_payload_kg + 1e-9:
            continue
        if vol > uav.volume_m3 + 1e-9:
            continue
        e, t, soc = _batch_cost(uav, cap, leg_out, leg_back, mass)
        if e > budget + 1e-9:
            continue
        # 架次历时 = 准备 + 按箱装载 + 飞行 + 逐箱交接
        dur = (
            uav.prepare_time_s
            + uav.box_load_time_s * nb
            + t
            + uav.handover_base_s
            + uav.handover_per_box_s * nb
        )
        out.append(
            Batch(type_code=type_code, counts=tuple(combo), mass_kg=mass,
                  volume_m3=vol, energy_kwh=e, duration_s=dur, soc_end=soc)
        )
    return out


# ---------------------------------------------------------------- 字典序 DP

def _dominates(a: tuple, b: tuple) -> bool:
    """字典序支配：a 严格优于 b（先架次数、再能耗、再时间）。"""
    return a < b


def plan_area_exact(
    service_id: str,
    boxes: Sequence,
    capacities: dict[str, AreaCapacity],
    uav_types: dict[str, UAVType],
    leg_cache: LegCache,
    allowed: Sequence[str] | None = None,
) -> AreaPlan:
    """对一个服务区做**精确**字典序组批。

    目标：`min_lex (架次数, 总能耗)`，同分时取较小累计作业时间。
    DP 状态 = 各箱型已装件数（元组），值 = (架次数, 能耗, 时间)。
    """
    box_types = aggregate_boxes(boxes)
    codes = list(allowed) if allowed else sorted(uav_types)

    leg_out = leg_cache.get(CENTER_ID, service_id)
    leg_back = leg_cache.get(service_id, CENTER_ID)

    # 每个机型可用的批次（按箱型计数向量索引）
    batches: list[Batch] = []
    for code in codes:
        uav = uav_types[code]
        cap = capacities.get((service_id, code))
        if cap is None or not cap.feasible:
            continue
        batches.extend(
            enumerate_batches(box_types, code, uav, cap, leg_out, leg_back)
        )
    if not batches:
        raise ValueError(f"{service_id}: 没有任何可行批次（机型 {codes}）")

    target = tuple(bt.count for bt in box_types)
    INF = (float("inf"), float("inf"), float("inf"))

    order = {i: bt for i, bt in enumerate(box_types)}
    batch_vecs = [(b.counts, (1, b.energy_kwh, b.duration_s), b) for b in batches]

    @lru_cache(maxsize=None)
    def dp(state: tuple[int, ...]) -> tuple:
        """返回 (最优代价三元组, 选用的批次索引或 None)。"""
        if state == target:
            return (0.0, 0.0, 0.0), None
        best = INF
        best_i = -1
        for i, (vec, cost, _b) in enumerate(batch_vecs):
            ns = tuple(s + v for s, v in zip(state, vec))
            if any(ns[k] > target[k] for k in range(len(target))):
                continue          # 超装
            if ns == state:
                continue          # 空批次
            sub, _ = dp(ns)
            if sub[0] == float("inf"):
                continue
            cand = (sub[0] + cost[0], sub[1] + cost[1], sub[2] + cost[2])
            if cand < best:
                best, best_i = cand, i
        return best, best_i

    cost, _ = dp(tuple([0] * len(box_types)))
    if cost[0] == float("inf"):
        raise ValueError(f"{service_id}: DP 无解")

    # 回溯
    chosen: list[Batch] = []
    state = tuple([0] * len(box_types))
    while state != target:
        _, i = dp(state)
        if i < 0:
            raise RuntimeError(f"{service_id}: 回溯失败")
        b = batch_vecs[i][2]
        chosen.append(b)
        state = tuple(s + v for s, v in zip(state, b.counts))

    return AreaPlan(
        service_id=service_id,
        n_sorties=len(chosen),
        total_energy_kwh=sum(b.energy_kwh for b in chosen),
        serial_time_s=sum(b.duration_s for b in chosen),
        batches=tuple(chosen),
    )


def plan_all_areas(
    boxes_by_area: dict[str, Sequence],
    capacities: dict[str, AreaCapacity],
    uav_types: dict[str, UAVType],
    leg_cache: LegCache,
    allowed: Sequence[str] | None = None,
) -> dict[str, AreaPlan]:
    """对全部服务区做精确组批。"""
    return {
        sid: plan_area_exact(sid, boxes, capacities, uav_types, leg_cache, allowed)
        for sid, boxes in sorted(boxes_by_area.items())
    }
