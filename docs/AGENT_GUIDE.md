# 交接导航（AGENT_GUIDE）— D 题四问：程序 / 图表 / 数据位置 · 答案与思维链 · 初稿使用须知

> **本文件是给"下一个接手 agent"的第一入口。** 目标是让你不必通读全仓库，
> 就能在 5 分钟内知道：**每问的代码在哪、图在哪、数据在哪、结论是什么、思维链怎么走的、哪些坑不能踩。**
>
> 阅读顺序建议：本文件 → `OPS_SPEC_D题.md`（操作规范）→ `docs/PROGRESS.md`（进度）→ 需要细节时再查 `docs/MODEL_NOTES.md`。

---

## 〇、30 秒速览

| 项 | 值 |
|---|---|
| 交付论文 | `paper/山区洪涝灾害下无人机运输与通信协同优化_论文.docx`（51 页 / 24 图 / 28 表 / 96 个可编辑公式） |
| 一键回归 | `python scripts\verify_paper.py`（构建 + 结构自检 + 页数 + 导出 PDF） |
| 测试 | `python -m pytest tests\ -v` → **240 passed** |
| 铁律 | **R1：改完即 commit，commit 即 push**（`.\scripts\commit.ps1 -Scope <...> -Type <...> -Message "..."`） |
| ★ 修正后的四问答案 | Q1 = **18 架次（可证最优）/ 75.07 kWh**；Q2 = **35 架次 / 83.01 kWh / 完工 9.78 h / 准时 38.8%**；Q3 = **30 个中继架次 / 29-29 全程覆盖 / 99.68 kWh**；Q4 = **不存在合法 2/3 组分区** |
| ★ 校验状态 | Q1 达到下界（可证最优）；**Q2/Q3 物理类硬约束违规 0 条**，剩余 49 条全为时限类（已论证为资源约束下物理不可行）；Q3 通信类违规 0 条 |
| ★ 数据一致性 | Q3 的「运输架次数/能耗」必须等于 Q2 的「架次数/总能耗」（Q3 继承 Q2 方案）。已加 `scripts\diag\check_paper_numbers.py` 自动核对论文与 metrics |

---

## 一、★ 初稿（`docs/reference/参考文稿2.pdf`）使用须知

`docs/reference/` 下有**两份第三方同题稿件**，定位不同，**务必分清**：

| 文件 | 页数 | 定位 |
|---|---|---|
| **`参考文稿2.pdf`** | 41 | ★★ **主参考稿（"初稿"）**：**章节骨架、三线表版式、公式呈现、图表与题注同页规则**都值得参考 |
| `示范版本_第三方参考.pdf` | 24 | 二手参考：摘要写法与信息密度可借鉴 |

### 1.1 ✅ 值得参考的部分（放心借鉴）

1. **章节骨架**：引言与问题重述 → 总体分析 → 公共物理模型 → 四问 → 模型检验 → 结论 → 附录。
   本仓库论文的章节结构就是照它搭的（见 `src/report/build_paper.py::build_body`）。
2. **三线表版式**：顶线 + 表头下线 + 底线，**无竖线**；符号表为**双栏**（符号｜说明｜符号｜说明）。
   落地实现：`build_paper.py::_three_line_borders` / `_header_bottom_rule` / `symbol_table()`。
3. **排版规则**：每章起新页；图与表必须跟题注同页。
   落地实现：`Heading 1` 样式 `pageBreakBefore`；图片段落与表题 `keepNext`。
4. **数据组织方式**：把结果整理成"逐架次表 + 逐箱表 + 资源表"的结构，本仓库沿用并细化为交付模板的 6 个 sheet。
5. **公式的"外观标准"**：它展示了一条排版合格的公式该长什么样（上下标、分式、求和号上下限都到位），
   可用作你自查公式是否退化的**视觉基准**。

### 1.2 ❌ 必须修正的部分（**它的公式有大量错误，不要照抄**）

> ⚠️ **这是最重要的一条**：初稿的**公式口径有多处错误**，且**未交代关键建模选择的依据**。
> 若直接沿用其公式，会直接把错误带进论文。下表是本仓库已复核确认的问题与**正确口径**：

| # | 初稿的问题 | 本仓库的正确处理 | 落地位置 |
|:--:|---|---|---|
| 1 | **能量约束结论表述不完整**：写成"能量不约束 A 型" | 正确结论：A 型 **15/15 服务区全部受结构上限 `Q_g` 约束**（即"能量从未成为紧约束"，不是"不约束"）；B 型 14/15、C 型 10/15 | `physics/payload.py`、`outputs/q1/tables/q1_1_max_safe_payload.csv` |
| 2 | **水平巡航能耗口径未交代依据**（且与附件不符） | 题目**未给运输机巡航功率**（只给中继机功率），必须用**由航程反推**：`E_hor = (d / L_g(q)) · E_g^use`，并在论文中写明依据 | **ADR-021**、`physics/energy.py` |
| 3 | **多点架次能耗按"总距离当一段"算**（能量对距离非线性，会显著失真） | 必须**逐段**计算：每段"爬升项 + 该段载荷下的水平能耗"，载荷沿航段递减 | `physics/energy.py::sortie_energy_kwh`、校验器 `legs` 口径 |
| 4 | **时限可行性未做论证**（直接给出"不可行"或干脆不提） | 必须给**定量论证**：8 架机 / 14 组电池 / 40~50 min 充电 ⇒ 前 60 min 最多 8~10 架次，而 9 个服务区要求 60 min 内送达 ⇒ **物理不可行** | `docs/MODEL_NOTES.md` §2.3c、`src/q2_transport_schedule/solver.py` |
| 5 | **交接时间按"总箱数 × 站数"计算**（重复计入） | 正确为 **Σ_站(基础交接 + 每箱 × 该站箱数)**，即逐站累加 | `physics/energy.py`、`src/verify/feasibility.py` |
| 6 | **爬升能耗系数 `0.72` 未说明是什么** | 附件列名是"**爬升能耗效率**"，故按**效率**用：`E_up = m·g·h⁺ / η_up`；下降能耗效率为 0 ⇒ **不单独计下降能耗** | **ADR-020**、`physics/energy.py` |
| 7 | **DEM 当成裸地地形** | 附件 DEM 是 **Copernicus GLO-30 DSM（数字表面模型，含植被/建筑）**，按原样使用、不"去建筑"，用于净空与遮挡判定**偏保守**（更安全） | **ADR-019**、`docs/DATA_NOTES.md` |
| 8 | **FSPL 单位陷阱**（距离用了 m 而非 km） | `L_FSPL = 32.45 + 20log₁₀f(MHz) + 20log₁₀D(**km**)`；内部距离以 m 存储，代入前必须 ÷1000，否则差 60 dB | `comms/link.py::fspl_db` |

> 📌 **给后续 agent 的动作要求**：
> 1. **借鉴格式与数据组织，不借鉴公式**；引用其任何数字前先用本仓库的独立结果核对。
> 2. 若你发现**新的**错误，请**登记到 `docs/reference/README.md` 的「已知错误」表**，避免下一个 agent 再次踩坑。
> 3. 学术红线：`docs/reference/` 的内容**不得**写入本队论文正文（查重会判定违规），只能作模板与自查。

---

## 二、四问的代码 / 图表 / 数据位置（详细索引）

### 2.0 通用目录约定

| 目录 | 内容 | 说明 |
|---|---|---|
| `src/qN_*/` | **各问的 Python 程序** | 每个包内 `run_qN.py` 是该问的**唯一入口** |
| `outputs/qN/` | **各问的原始产出**（metrics / params / 图表 / 校验报告 / 运行日志） | 建模结果的"证据链" |
| `paper/figures/` `paper/tables/` `paper/data/` | **论文里用的图 / 表 / 图表数据源** | 由 `make_figures*.py` 生成 |
| `paper/by_question/{common,q1,q2,q3,q4}/` | ★ **按问题分目录的副本**（figures / tables / data） | 备份用，内容与上两处一致 |
| `data/raw/D题/` | 竞赛官方附件 | ★ **只读**（铁律 R3），禁止修改删除 |
| `data/processed/` | 建模就绪的派生数据 | 由 `q0_data/build_processed.py` 生成 |
| `tests/test_qN.py` | 各问的单元测试 | 改代码必须补测试 |

### 2.0.1 公共层（四问共用，改一处四问都受影响）

| 主题 | 程序 | 说明 |
|---|---|---|
| 附件解析（**唯一**入口） | `src/q0_data/build_processed.py` | 产出 `data/processed/*.csv`；`discover.py` 负责附件清点 |
| 附录 2 物理公式（**唯一**实现） | `src/physics/payload.py`（载荷-航程、最大安全载荷反解）<br>`src/physics/energy.py`（航段时间与能耗）<br>`src/physics/battery.py`（两阶段充电、SOC 周转）<br>`src/physics/leg_cache.py`（航段预计算缓存，**哈希索引**） | ★ 铁律 **R4：口径唯一**，禁止各问各写一套 |
| 几何与 DEM | `src/geo/crs.py`（投影唯一入口）<br>`src/geo/dem.py`（`ElevationProvider` 协议）<br>`src/geo/leg.py`（航段几何） | ★ 关键解耦点：物理/几何只依赖协议，**34 项公式测试不加载 DEM** |
| 附录 3 通信公式（**唯一**实现） | `src/comms/link.py`（FSPL / 链路预算 / 双向门限）<br>`src/comms/los.py`（三维视线遮挡）<br>`src/comms/service.py`（直连/中继/中断三态） | |
| **独立校验器** | `src/verify/feasibility.py` + `_internal.py` | ★ 铁律 **R8**：**不 import 任何 `qN_*`**，从附件与 DEM **重算**全部物理量，18 类约束 + 负样本测试 |

---

### 2.1 问题一：单点往返运输能力与货箱组批

**答案（修正后）**：最优 **18 架次**（全部 C 型机）、总能耗 **75.07 kWh**、累计作业 **33729.5 s**；
**逐服务区达到 Martello–Toth 型解析下界 ⇒ 架次数维度可证最优**。

| 类别 | 位置 |
|---|---|
| **程序入口** | `src/q1_payload_grouping/run_q1.py` |
| 程序模块 | `grouping.py`（装箱：FFD + `_pack_area`、`sortie_lower_bound`、`pareto_frontier`）<br>`sensitivity.py`（ρ_g 扫描、临界值、载荷曲线） |
| 原始产出 | `outputs/q1/metrics.json`、`params.json`、`run.log`、`run_log.json` |
| 原始图 | `outputs/q1/figures/q1_payload_vs_rho.png`、`q1_rho_sensitivity.png`、`q1_strategy_comparison.png` |
| 原始表 | `outputs/q1/tables/`：`q1_1_max_safe_payload.csv`（45 组载荷）、`q1_2_groups_by_service.csv`（组批方案）、`q1_3_pareto_frontier.csv`、`q1_3_sortie_lower_bounds.csv`、`q1_3_strategy_comparison.csv`、`q1_4_rho_sweep.csv`、`q1_4_critical_rho.csv`、`q1_4_payload_vs_rho.csv` |
| **论文图** | `paper/figures/`：`f04_q1_payload.png`（图 9 载荷热力图）、`f05_q1_groups.png`（图 10 组批构成）、`f06_q1_strategy.png`、`f07_q1_rho.png`（图 12 ρ_g 敏感性） |
| **论文表** | `paper/tables/`：`t_q1_payload.csv`（表 9）、`t_q1_groups.csv`（表 10）、`t_q1_strategy.csv`（表 11）、`t_q1_lowerbound.csv`（表 12）、`t_q1_rho_sweep.csv`（表 13） |
| 分目录备份 | `paper/by_question/q1/figures|tables|data/` |
| 测试 | `tests/test_q1.py` |

**思维链（可复用的推理路径）**

1. **拆两层**：问题一不含实体机与电池调度 ⇒ 先解"单点往返能带多少"（载荷），再解"怎么把 80 箱装进最少架次"（装箱）。
2. **载荷层**：`L_g(q) = L_g0 − (L_g0 − L_gF)·(q/Q_g)^{3/2}` 单调不增；往返能耗约束 `E_g^T(q) ≤ (1−ρ_g)·E_g^use`。
   `(q/Q_g)^{3/2}` **无初等反函数** ⇒ 必须**数值反解**（Brent 法，`[0, Q_g]` 上单调）。
   安全载荷 = `min(能量反解值, Q_g, 体积瓶颈对应质量)`。
   → **结论**：A 型 15/15 受**结构**约束（恒 25 kg），B 型 14/15，C 型仅 10/15（远距离时能量才成紧约束）。
3. **装箱层**：货箱不可拆 + 恰用一次 + 质量/体积/能量三约束 ⇒ **质量—体积二维装箱**。
   用 FFD（按体积降序，体积是本题主要瓶颈）构造。
4. **最优性**：推导 **Martello–Toth 型解析下界**（按质量、体积分别用最佳机型容量估架次数，取大者）。
   启发式结果**逐服务区等于下界** ⇒ 架次数维度**可证最优**（这是本题最有力的"质证"）。
5. **敏感性**：ρ_g 从 0 扫到 0.50（步长 0.025），每点重算载荷并重跑组批。
   → ρ_g 0.20→0.35 使架次 18→25（+39%）、能耗 75.07→106.60 kWh；**ρ_g > 0.40 时部分高海拔服务区（S003、S014）即使空载也无法返回 ⇒ 无可行解**；附件取值 0.20 恰在效率最优区间。

---

### 2.2 问题二：异构无人机多点多架次运输调度

**答案（已修正）**：**35 架次**（全部 B 型）、总能耗 **83.01 kWh**、完工时间 **9.78 h（35219 s）**、
期望送达准时率 **38.8%**；首批违规 23 箱、期望送达违规 49 箱。

★ **独立校验器报告 `ok=false`、49 条违规，但全部是时限类**（26 条期望送达 + 23 条首批超时），
**物理/资源类违规 0 条**。时限类违规不是缺陷，而是本文第 5.4 节论证的**资源约束下物理不可行**的必然结果。

> ✅ **已修复的历史缺陷（务必不要回退）**：曾出现"某个架次给 B 型机装了 235 kg（上限 30 kg）
> 却被静默输出"的问题 —— 表现为校验器报 `[超出能量预算] 重算 10.0383 kWh > 预算 3.2000 kWh`、
> `[返航SOC低于下限] SOC 0.0000`。该阶段（`construct`/`local_search`/`schedule`）现已逐层复核，
> 三个阶段的超载架次数均为 0。
>
> ★ **新增硬约束闸门**（`run_q2.py` / `run_q3.py`）：把 18 类违规分为两类 ——
> **物理/资源/通信类 16 类**（超载、超体积、超能量、SOC 不足、资源冲突、时长不足、货箱缺失/重复…）
> 一律 `raise RuntimeError` **中止产出**；**时限类 2 类**（首批超时、期望送达超时）放行并写日志。
> 这样"方案不可行却被静默发布"不可能再发生。

| 类别 | 位置 |
|---|---|
| **程序入口** | `src/q2_transport_schedule/run_q2.py`（含硬约束闸门） |
| 程序模块 | `models.py`（多点串飞模型：`SortiePlan`/`evaluate_sortie`/`best_stop_order`）<br>`schedule.py`（资源池 `ResourcePool`、两阶段充电周转、`schedule_dispatch` 时限驱动派发）<br>`solver.py`（构造 + 局部搜索 + 字典序目标） |
| 原始产出 | `outputs/q2/metrics.json`、`params.json`、`feasibility.json`（49 条，**全为时限类**）、`run.log` |
| 原始图 | `outputs/q2/figures/q2_gantt.png`、`q2_timeliness.png` |
| 原始表 | `outputs/q2/tables/`：`q2_运输架次.csv`、`q2_逐箱交付.csv`、`q2_时限达成.csv`、`q2_资源使用_无人机.csv`、`q2_资源使用_电池.csv` |
| **论文图** | `paper/figures/`：`f08_q2_gantt.png`（图 13 甘特图）、`f09_q2_timeliness.png`（图 15 时限达成）、`f10_q2_resources.png`（图 14 资源使用） |
| **论文表** | `paper/tables/`：`t_q2_sorties.csv`（表 15）、`t_q2_uav_use.csv`（表 16）、`t_q2_battery_count.csv`（表 17）、`t_q2_timeliness.csv`（表 18） |
| 分目录备份 | `paper/by_question/q2/...` |
| 测试 | `tests/test_q2.py` |

**思维链**

1. **新增三类耦合**：① 多点串飞 ⇒ 载荷**逐段递减**；② 机型异构 ⇒ 容量/速度/能耗不同；③ 共享电池 + 两阶段充电 ⇒ 资源周转成为瓶颈。
2. **多点串飞模型**：设访问顺序 `(S_a, S_b, …)`，第 m 段机载荷 = **尚未投送货箱之和**。
   前缀可行性：`∀m: Σ_{k≥m} m_k ≤ Q_g` 且 `Σ_{k≥m} v_k ≤ V_g`（下标是"从第 m 站起仍留在机上的货"）。
   架次能耗 = **逐段求和** `Σ_m E_g(seg_m, q_m)`（★ 不能拿总距离当一段，见初稿错误 #3）。
   架次时间 `t_p = t_prep + n_box·t_load + Σ_m t_g(seg_m) + Σ_站(t_h0 + k_s·t_h1)`（★ 交接时间逐站累加，见初稿错误 #5）。
3. **求解框架"构造—改进—调度—校验"**：
   - 构造：货箱按"首批优先 → 期望送达升序 → 应急优先系数降序 → 体积降序"排序，并入已有架次或新开架次；
   - 选序：站点数 ≤6 全排列，>6 最近邻 + 2-opt；
   - 局部搜索：搬箱 / 合并，目标为 (及时性惩罚, 架次数, 能耗) **字典序**；
   - 调度：**时限驱动贪心派发** —— 每决策时刻在"资源已就绪"的未调度架次里选"新增首批违规最少 → 首批迟到最少 → 期望违规最少"者。**动机**：固定顺序调度在资源延迟后失效，逐时刻按违规量择优能把紧急架次塞进刚释放的资源。
4. **不可行性论证（本题最关键的结论）**：8 架实体机、14 组电池、单次充电 40~50 min
   ⇒ 前 60 min 最多完成 **8~10 个架次**；而 **9 个服务区要求 60 min 内送达**
   ⇒ **首批保障时限是资源约束下的物理不可行**，不是算法不够好。论文要写**定量论证**而非归因于启发式。

---

### 2.3 问题三：通信约束下的运输与中继联合调度

**答案（修正后）**：运输 **35 架次**（沿用问题二方案）、中继 **30 架次**；
**29/29 需保障架次实现全程连续通信覆盖（100%）**；
运输能耗 83.01 kWh + 中继能耗 16.67 kWh = **总计 99.68 kWh**；联合完工 **9.91 h**。
实测 **29/35 架次存在直连中断**（平均中断占比 31.0%）⇒ **中继是必需项**。
校验器 `ok=false`、49 条违规 —— **全部为时限类**（26 条期望送达 + 23 条首批超时，均由 Q2 继承），
**通信类与能量类违规 0 条**；`run_q3.py` 亦已加硬约束闸门。

| 类别 | 位置 |
|---|---|
| **程序入口** | `src/q3_comms_relay/run_q3.py` |
| 程序模块 | `coverage.py`（轨迹逐时刻采样、悬停候选点生成、时空覆盖判定）<br>`relay.py`（中继架次几何与能耗 `RelaySortie`/`evaluate_relay_sortie`） |
| 原始产出 | `outputs/q3/metrics.json`、`params.json`、`feasibility.json`（49 条，均时限类）、`run.log` |
| 原始图 | `outputs/q3/figures/q3_relay_positions.png`、`q3_gantt.png` |
| 原始表 | `outputs/q3/tables/`：`q3_直连状态诊断.csv`、`q3_中继架次.csv`、`q3_中继选址.csv`、`q3_通信保障.csv`、`q3_运输架次.csv` |
| **论文图** | `paper/figures/`：`f11_q3_diagnosis.png`（图 16 直连诊断）、`f12_q3_relay_map.png`（图 17 中继悬停点）、`f13_q3_coverage.png`（图 18 选址特征）、`f14_q3_joint_gantt.png`（图 19 联合时间线） |
| **论文表** | `paper/tables/`：`t_q3_diagnosis.csv`（表 19）、`t_q3_relay_sorties.csv`（表 20）、`t_q3_siting.csv`、`t_q3_summary.csv` |
| 分目录备份 | `paper/by_question/q3/...` |
| 测试 | `tests/test_q3.py` |

**思维链**

1. **先诊断，再设计**：对问题二的 35 个架次做**直连可用性诊断** ⇒ 29 个存在中断 ⇒ 证明"中继不是可选项"。
2. **通信判定三要素**：地形遮挡（沿视线水平投影采样，比地面高程与视线插值高度；遮挡**只附加 10 dB**，不直接判中断）
   + 传播损耗（FSPL，★ 距离单位必须是 **km**）
   + **双向链路预算**（控制与回传都要保障 ⇒ 门限取两方向**较小**值）。
   三态优先级：**直连 > 中继（接入段与回传段同时可用）> 中断**；**不允许多跳**。
3. **关键定量事实**：门限 直连 122 dB / 中继接入 116 dB / 中继回传 126 dB。
   接入段门限**比直连还低 6 dB** ⇒ 中继必须**靠近运输机**（≤6.27 km），而回传段很宽（可达 19.83 km）
   ⇒ **中继悬停可行域是"贴近作业空域"而非"贴近网关"**。这条结论直接指导选址，也解释了为什么中继位置经度集中在 109.20~109.27°E。
4. **为什么必须逐时刻采样轨迹**：只查服务区一个点或航段端点会漏掉"中途被山体遮挡"的时段。
   采样步长 `sample_dt_s = 5.0`（第 8 章有步长敏感性分析）。
5. **降维技巧（可复用）**：中继选址本是连续三维变量，逐时刻独立选址会退化成难解的连续最优控制。
   改用**可验证的充分条件**：对某架次，若存在**一个**悬停点 P 使"轨迹上每一时刻都满足 直连可用 ∨（接入(P) 可用 ∧ 回传(P) 可用）"，
   则该架次由一架中继全程保障即可。若单点覆盖不了全程 ⇒ 退化为**按时段分段接力**（题目允许不同时刻由不同中继承担）。
6. **实现**：DEM 范围内、服务区凸包外扩 3 km 生成 **800 m 网格**共 **481 个**悬停候选点；对每个需保障架次搜"能覆盖全部中断样本且返航 SOC 达标"的最低能耗点。

---

### 2.4 问题四：救援任务分区与资源配置优化

**答案（修正后）**：★ **在"保持问题三运输安排不变"的前提下，不存在合法的 2 组或 3 组分区** ——
问题三的 **21 个多点架次**把 15 个服务区串成**单一连通分量**，唯一合法分区是"全部服务区一组"。
给出 **3 个桥接架次**（T010: S001→S014、T017: S006→S003、T027: S010→S007）与最小改动方案：
**拆 1 个架次得 2 组、拆 2 个得 3 组**。资源总规模 K=1/2/3 = **13/17/21（台·组）**，
组间不均衡度 0 / 1.7718 / 2.4707 ⇒ **分区既不省资源也不改善均衡**。

| 类别 | 位置 |
|---|---|
| **程序入口** | `src/q4_partitioning/run_q4.py` |
| 程序模块 | `partition.py`（图与**连通分量/原子单元** `atomic_units`、桥接架次 `bridge_sorties`、RGS 枚举 `enumerate_partitions`、最小改动 `minimal_edits_for_partition`、资源核算 `group_resources`/`batteries_required`/`_parallel_peak`、`select_best_partition`） |
| 原始产出 | `outputs/q4/metrics.json`、`params.json`、`run.log`（**无 feasibility.json**：Q4 不产出运输方案，只做分区与资源核算） |
| 原始图 | `outputs/q4/figures/q4_partition_map.png`、`q4_plan_comparison.png` |
| 原始表 | `outputs/q4/tables/`：`q4_桥接架次.csv`、`q4_原子单元.csv`、`q4_方案对比.csv`、`q4_逐组明细.csv`、`q4_资源缺口.csv`、`q4_分区配置.csv` |
| **论文图** | `paper/figures/`：`f15_q4_graph.png`（图 20 原子单元分析）、`f16_q4_compare.png`（图 21 方案对比）、`f17_q4_detail.png`（图 22 逐组配置） |
| **论文表** | `paper/tables/`：`t_q4_bridge.csv`（表 21）、`t_q4_units.csv`（表 22）、`t_q4_compare.csv`（表 23）、`t_q4_gap.csv`（表 24）、`t_q4_group.csv`（表 25） |
| 分目录备份 | `paper/by_question/q4/...` |
| 测试 | `tests/test_q4.py` |

**思维链**

1. **识别硬规则**：题目规定"**同一运输架次涉及的服务区必须划入同一组**" ⇒ 服务区之间产生**等价关系**
   ⇒ 问题自然建模为**图 + 连通分量**，每个连通分量是一个**不可拆原子单元**。
2. **求连通分量**：对问题三方案里涉及服务区的 35 个架次构图，其中 **21 个是多点架次**（访问 ≥2 个服务区）
   ⇒ 这些架次把服务区连起来 ⇒ 最终 **1 个连通分量**。
3. **得出不可行性（本题核心结论）**：K 个组要求把图切成 K 个分量 ⇒ 但只有 1 个分量可切
   ⇒ **K=2、K=3 均无合法解**（在"保持问题三安排不变"前提下）。
   ★ **不伪造违反约束的分区**：论文给的是**严格论证 + 桥接定位 + 最小改动方案**，而不是硬凑两个组。
4. **找桥接架次**：逐条试"移除该架次后分量数是否增加" ⇒ 得到 **3 个桥接架次**（T010/T017/T027）。
   最少要拆 **1 个**才能得 2 组、拆 **2 个**才能得 3 组（`minimal_edits_for_partition`）。
5. **资源核算（组内独立、不得跨组调配）**：
   - 运输机/电池：按组内架次的**时间区间求并行峰值** `_parallel_peak`（★ 注意**首尾相接不算重叠**，
     排序键要用 `(t, delta)` 让 −1 先于 +1，否则会虚报"缺 1 架"）；
   - 电池组数 `batteries_required`：考虑充电周转；
   - 中继机/能源组件：按组内中继架次同法核算。
6. **对比与结论**：K=1/2/3 ⇒ 资源总量 13/17/21、不均衡度 0/1.77/2.47、最大组工作量 18.91/18.41/17.72 h
   ⇒ **分区不省资源、也不改善均衡、还降低单组工作量集中度**，是一条**有工程指导意义的负面结论**。
   K=1 唯一缺口：1 组 B 型备用电池（见 `t_q4_gap.csv`）。

---

## 三、横切主题（不属于某一问，但必须一起看）

| 主题 | 程序 | 论文图表 |
|---|---|---|
| 数据特征与地形 | `src/report/make_figures.py`（f01–f03、f24）、`q0_data/` | 图 1–图 5、表 1–表 6（`t_nodes`/`t_box_by_type`/`t_box_by_service`/`t_uav_params`/`t_battery_inventory`/`t_uav_fleet`） |
| 公共物理计算器与链路预算 | `src/report/make_figures2.py`（f18–f20）、`physics/`、`comms/` | 图 6 统一计算器、图 7 飞行剖面、图 8 链路预算、表 7 符号表、表 8 链路门限 |
| 独立校验器 | `src/verify/feasibility.py` | 图 21 校验器架构（`f21_verifier.png`） |
| 敏感性分析 | `src/report/make_figures2.py`（f22）、`q1_payload_grouping/sensitivity.py` | 图 22、表 26（`t_sensitivity.csv`） |
| 四问指标汇总 | — | 表 B1（`t_all_metrics.csv`） |
| 图表清单 | `paper/chart_manifest.csv` | 24 图 + 32 表的编号/标题/章节/文件路径 |
| 备份清单 | `paper/backup_manifest.csv` | 分目录备份统计 |

---

## 四、复现命令（端到端）

```powershell
# 0) 环境
python scripts\check_env.py                      # → outputs/env_report.json，须 status: ok

# 1) 数据层（附件只读，产出 data/processed/）
python -m src.q0_data.discover                   # 附件清点
python -m src.q0_data.build_processed            # 解析附件 → data/processed/*.csv
python -m src.physics.leg_cache                  # 240 条有序航段缓存（首次约 0.2 s）

# 2) 四问（按依赖顺序：Q1 → Q2 → Q3 → Q4）
python -m src.q1_payload_grouping.run_q1         # 实测 0.76 s
python -m src.q2_transport_schedule.run_q2       # ★ 实测 3092.6 s（≈52 min，局部搜索最耗时）
python -m src.q3_comms_relay.run_q3              # 实测 84.4 s（481 个悬停候选点 × 逐时刻采样）
python -m src.q4_partitioning.run_q4             # 实测 0.44 s

# 3) 论文
python -m src.report.make_figures                # 基础图表 17 图 / 21 表
python -m src.report.make_figures2               # 补充图表 + 按问题分目录备份 → 24 图 / 32 表
python -m src.report.build_paper                 # 装配 Word（公式 = Word 原生 OMML 对象）
python scripts\verify_paper.py                   # ★ 一键回归：构建 + 结构自检 + 页数 + PDF

# 4) 测试
python -m pytest tests\ -v                       # 227 passed
```

---

## 五、给后续 agent 的优先级建议

| 优先级 | 事项 | 说明 |
|:--:|---|---|
| ~~P0~~ | ~~修 Q2 的物理硬约束违规~~ | ✅ **已完成**：Q2/Q3 物理类违规 0 条；并加硬约束闸门（16 类物理/资源/通信违规一律中止产出）。见 §2.2 |
| **P1** | 改 Q2 后**必须重跑 Q3 → Q4 并同步论文** | Q3/Q4 继承 Q2 的方案，链式依赖。跑完用 `python scripts\diag\check_paper_numbers.py` 核对论文数字 |
| **P2** | 论文页数 | 当前 **51 页**（要求 50~100），余量很小；删改内容后必须跑 `verify_paper.py` 复核 |
| **P3** | 提取 `镇龙乡地理空间数据说明.pdf` 正文 | 确认是否还有额外口径约定（OPEN-013） |
| — | 每完成一步 | 按铁律 **R1** 立即 `commit` + `push` |

**改代码时的硬约束**

1. **R3**：`data/raw/**` 只读。
2. **R4**：附录 2/3 的公式只在 `src/physics/`、`src/comms/` 实现**一次**，四问共用；改公式必须同步补 `tests/test_physics.py`。
3. **R8**：方案必须过独立校验器；**校验器不得 import 任何 `qN_*`**。
4. **R7**：随机过程固定 `SEED = 42`。
5. 被推翻的方案归档到 `docs/legacy_D题/` 并写明**为何弃用**，不要就地删除。

---

## 六、变更记录

| 版本 | 变更 |
|---|---|
| **v1.0** | 新建：① 四问「程序 / 图表 / 数据」详细索引 + 复现命令；② 初稿（`参考文稿2.pdf`）使用须知与 8 项必须修正的公式错误；③ 四问答案与完整思维链；④ 后续 agent 优先级建议 |
