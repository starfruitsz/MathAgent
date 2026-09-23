"""电池 SOC 与两阶段充电周转（题目附录 2 的**唯一实现**，铁律 R4）。

两阶段等效充电模型（题目原文）：

                ⎧ T_full · [ 0.65 · (0.90 − s) / 0.90 + 0.35 ],   0 ≤ s < 0.90
    t_chg(s) =  ⎨
                ⎩ T_full · 0.35 · (1 − s) / 0.10,                0.90 ≤ s ≤ 1

自检点（由 tests/test_physics.py 锁死）：
    t_chg(0)   = T_full            （0% 起充满需一个完整充电时间）
    t_chg(0.9) = T_full · 0.35     （两段在此连续）
    t_chg(1)   = 0

资源规则（题目附录 2）：
    - 运输共享电池与中继能源组件都是**独立资源**，各自记录 SOC
    - 初始 SOC = 100%
    - **同一资源的任务占用与充电时段不得重叠**；不同资源可并行充电
    - 同一机型的共享电池可在该机型不同实体无人机间调度；**不同机型不可混用**
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.common.config import (
    CHG_FAST_FRACTION,
    CHG_FAST_SOC_BOUNDARY,
    CHG_SLOW_FRACTION,
    SOC_INITIAL,
    SOC_TOL,
)


def charging_time(soc: float, t_full_s: float) -> float:
    """从 SOC = s 充至 100% 所需的等效时间（s）。

    参数
    ----
    soc : 任务结束时的剩余 SOC ∈ [0, 1]
    t_full_s : 等效完全充电时间 T_full（s）
    """
    if not -SOC_TOL <= soc <= 1.0 + SOC_TOL:
        raise ValueError(f"SOC 必须在 [0, 1] 内，收到 {soc}")
    if t_full_s <= 0:
        raise ValueError(f"等效完全充电时间必须为正，收到 {t_full_s}")
    s = min(max(soc, 0.0), 1.0)

    if s < CHG_FAST_SOC_BOUNDARY:
        # 快速阶段：0% → 90% 占 T_full 的 65%
        return t_full_s * (
            CHG_FAST_FRACTION * (CHG_FAST_SOC_BOUNDARY - s) / CHG_FAST_SOC_BOUNDARY
            + CHG_SLOW_FRACTION
        )
    # 慢速阶段：90% → 100% 占 T_full 的 35%
    return t_full_s * CHG_SLOW_FRACTION * (1.0 - s) / (1.0 - CHG_FAST_SOC_BOUNDARY)


def soc_after_energy(energy_used_kwh: float, energy_total_kwh: float) -> float:
    """由已用能量反推剩余 SOC（0~1）。"""
    if energy_total_kwh <= 0:
        raise ValueError("总能量必须为正")
    if energy_used_kwh < 0:
        raise ValueError("已用能量不得为负")
    return max(0.0, 1.0 - energy_used_kwh / energy_total_kwh)


def energy_from_soc(soc: float, energy_total_kwh: float) -> float:
    """由 SOC 反推可用能量（kWh）。"""
    return soc * energy_total_kwh


@dataclass(frozen=True)
class ResourceTask:
    """某能源资源（一组电池 / 一个能源组件）的一次占用记录。"""

    start_s: float
    end_s: float
    soc_end: float
    """任务结束时的剩余 SOC（0~1）。"""

    def __post_init__(self) -> None:
        if self.end_s < self.start_s:
            raise ValueError(f"任务结束时刻 {self.end_s} 早于开始时刻 {self.start_s}")
        if not -SOC_TOL <= self.soc_end <= 1.0 + SOC_TOL:
            raise ValueError(f"SOC 必须在 [0, 1] 内，收到 {self.soc_end}")

    @property
    def duration_s(self) -> float:
        return self.end_s - self.start_s


@dataclass
class SocTimeline:
    """单个能源资源的时间线：记录其历次任务占用与充电窗口。

    负责**占用与充电不重叠**这条硬约束的检查（题目附录 2）。
    """

    t_full_s: float
    label: str = ""
    tasks: list[ResourceTask] = field(default_factory=list)
    _charge_windows: list[tuple[float, float]] = field(default_factory=list, repr=False)

    def add_task(self, start_s: float, end_s: float, soc_end: float) -> ResourceTask:
        """登记一次任务占用，并自动插入随后的充电窗口。

        若与已登记的占用或充电窗口重叠 → 抛 ValueError。
        """
        task = ResourceTask(start_s, end_s, soc_end)

        # 充电窗口：任务结束后立即充到 100%
        charge_start = end_s
        charge_end = end_s + charging_time(soc_end, self.t_full_s)

        for other in self.tasks:
            if task.start_s < other.end_s - SOC_TOL and other.start_s < task.end_s - SOC_TOL:
                raise ValueError(
                    f"[{self.label}] 任务占用时段 ({task.start_s}, {task.end_s}) "
                    f"与已有占用 ({other.start_s}, {other.end_s}) 重叠"
                )
        for cs, ce in self._charge_windows:
            if task.start_s < ce - SOC_TOL and cs < task.end_s - SOC_TOL:
                raise ValueError(
                    f"[{self.label}] 任务占用时段 ({task.start_s}, {task.end_s}) "
                    f"与充电窗口 ({cs:.1f}, {ce:.1f}) 重叠"
                )

        self.tasks.append(task)
        self._charge_windows.append((charge_start, charge_end))
        return task

    @property
    def busy_until_s(self) -> float:
        """该资源最早可再次投入任务的时刻（最后一次任务结束 + 充电完成）。"""
        if not self.tasks:
            return 0.0
        return max(ce for _, ce in self._charge_windows)

    @property
    def overlaps_task(self) -> bool:
        """占用与充电窗口是否存在自重叠（健康检查）。"""
        windows = [(t.start_s, t.end_s) for t in self.tasks] + self._charge_windows
        windows.sort()
        return any(
            b[0] < a[1] - SOC_TOL for a, b in zip(windows, windows[1:])
        )


def turnaround_feasible(timeline: SocTimeline, next_start_s: float) -> bool:
    """给定时间线，判断该资源能否在 next_start_s 时刻再次投入任务。

    要求：next_start_s ≥ 该资源「最后一次任务结束 + 充电至 100%」的时刻。
    """
    return next_start_s >= timeline.busy_until_s - SOC_TOL


def initial_soc() -> float:
    """初始 SOC（题目规定 100%）。"""
    return SOC_INITIAL
