"""问题二调度：资源周转（无人机 / 共享电池 / 充电）与时刻安排。

资源规则（题目附录 2）
----------------------
- 共享电池是**独立资源**，各记录 SOC；初始 SOC = 100%
- 同一资源的**任务占用与充电时段不得重叠**；不同资源可并行充电
- 任务结束后立即充电，充满所需时间由两阶段模型给出（`physics.battery`）
- 同一机型的电池可在该机型不同实体无人机间调度；**机型间不可混用**
- 实体无人机：同一时刻只能执行一个架次；返回后才能接下一个

调度策略：**尽早调度（earliest feasible）**
    架次 → 在满足「无人机可用」且「电池充满」的前提下，取最早就绪时刻开工。
    单架次内多点串飞，因此一个架次只占用无人机与电池各一次连续时间段。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from src.physics.battery import charging_time
from src.physics.energy import Segment, segment_time_s
from src.physics.payload import UAVType
from src.q2_transport_schedule.models import evaluate_sortie


@dataclass
class ResourceState:
    """一个资源的可用时刻（无人机或电池）。"""

    resource_id: str
    available_at_s: float = 0.0
    """最早可再次投入任务的时刻。"""


@dataclass
class BatteryState(ResourceState):
    """共享电池：记录 SOC 与充电起点（用于输出充电计划）。"""

    t_full_s: float = 0.0
    last_soc: float = 1.0
    charge_start_s: float = 0.0
    charge_end_s: float = 0.0
    charges: list[tuple[float, float, float]] = field(default_factory=list)
    """历次充电窗口 (start, end, soc_before)。"""


class ResourcePool:
    """管理某机型的实体无人机与共享电池。"""

    def __init__(
        self,
        uav_ids: list[str],
        battery_ids: list[str],
        t_full_s: float,
    ) -> None:
        self.uavs: dict[str, ResourceState] = {
            u: ResourceState(u) for u in uav_ids
        }
        self.batteries: dict[str, BatteryState] = {
            b: BatteryState(b, t_full_s=t_full_s) for b in battery_ids
        }

    # ---- 无人机 ----

    def earliest_uav(self, not_before_s: float) -> tuple[str, float] | None:
        """取最早可用的无人机。"""
        if not self.uavs:
            return None
        rid, st = min(self.uavs.items(), key=lambda kv: max(kv[1].available_at_s, not_before_s))
        return rid, max(st.available_at_s, not_before_s)

    # ---- 电池 ----

    def earliest_battery(self, not_before_s: float) -> tuple[str, float] | None:
        """取最早充满的电池。"""
        if not self.batteries:
            return None
        rid, st = min(
            self.batteries.items(),
            key=lambda kv: max(kv[1].available_at_s, not_before_s),
        )
        return rid, max(st.available_at_s, not_before_s)

    def occupy(
        self,
        uav_id: str,
        battery_id: str,
        start_s: float,
        end_s: float,
        soc_end: float,
    ) -> None:
        """占用无人机与电池，并为电池排入充电窗口。

        调用方需保证 `start_s >= 该资源的 available_at_s`（由 `earliest_*` 保证）。
        """
        u = self.uavs[uav_id]
        b = self.batteries[battery_id]
        if start_s < u.available_at_s - 1e-9:
            raise ValueError(
                f"无人机 {uav_id} 在 {start_s:.1f}s 尚未可用（{u.available_at_s:.1f}s）"
            )
        if start_s < b.available_at_s - 1e-9:
            raise ValueError(
                f"电池 {battery_id} 在 {start_s:.1f}s 尚未充满（{b.available_at_s:.1f}s）"
            )
        u.available_at_s = end_s
        # 电池：任务结束后立即充电
        t_chg = charging_time(soc_end, b.t_full_s)
        b.charges.append((end_s, end_s + t_chg, soc_end))
        b.charge_start_s = end_s
        b.charge_end_s = end_s + t_chg
        b.last_soc = soc_end
        b.available_at_s = end_s + t_chg


@dataclass
class ScheduledSortie:
    """调度后的架次（含资源与时刻）。"""

    sortie_id: str
    plan_index: int
    uav_id: str
    type_code: str
    battery_id: str
    stops: tuple[str, ...]
    boxes_by_stop: dict[str, tuple[str, ...]]
    start_s: float
    return_s: float
    energy_kwh: float
    soc_end: float
    delivery_times: dict[str, float]
    """{服务区: 交付完成时刻}。"""
    n_boxes: int

    @property
    def duration_s(self) -> float:
        return self.return_s - self.start_s


def build_pools(
    fleet: dict[str, list[str]],
    battery_inventory: dict[str, int],
    t_full: dict[str, float],
) -> dict[str, ResourcePool]:
    """按机型建立资源池。

    电池编号规则：`{机型}-B{序号:02d}`（如 `A-B01`），
    与校验器 `known_battery_ids` 的约定一致。
    """
    pools: dict[str, ResourcePool] = {}
    for code, uav_ids in fleet.items():
        n_bat = int(battery_inventory.get(code, 0))
        bats = [f"{code}-B{i:02d}" for i in range(1, n_bat + 1)]
        pools[code] = ResourcePool(uav_ids, bats, float(t_full.get(code, 1800.0)))
    return pools


def schedule_ordered(
    plans: list,
    uav_types: dict,
    leg_cache,
    boxes_by_id: dict,
    pools: dict[str, ResourcePool],
    center_id: str = "O01",
) -> list[ScheduledSortie]:
    """按给定顺序调度架次，返回**精确**时刻与交付时刻。

    ★ 关键：工作时段 = 准备 + 装载 + 飞行 + 投送交接（**不含充电**）。
      充电发生在任务结束之后，只影响该电池的下一次可用时刻。
      这与"同一资源的任务占用与充电时段不得重叠"一致。

    顺序策略：按「架上最紧时限」升序（最紧的箱优先），
    这样资源周转造成的推迟会优先落在不紧急的架次上。
    """
    from src.physics.energy import Segment, segment_time_s

    remaining = list(plans)

    def urgency(p) -> float:
        best = math.inf
        for bid in p.all_box_ids:
            dl = deadlines_of(boxes_by_id, bid)
            if dl is not None:
                best = min(best, dl)
        return best

    remaining.sort(key=urgency)

    scheduled: list[ScheduledSortie] = []
    for k, plan in enumerate(remaining, start=1):
        uav = uav_types[plan.type_code]
        pool = pools[plan.type_code]

        u = pool.earliest_uav(0.0)
        b = pool.earliest_battery(0.0)
        if u is None or b is None:
            raise RuntimeError(f"{plan.type_code} 型资源不足")
        uav_id, t_u = u
        bat_id, t_b = b
        start = max(t_u, t_b)

        # 精确时间推进
        n = plan.n_boxes
        t = start + uav.prepare_time_s + uav.box_load_time_s * n
        dt: dict[str, float] = {}
        prev = center_id
        for svc in plan.stops:
            g = leg_cache.get(prev, svc)
            t += segment_time_s(uav, Segment(g["distance_m"], g["climb_m"], g["descent_m"]))
            kb = len(plan.boxes_by_stop.get(svc, ()))
            t += uav.handover_base_s + uav.handover_per_box_s * kb
            dt[svc] = t
            prev = svc
        g_back = leg_cache.get(plan.stops[-1], center_id)
        t += segment_time_s(
            uav, Segment(g_back["distance_m"], g_back["climb_m"], g_back["descent_m"])
        )
        end = t

        mass = {s: sum(boxes_by_id[x].mass_kg for x in plan.boxes_by_stop.get(s, ()))
                for s in plan.stops}
        vol = {s: sum(boxes_by_id[x].volume_m3 for x in plan.boxes_by_stop.get(s, ()))
               for s in plan.stops}
        ev = evaluate_sortie(plan, uav, leg_cache, mass, vol, center_id)

        pool.occupy(uav_id, bat_id, start, end, ev.return_soc)
        scheduled.append(
            ScheduledSortie(
                sortie_id=f"T{k:03d}", plan_index=k - 1, uav_id=uav_id,
                type_code=plan.type_code, battery_id=bat_id, stops=plan.stops,
                boxes_by_stop=plan.boxes_by_stop, start_s=start, return_s=end,
                energy_kwh=ev.energy_kwh, soc_end=ev.return_soc,
                delivery_times=dt, n_boxes=n,
            )
        )
    return sorted(scheduled, key=lambda s: s.start_s)


def deadlines_of(boxes_by_id: dict, bid: str) -> float | None:
    """从 Box 取"最紧时限"（首批截止优先，否则期望送达时间）。"""
    b = boxes_by_id.get(bid)
    if b is None:
        return None
    if b.is_first_batch and b.first_batch_deadline_s is not None:
        return float(b.first_batch_deadline_s)
    return float(b.expected_time_s) if b.expected_time_s is not None else None


def _plan_deadline(plan, boxes_by_id: dict) -> float:
    """架次内最紧的时限（用于排序）。"""
    best = math.inf
    for bid in plan.all_box_ids:
        d = deadlines_of(boxes_by_id, bid)
        if d is not None:
            best = min(best, d)
    return best


def _plan_geometry(plan, uav, leg_cache, boxes_by_id: dict, center_id: str):
    """返回 (交付时刻偏移 {svc: 相对开工秒数}, 返回时刻偏移, 能耗 kWh)。

    偏移量只依赖架次内容，因此"开工时刻 = 偏移基准 0"即可复用，
    这让调度器能在**不实际占用资源**的前提下试算任意开工时刻的交付时刻。
    """
    from src.physics.energy import Segment, segment_time_s

    n = plan.n_boxes
    t = uav.prepare_time_s + uav.box_load_time_s * n
    offs: dict[str, float] = {}
    prev = center_id
    for svc in plan.stops:
        g = leg_cache.get(prev, svc)
        t += segment_time_s(uav, Segment(g["distance_m"], g["climb_m"], g["descent_m"]))
        kb = len(plan.boxes_by_stop.get(svc, ()))
        t += uav.handover_base_s + uav.handover_per_box_s * kb
        offs[svc] = t
        prev = svc
    g_back = leg_cache.get(plan.stops[-1], center_id)
    t += segment_time_s(
        uav, Segment(g_back["distance_m"], g_back["climb_m"], g_back["descent_m"])
    )
    mass = {s: sum(boxes_by_id[x].mass_kg for x in plan.boxes_by_stop.get(s, ()))
            for s in plan.stops}
    vol = {s: sum(boxes_by_id[x].volume_m3 for x in plan.boxes_by_stop.get(s, ()))
           for s in plan.stops}
    ev = evaluate_sortie(plan, uav, leg_cache, mass, vol, center_id)
    return offs, t, ev


def schedule_dispatch(
    plans: list,
    uav_types: dict,
    leg_cache,
    boxes_by_id: dict,
    pools: dict[str, ResourcePool],
    center_id: str = "O01",
    max_passes: int = 800,
) -> list[ScheduledSortie]:
    """**时限驱动的贪心派发（deadline-aware greedy dispatch）**。

    与 `schedule_ordered` 的区别
    ---------------------------
    固定顺序会在资源延迟后失效：先排的架次把资源占满，
    后面时限更紧的架次只能干等。
    这里改为**逐时刻决策**：

        1. 对每个未调度架次，算出"若此刻用某资源开工"的交付时刻
        2. 计算该架次的**时限违规量**（首批截止权重更高）
        3. 每轮挑选「违规量最大」且资源已就绪的架次优先派发
        4. 若没有任何架次的资源就绪，则把时间推进到最近一个资源就绪时刻

    ★ 这样紧急架次一旦资源可用就会被优先派发，而不是被固定顺序压住。

    资源就绪时刻通过 `ResourcePool` 维护（任务占用 + 充电周转）。
    """
    remaining = [p for p in plans if p.stops]
    out: list[ScheduledSortie] = []
    now = 0.0
    guard = 0

    # ★ 性能：架次几何（交付偏移/返回偏移/能耗）只与架次内容有关，
    #   与资源何时就绪无关，因此**预计算一次**并在各轮复用。
    geom: dict[int, tuple[dict[str, float], float, object]] = {}
    for plan in remaining:
        geom[id(plan)] = _plan_geometry(
            plan, uav_types[plan.type_code], leg_cache, boxes_by_id, center_id
        )

    while remaining and guard < max_passes:
        guard += 1
        ready: list[tuple[float, object, str, str]] = []
        for plan in remaining:
            pool = pools[plan.type_code]
            u = pool.earliest_uav(now)
            b = pool.earliest_battery(now)
            if u is None or b is None:
                continue
            uav_id, t_u = u
            bat_id, t_b = b
            ready.append((max(t_u, t_b), plan, uav_id, bat_id))

        if not ready:
            break

        min_ready = min(r[0] for r in ready)
        if min_ready > now + 1e-9:
            now = min_ready
            continue
        active = [r for r in ready if r[0] <= now + 1e-9]

        best = None
        for _, plan, uav_id, bat_id in active:
            offs, ret_off, ev = geom[id(plan)]
            # ★ 分层优先：
            #   n_fb    —— 本架次**新增**的首批违规箱数（最少者优先，硬优先）
            #   fb_late —— 首批违规的**总时长**（同违规箱数时取更早的）
            #   n_exp   —— 期望送达违规箱数
            #   exp_late—— 期望违规总时长
            #   slack   —— ★ 最小松弛量（详见下）
            #   energy  —— 能耗，最后的确定性 tie-break
            #
            # ★ 为什么必须有 slack（最小松弛优先 / least-laxity-first）：
            #   开工时刻早的时候（尤其 t=0）所有架次都**还没**违规，
            #   n_fb / fb_late / n_exp / exp_late 全是 0，排序实际退化成
            #   "能耗最小者优先" —— 于是稀缺的首批资源被"顺路的小架次"占满，
            #   真正该抢时间的紧时限服务区反而要等下一轮。
            #   实测（旧口径）：t=0 的 8 个机位里有两个给了 S001 的第二个架次，
            #   而 S002/S012/S013 的首批箱被推到 5 800~7 800 s，凭空多出 5 箱首批超时。
            #   松弛量 slack = min(时限 − 交付时刻) 把"离超时还有多久"直接编码进来，
            #   同违规量的架次里**最紧的先派**，这才是时限驱动派发应有的行为。
            n_fb = 0
            fb_late = 0.0
            n_exp = 0
            exp_late = 0.0
            slack = math.inf
            for svc, off in offs.items():
                t_deliver = now + off
                for bid in plan.boxes_by_stop.get(svc, ()):
                    b = boxes_by_id[bid]
                    if b.is_first_batch and b.first_batch_deadline_s is not None:
                        late = t_deliver - b.first_batch_deadline_s
                        slack = min(slack, -late)
                        if late > 0:
                            n_fb += 1
                            fb_late += late
                    if b.expected_time_s is not None:
                        late_e = t_deliver - b.expected_time_s
                        slack = min(slack, -late_e)
                        if late_e > 0:
                            n_exp += 1
                            exp_late += late_e
            key = (n_fb, fb_late, n_exp, exp_late, slack, ev.energy_kwh)
            if best is None or key < best[0]:
                best = (key, plan, uav_id, bat_id, offs, ret_off, ev)

        assert best is not None
        _, plan, uav_id, bat_id, offs, ret_off, ev = best
        end = now + ret_off
        pools[plan.type_code].occupy(uav_id, bat_id, now, end, ev.return_soc)
        k = len(out) + 1
        out.append(
            ScheduledSortie(
                sortie_id=f"T{k:03d}", plan_index=k - 1, uav_id=uav_id,
                type_code=plan.type_code, battery_id=bat_id, stops=plan.stops,
                boxes_by_stop=plan.boxes_by_stop, start_s=now, return_s=end,
                energy_kwh=ev.energy_kwh, soc_end=ev.return_soc,
                delivery_times={s: now + o for s, o in offs.items()},
                n_boxes=plan.n_boxes,
            )
        )
        remaining.remove(plan)

    return sorted(out, key=lambda s: s.start_s)
