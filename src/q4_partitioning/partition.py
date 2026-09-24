"""问题四核心：任务分区与资源配置核算。

题目规则（硬约束）
------------------
1. 15 个服务区划分为 **2 组** 与 **3 组** 两种方案；每区**必须且只能**属于一组；
   每组至少一个服务区。
2. ★ **保持 Q3 已确定的货箱组批、服务区访问顺序、运输与中继任务安排、
   通信保障关系不变**。
3. ★ **若同一运输架次同时涉及多个服务区，则这些服务区应划入同一任务组**。
4. 各任务组仅承担**本组**服务区的任务；执行期间**各类资源不得跨组调配**。

★ 建模关键：**原子单元（atomic unit）**
--------------------------------------
规则 3 意味着"同架次的多个服务区不可拆开"。把所有这样的服务区集合求并，
得到若干**不可分的最小单元**；分区实际上是对这些单元的划分。

    原子单元 = 由"同架次"关系导出的服务区**连通分量**

若先对 15 个服务区直接做枚举/聚类，几乎必然产生违反规则 3 的方案。
因此正确顺序是：**先求连通分量 → 再对分量划分 → 最后校验并集与互斥**。

资源核算口径
------------
各组独立执行、资源不可跨组 ⟹ 在**组内**重新排程（沿用 Q3 的相对顺序），
按该组的资源池计算所需数量：

- **运输无人机**：组内机型分型的并行峰值（同一时刻在飞的实体机数）
- **共享电池组数**：既要在时段上不重叠，又要满足"用后充满"的周转约束
- **中继无人机 / 能源组件**：同理，按中继架次的服务窗口与充电周转核算
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field

import pandas as pd

from src.physics.battery import charging_time


# ---------------------------------------------------------------- 数据结构

@dataclass(frozen=True)
class SortieRec:
    """一个运输架次（Q3 方案的记录）。"""

    sortie_id: str
    type_code: str
    uav_id: str
    battery_id: str
    start_s: float
    return_s: float
    stops: tuple[str, ...]
    energy_kwh: float = 0.0

    @property
    def services(self) -> frozenset[str]:
        return frozenset(self.stops)


@dataclass(frozen=True)
class RelayRec:
    """一个中继架次（Q3 方案的记录）。"""

    sortie_id: str
    relay_uav_id: str
    pack_id: str
    start_s: float
    link_ready_s: float
    service_end_s: float
    return_s: float
    energy_kwh: float
    covers: tuple[str, ...]
    """保障的**运输架次**编号。"""


@dataclass
class GroupResources:
    """一个任务组的资源需求。"""

    group_id: str
    services: tuple[str, ...]
    n_sorties: int
    n_relay_sorties: int
    uav_by_type: dict[str, int] = field(default_factory=dict)
    battery_by_type: dict[str, int] = field(default_factory=dict)
    relay_uavs: int = 0
    relay_packs: int = 0
    total_energy_kwh: float = 0.0
    workload_s: float = 0.0
    """组内运输作业量（架次时长之和，s）。"""


# ---------------------------------------------------------------- 原子单元

def components(sorties: list[SortieRec], services: list[str] | None = None) -> list[frozenset[str]]:
    """求由"同架次"关系导出的服务区**连通分量**。

    参数
    ----
    sorties : 参与构图的服务区架次集合（可只传其子集，用于"去掉某架次后"的分析）
    services : 需要纳入图的全部服务区；None 时只包含架次中出现过的
    """
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for x in services or []:
        find(x)
    for s in sorties:
        stops = list(s.stops)
        for x in stops:
            find(x)
        for x, y in zip(stops, stops[1:]):
            union(x, y)

    groups: dict[str, set[str]] = {}
    for node in list(parent):
        groups.setdefault(find(node), set()).add(node)
    return [frozenset(v) for v in groups.values()]


def atomic_units(sorties: list[SortieRec]) -> list[frozenset[str]]:
    """求"同架次"关系导出的服务区**连通分量**（不可分的最小单元）。

    两个服务区若出现在同一架次中，则属于同一单元；
    单元之间不存在同架次约束，可以自由分配到不同任务组。
    """
    return components(sorties)


def bridge_sorties(
    sorties: list[SortieRec], services: list[str]
) -> list[tuple[SortieRec, int]]:
    """找出**桥接架次**：去掉它之后连通分量数会增加的多点架次。

    返回 [(架次, 去掉后的分量数), ...]，按分量数降序。
    这类架次是"无法分区"的直接原因，也是最小改动的着力点。
    """
    base = len(components(sorties, services))
    out: list[tuple[SortieRec, int]] = []
    for i, s in enumerate(sorties):
        if len(s.stops) < 2:
            continue
        rest = [x for j, x in enumerate(sorties) if j != i]
        n = len(components(rest, services))
        if n > base:
            out.append((s, n))
    return sorted(out, key=lambda t: -t[1])


def minimal_edits_for_partition(
    sorties: list[SortieRec], services: list[str], k: int
) -> tuple[list[SortieRec], int]:
    """给出**最小改动**：去掉最少的多点架次后，使连通分量数 ≥ k。

    逐条尝试去掉"桥接架次"，直到分量数达到 k。
    返回 (被去掉的架次列表, 最终分量数)。
    """
    removed: list[SortieRec] = []
    cur = list(sorties)
    while True:
        n = len(components(cur, services))
        if n >= k:
            return removed, n
        cands = bridge_sorties(cur, services)
        if not cands:
            return removed, n
        # 优先去掉"去掉后分量最多"的
        best, _ = cands[0]
        removed.append(best)
        cur = [x for x in cur if x is not best]


def enumerate_partitions(
    units: list[frozenset[str]], k: int
) -> list[list[frozenset[str]]]:
    """把原子单元划分成 `k` 个非空任务组（枚举全部方案）。

    ★ 复杂度：第二类斯特林数 S(n, k)。本题 n ≤ 15，k ∈ {2, 3}，
      最坏 S(15,3) = 2,375,101 —— 原子单元数通常远小于 15（同架次把它们并起来了），
      实际规模很小。若单元数仍偏大，可改用 `greedy_balanced_partition`。
    """
    n = len(units)
    if k > n or k <= 0:
        return []
    out: list[list[frozenset[str]]] = []

    # 受限增长串（restricted growth string）枚举，天然避免重复：
    # 第 i 个单元只能分到 0..used（used = 此前用过的最大编号 + 1），
    # 即"要么进已有组，要么开一个新组"。
    def rec(i: int, assign: list[int]) -> None:
        if i == n:
            if len(set(assign)) == k:
                buckets: list[list[frozenset[str]]] = [[] for _ in range(k)]
                for u, a in zip(units, assign):
                    buckets[a].append(u)
                out.append([frozenset().union(*b) for b in buckets])
            return
        used = max(assign) + 1 if assign else 0
        # 进入已有组
        for c in range(used):
            rec(i + 1, assign + [c])
        # 开一个新组（若还没用满 k 组）
        if used < k:
            rec(i + 1, assign + [used])

    rec(0, [])
    return out


# ---------------------------------------------------------------- 资源核算

def _parallel_peak(spans: list[tuple[float, float]]) -> int:
    """时段列表的**并行峰值**（同一时刻同时占用的最大数量）。

    ★ 约定：首尾相接（前一段 end == 后一段 start）**不算重叠** ——
      同一架无人机刚返回即可接下一架次，不应被计为两架在用。
      因此同一时刻先处理 −1（结束）再处理 +1（开始），
      即排序键用 (时刻, 增量) 升序（−1 在 +1 之前）。
      这与 `ResourcePool.earliest_uav`（`available_at_s <= start` 即可复用）的口径一致。
    """
    events: list[tuple[float, int]] = []
    for a, b in spans:
        if b <= a:
            continue
        events.append((a, +1))
        events.append((b, -1))
    events.sort(key=lambda e: (e[0], e[1]))  # -1 排在 +1 之前
    cur = peak = 0
    for _, d in events:
        cur += d
        peak = max(peak, cur)
    return peak


def batteries_required(
    spans: list[tuple[float, float]], soc_ends: list[float], t_full_s: float
) -> int:
    """满足"任务不重叠 + 用后充满"所需的最少电池组数（贪心区间调度）。

    按开工时刻排序，每组电池维护"下次可用时刻"（任务结束 + 充电时间）；
    能接就接最早可用的那组，接不上就新开一组。
    """
    if not spans:
        return 0
    order = sorted(range(len(spans)), key=lambda i: spans[i][0])
    avail: list[float] = []
    for i in order:
        a, b = spans[i]
        soc = soc_ends[i] if i < len(soc_ends) else 1.0
        need_by = a
        placed = False
        for j in range(len(avail)):
            if avail[j] <= need_by + 1e-9:
                avail[j] = b + charging_time(soc, t_full_s)
                placed = True
                break
        if not placed:
            avail.append(b + charging_time(soc, t_full_s))
    return len(avail)


def soc_from_energy(energy_kwh: float, total_kwh: float) -> float:
    if total_kwh <= 0:
        return 1.0
    return max(0.0, 1.0 - energy_kwh / total_kwh)


def group_resources(
    group_id: str,
    services: tuple[str, ...],
    sorties: list[SortieRec],
    relays: list[RelayRec],
    uav_energy: dict[str, float],
    battery_t_full: dict[str, float],
    relay_t_full: float = 1800.0,
    relay_energy: float = 3.2,
) -> GroupResources:
    """核算一个任务组的四类资源需求。

    ★ 只统计**属于本组**的架次（架次的所有服务区必须都在组内）。
    """
    svc_set = set(services)
    my_sorties = [s for s in sorties if set(s.stops) <= svc_set]
    my_ids = {s.sortie_id for s in my_sorties}
    my_relays = [r for r in relays if set(r.covers) <= my_ids]

    res = GroupResources(
        group_id=group_id,
        services=services,
        n_sorties=len(my_sorties),
        n_relay_sorties=len(my_relays),
        total_energy_kwh=sum(s.energy_kwh for s in my_sorties)
        + sum(r.energy_kwh for r in my_relays),
        workload_s=sum(s.return_s - s.start_s for s in my_sorties),
    )

    # 运输无人机：分机型并行峰值
    by_type: dict[str, list[tuple[float, float]]] = {}
    for s in my_sorties:
        by_type.setdefault(s.type_code, []).append((s.start_s, s.return_s))
    for code, spans in by_type.items():
        res.uav_by_type[code] = _parallel_peak(spans)

    # 共享电池：分机型按周转核算
    spans_by_type: dict[str, list[tuple[float, float]]] = {}
    soc_by_type: dict[str, list[float]] = {}
    for s in my_sorties:
        spans_by_type.setdefault(s.type_code, []).append((s.start_s, s.return_s))
        soc_by_type.setdefault(s.type_code, []).append(
            soc_from_energy(s.energy_kwh, uav_energy.get(s.type_code, 1.0))
        )
    for code, spans in spans_by_type.items():
        res.battery_by_type[code] = batteries_required(
            spans, soc_by_type[code], battery_t_full.get(code, 1800.0)
        )

    # 中继无人机：并行峰值
    res.relay_uavs = _parallel_peak(
        [(r.link_ready_s, r.service_end_s) for r in my_relays]
    )
    # 中继能源组件：按周转核算
    res.relay_packs = batteries_required(
        [(r.start_s, r.return_s) for r in my_relays],
        [soc_from_energy(r.energy_kwh, relay_energy) for r in my_relays],
        relay_t_full,
    )
    return res


# ---------------------------------------------------------------- 方案评价

@dataclass
class PartitionPlan:
    """一个分区方案（k 组）及其资源核算。"""

    k: int
    groups: list[GroupResources]

    @property
    def total_uavs(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for g in self.groups:
            for c, n in g.uav_by_type.items():
                out[c] = out.get(c, 0) + n
        return out

    @property
    def total_batteries(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for g in self.groups:
            for c, n in g.battery_by_type.items():
                out[c] = out.get(c, 0) + n
        return out

    @property
    def total_relay_uavs(self) -> int:
        return sum(g.relay_uavs for g in self.groups)

    @property
    def total_relay_packs(self) -> int:
        return sum(g.relay_packs for g in self.groups)

    @property
    def max_group_workload(self) -> float:
        return max((g.workload_s for g in self.groups), default=0.0)

    @property
    def workload_imbalance(self) -> float:
        """组间工作量不均衡度 = (max − min) / mean；越小越均衡。"""
        ws = [g.workload_s for g in self.groups]
        if not ws or sum(ws) == 0:
            return 0.0
        return (max(ws) - min(ws)) / (sum(ws) / len(ws))

    @property
    def n_sorties(self) -> int:
        return sum(g.n_sorties for g in self.groups)


def score_plan(
    plan: PartitionPlan,
    inventory: dict[str, int],
    battery_inventory: dict[str, int],
    relay_inventory: dict[str, int],
) -> tuple:
    """方案排序键（越小越好）：

    (资源缺口总数, 资源总规模, 组间不均衡度)
    """
    gap = 0
    for c, n in plan.total_uavs.items():
        gap += max(0, n - inventory.get(c, 0))
    for c, n in plan.total_batteries.items():
        gap += max(0, n - battery_inventory.get(c, 0))
    gap += max(0, plan.total_relay_uavs - relay_inventory.get("relay_uavs", 0))
    gap += max(0, plan.total_relay_packs - relay_inventory.get("relay_packs", 0))

    scale = (
        sum(plan.total_uavs.values())
        + sum(plan.total_batteries.values())
        + plan.total_relay_uavs
        + plan.total_relay_packs
    )
    return (gap, scale, round(plan.workload_imbalance, 6))


def select_best_partition(
    units: list[frozenset[str]],
    k: int,
    sorties: list[SortieRec],
    relays: list[RelayRec],
    uav_energy: dict[str, float],
    battery_t_full: dict[str, float],
    inventory: dict[str, int],
    battery_inventory: dict[str, int],
    relay_inventory: dict[str, int],
    max_enum: int = 200_000,
) -> tuple[PartitionPlan, int]:
    """枚举/贪心搜索最优分区方案，返回 (最优方案, 枚举的方案数)。"""
    parts = enumerate_partitions(units, k)
    if len(parts) > max_enum:
        parts = parts[:max_enum]
    best: PartitionPlan | None = None
    best_key: tuple | None = None
    for part in parts:
        groups = []
        for gi, svcs in enumerate(sorted(part, key=lambda s: sorted(s))):
            if not svcs:
                continue
            groups.append(
                group_resources(
                    f"G{gi + 1}", tuple(sorted(svcs)), sorties, relays,
                    uav_energy, battery_t_full,
                )
            )
        plan = PartitionPlan(k=k, groups=groups)
        key = score_plan(plan, inventory, battery_inventory, relay_inventory)
        if best_key is None or key < best_key:
            best, best_key = plan, key
    assert best is not None, "没有可行分区"
    return best, len(parts)
