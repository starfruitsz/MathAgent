"""问题二：**资源区间调度器**（CP-SAT，实体机/电池不重叠 + 两阶段充电周转 + 逐箱时限）。

模型（与 SKILL 第 2、4 条对应）
-------------------------------
固定给定的 23 个运输架次（组批、机型、能耗、SOC 已定），联合决定
**执行实体机 `u_r`、共享电池 `k_r`、起飞时刻 `t_r`**，最小化最晚返回。

决策变量
    `t_r`            起飞时刻（s，整数网格）
    `u_r ∈ U_{g_r}`  实体机（按机型分池：A→U01–U04、B→U05–U06、C→U07–U08）
    `k_r ∈ K_{g_r}`  共享电池（A:6 组、B:4 组、C:4 组）

约束
    ① 同一实体机的架次区间不重叠：`[t_r, t_r+d_r)`
    ② 同一电池的占用区间不重叠：`[t_r, t_r+d_r+c_r)` —— `c_r` 为该架次返航后按
       **两阶段充电模型**充满所需时间（`charging_time(soc)`），体现“再次投入前须充至 100%”
    ③ 硬时限：首批箱 `t_r + τ_r ≤ F_b`；医疗/全部箱 `t_r + τ_r ≤ D_b`
       （`τ_r` 为该架次的交付偏移）
    ④ 目标：`min max_r (t_r + d_r)`

为什么是 CP-SAT：本问题是**资源受限调度**（区间不重叠 + 时限），
CP-SAT 的可选区间与 `NoOverlap`/`Cumulative` 正好对应，且能给出
“在固定组批下的最优调度”这一**有限范围内的最优性**声明。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ortools.sat.python import cp_model

# 时间网格：0.1 s（SKILL 记载给定方案即用 0.1 s 网格）
TIME_SCALE = 10


@dataclass
class DispatchTask:
    """待调度的一个运输架次。"""

    task_id: str
    type_code: str
    duration_s: float
    """架次历时（起飞到返回）。"""
    soc_end: float
    """返航剩余 SOC（0–1）。"""
    charge_s: float
    """返航后充满所需时间（两阶段充电模型）。"""
    delivery_elapsed_s: float
    """**交付耗时**：交付时刻 = 起飞时刻 + 该值（相对架次起飞的耗时，s）。

    ★ 注意区分两个量：权威数据里的 `delivery` 字段是**相对起飞的耗时**，
      而“绝对交付时刻 = 起飞 + 该耗时”。早先把绝对值当作这里的输入，
      导致时限约束退化成 `起飞 ≤ 时限 − 交付绝对值`（常常为负），
      结果 CP-SAT 把所有架次都排在 t≈0，等价于**取消时限约束**。"""
    hard_deadlines_s: tuple[float, ...] = ()
    """该架次任一货箱的最紧硬时限（首批截止 / 医疗期望）。"""
    soft_deadlines_s: tuple[float, ...] = ()
    """其它货箱的期望时间（尽量满足，不阻断可行性）。"""


@dataclass
class DispatchResult:
    ok: bool
    status: str
    makespan_s: float = 0.0
    assignments: dict[str, dict] = field(default_factory=dict)
    """{task_id: {machine, battery, start_s, return_s}}"""
    violations: list[str] = field(default_factory=list)


def dispatch(
    tasks: list[DispatchTask],
    machines: dict[str, list[str]],
    batteries: dict[str, list[str]],
    horizon_s: float = 12000.0,
    time_limit_s: float = 120.0,
    workers: int = 8,
) -> DispatchResult:
    """在固定组批下求最优调度（最小化最晚返回时刻）。

    参数
    ----
    machines : {机型: [实体机编号, ...]}
    batteries: {机型: [电池编号, ...]}
    """
    m = cp_model.CpModel()
    H = int(horizon_s * TIME_SCALE)

    n = len(tasks)
    starts, mach_vars, bat_vars = [], [], []
    mach_pres: dict[str, list] = {u: [] for ids in machines.values() for u in ids}
    bat_pres: dict[str, list] = {k: [] for ids in batteries.values() for k in ids}

    for i, t in enumerate(tasks):
        dur = max(1, int(round(t.duration_s * TIME_SCALE)))
        st = m.NewIntVar(0, H - dur, f"t{i}")
        starts.append(st)

        ms = []
        for u in machines.get(t.type_code, []):
            b = m.NewBoolVar(f"mu{i}_{u}")
            iv = m.NewOptionalIntervalVar(st, dur, st + dur, b, f"iu{i}_{u}")
            mach_pres[u].append(iv)
            ms.append((u, b, iv))
        if not ms:
            return DispatchResult(False, "NO_MACHINE",
                                  violations=[f"{t.task_id}: 机型 {t.type_code} 无实体机"])
        m.AddExactlyOne(b for _, b, _ in ms)
        mach_vars.append(ms)

        bs = []
        for k in batteries.get(t.type_code, []):
            b = m.NewBoolVar(f"bk{i}_{k}")
            # 电池占用 = 架次 + 充电（充电时长随该架次返航 SOC 而定，故为每架次常量）
            total = dur + max(0, int(round(t.charge_s * TIME_SCALE)))
            iv = m.NewOptionalIntervalVar(st, total, st + total, b, f"ik{i}_{k}")
            bat_pres[k].append(iv)
            bs.append((k, b, iv))
        if not bs:
            return DispatchResult(False, "NO_BATTERY",
                                  violations=[f"{t.task_id}: 机型 {t.type_code} 无电池"])
        m.AddExactlyOne(b for _, b, _ in bs)
        bat_vars.append(bs)

        # 硬时限：t + τ ≤ F
        for dl in t.hard_deadlines_s:
            lim = int(round((dl - t.delivery_elapsed_s) * TIME_SCALE))
            if lim < 0:
                return DispatchResult(
                    False, "DEADLINE_INFEASIBLE",
                    violations=[f"{t.task_id}: 交付偏移 {t.delivery_elapsed_s:.1f}s "
                                f"已超过时限 {dl:.0f}s"])
            m.Add(st <= lim)

    for u, ivs in mach_pres.items():
        if ivs:
            m.AddNoOverlap(ivs)
    for k, ivs in bat_pres.items():
        if ivs:
            m.AddNoOverlap(ivs)

    # 目标：最小化最晚返回
    ends = [starts[i] + max(1, int(round(tasks[i].duration_s * TIME_SCALE)))
            for i in range(n)]
    makespan = m.NewIntVar(0, H, "Cmax")
    m.AddMaxEquality(makespan, ends)
    m.Minimize(makespan)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_s
    solver.parameters.num_search_workers = workers
    solver.parameters.log_search_progress = False
    st = solver.Solve(m)

    if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return DispatchResult(False, solver.StatusName(st),
                              violations=["CP-SAT 未找到可行调度"])

    out: dict[str, dict] = {}
    for i, t in enumerate(tasks):
        u = next(u for u, b, _ in mach_vars[i] if solver.Value(b))
        k = next(k for k, b, _ in bat_vars[i] if solver.Value(b))
        s = solver.Value(starts[i]) / TIME_SCALE
        out[t.task_id] = {
            "machine": u, "battery": k, "start_s": s,
            "return_s": s + t.duration_s,
        }

    note = "OPTIMAL" if st == cp_model.OPTIMAL else "FEASIBLE"
    viol: list[str] = []
    # 复核硬时限
    for i, t in enumerate(tasks):
        act = out[t.task_id]["start_s"] + t.delivery_elapsed_s
        for dl in t.hard_deadlines_s:
            if act > dl + 1e-6:
                viol.append(f"{t.task_id}: 交付 {act:.1f}s > 时限 {dl:.0f}s")
    return DispatchResult(True, note, solver.Value(makespan) / TIME_SCALE,
                          out, viol)
