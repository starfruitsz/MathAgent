# MathAgent

2026 年中国研究生数学建模竞赛 **D 题**（山区洪涝灾害下无人机运输与通信协同优化）的建模工作仓库。

> **归档约定**：`docs/legacy_D题/` 存放**被推翻或已废弃**的 D 题方案（旧模型形式、试过但不 work 的算法），
> 只读保留、不再维护，目的是留下"为什么否掉某个方案"的轨迹。
> `docs/reference/` 存放**第三方同题解答**（非本队产出），仅作风格模板与交叉验证，
> **不得引用其文字或数字**（详见该目录 README）。

---

## 一、当前状态

| 阶段 | 状态 | 关键产出 |
|---|:--:|---|
| **P0** 数据发现 + 航段预计算 | ✅ 完成 | `outputs/data_inventory.json`、`data/processed/leg_cache.parquet`（240 条有序航段） |
| **P0b** 物理 / 地理 / 通信 / 校验器 | ✅ 完成 | `src/physics/`、`src/geo/`、`src/comms/`、`src/verify/` |
| **P1 / Q1** 载荷能力与货箱组批 | ✅ 完成 | 18 架次（**达到下界，可证最优**）、ρ_g 敏感性、Pareto 前沿 |
| **P2 / Q2** 异构多点多架次调度 | ✅ 完成 | 35 架次 / 83.01 kWh / 完工 587 min；硬约束全部通过 |
| **P3 / Q3** 通信约束下运输与中继联合调度 | ✅ 完成 | 30 个中继架次 / **29-29 全程通信覆盖** / 总能耗 99.68 kWh |
| **P4 / Q4** 任务分区与资源配置 | ✅ 完成 | ★ **按规则不存在合法 2/3 组分区**；给出桥接架次与最小改动方案 |
| **P5** 论文与 Word 生成 | ⬜ 待做 | 以 `docs/reference/` 的第三方版本为**格式模板** |

**环境**：Python 3.13.7 / Windows 11 / 24 核；依赖已锁定（`requirements.txt`），`check_env.py` 返回 `status: ok`。
**测试**：`227 passed`。

---

## 二、快速开始

```powershell
# 1. 同步仓库
git pull --rebase origin main

# 2. 环境（本机已装好，可直接跳到第 3 步）
pip install -r requirements.txt
python scripts\check_env.py

# 3. 读规范（必做）
#    OPS_SPEC_D题.md        —— 唯一操作规范
#    docs/PROGRESS.md       —— 当前进度与阻塞项
#    docs/IMPLEMENTATION_PLAN.md —— 分层结构与实现顺序
```

### 完整复现（端到端）

```powershell
python -m src.q0_data.discover            # 附件清点
python -m src.q0_data.build_processed     # → data/processed/*.csv
python -m src.physics.leg_cache           # → leg_cache.parquet（首次约 0.1 s）
python -m src.q1_payload_grouping.run_q1  # Q1
python -m src.q2_transport_schedule.run_q2 # Q2
python -m src.q3_comms_relay.run_q3       # Q3
python -m src.q4_partitioning.run_q4      # Q4
python -m pytest tests\ -v
```

---

## 三、⚠️ 铁律（每次操作前必读）

> ## 每次更改代码必须提交仓库
>
> 改完即 `commit`，`commit` 即 `push`。禁止累积多次改动后一次性提交。
> 本仓库的规范文件（`OPS_SPEC_D题.md` 等 `*.md`）修改后同样**必须提交并推送**。

```powershell
.\scripts\commit.ps1 -Scope q3 -Type feat -Message "中继悬停候选点生成"
```

收工自检（两条输出都必须为空）：

```powershell
git status --porcelain
git log origin/main..HEAD --oneline
```

其余铁律见 **`OPS_SPEC_D题.md`** 第 0 节。最容易踩的三条：

| 编号 | 内容 |
|:--:|---|
| **R4** | **物理口径唯一**：附录 2/3 的时间、能耗、充电、链路公式只在 `src/physics/`、`src/comms/` 实现一次，四问共用 |
| **R8** | **方案必须通过独立校验器**：校验器不 import 任何 `qN_*`，且有**负样本测试** |
| **R2** | 本规范与文档修改后同样必须提交推送 |

---

## 四、仓库结构

```
MathAgent/
├── OPS_SPEC_D题.md              ★ 唯一操作规范（先读这个）
├── requirements.txt / requirements.lock.txt
├── .gitignore / .gitattributes
├── data/
│   ├── raw/D题/                 ★ 只读★ 竞赛官方附件（不入库）
│   └── processed/               建模就绪派生数据（含 leg_cache.parquet）
├── src/
│   ├── common/                  配置 / IO / 指标
│   ├── q0_data/                 附件解析（discover / build_processed）
│   ├── physics/                 ★ 附录2 唯一实现
│   │   ├── payload.py           载荷-航程、最大安全载荷反解
│   │   ├── energy.py            航段能耗与时间
│   │   ├── battery.py           两阶段充电与 SOC 周转
│   │   └── leg_cache.py         航段预计算缓存（哈希索引）
│   ├── geo/                     ★ DEM 与几何
│   │   ├── crs.py               坐标投影（ADR-011 唯一入口）
│   │   ├── dem.py               DEM 采样 + ElevationProvider 协议
│   │   └── leg.py               航段几何（不直接读 DEM）
│   ├── comms/                   ★ 附录3 唯一实现
│   │   ├── link.py              FSPL / 链路预算 / 双向门限
│   │   ├── los.py               地形遮挡判定
│   │   └── service.py           直连 / 中继 / 中断 三态判定
│   ├── verify/                  ★ 独立可行性校验器（18 类 + 负样本测试）
│   ├── q1_payload_grouping/     Q1：载荷表 / 装箱 / Pareto / rho_g 敏感性
│   ├── q2_transport_schedule/   Q2：多点串飞 / 资源周转 / 时限驱动派发
│   ├── q3_comms_relay/          Q3：中继选址 / 轨迹覆盖 / 联合调度
│   ├── q4_partitioning/         Q4：分区（原子单元/连通分量）与资源核算
│   └── report/                  论文表格与图
├── outputs/                     ★ 证据链：metrics / params / 图表 / 校验报告
│   ├── q1/  q2/                 每问含 metrics.json、params.json、tables/、figures/
│   └── p0_inspect/  p0_smoke/   附件勘察与冒烟验证记录
├── scripts/
│   ├── commit.ps1               ★ 一键提交并推送（含收工自检）
│   ├── check_env.py             环境自检
│   ├── inspect_attachments.py   附件结构勘察
│   ├── smoke_physics_real_data.py / smoke_comms_real_data.py / smoke_verify_real_data.py
│   └── run_all.ps1              端到端复现
├── docs/
│   ├── PROGRESS.md              ★ 进度看板
│   ├── DATA_NOTES.md            ★ 附件字段结构实测记录
│   ├── MODEL_NOTES.md           ★ 各问数学形式与推导
│   ├── IMPLEMENTATION_PLAN.md   五层解耦结构与实现顺序
│   ├── DECISIONS.md             决策记录（ADR-001~021）
│   ├── TOOLS.md                 外部工具来源/版本/许可证
│   ├── reference/               第三方同题解答（仅作模板/交叉验证）
│   └── legacy_D题/              废弃的 D 题方案归档（只读）
└── tests/                       227 项测试（物理公式逐条锁死 + 负样本）
```

---

## 五、分层解耦架构

严格单向依赖，**下层不得反向依赖上层**：

```
L4 问题层   q1 / q2 / q3 / q4      只做决策，不碰公式
L3 领域层   physics/ comms/ verify/
L2 几何层   geo/leg.py             通过 ElevationProvider 协议拿高程
L1 基础层   geo/crs.py  geo/dem.py 投影与栅格采样各只有一处实现
L0 常量层   common/config.py
```

★ **关键解耦点 `ElevationProvider` 协议**：物理与几何层只依赖协议，
因此 **34 项物理公式测试完全不加载 DEM**（用解析高程），只有 3 项对照测试读真实附件。

---

## 六、四问主线与关键结论

| 阶段 | 内容 | 关键结论 |
|---|---|---|
| **Q1** | 单点往返最大安全载荷 + 货箱组批 | A 型 **15/15**、B 型 14/15 全区受**结构载重**约束，能量仅为次要约束；最优 **18 架次**（逐区达到下界）；ρ_g 0.20→0.35 使架次 18→25，**>0.40 无解** |
| **Q2** | 异构多点多架次调度 | 35 架次 / 83.01 kWh / 完工 587 min；★ **首批时限在本机队下物理不可行**（前 60 min 最多 8~10 架次，但有 9 个区要求 60 min 内送达） |
| **Q3** | 通信约束下运输与中继联合调度 | ★ 实测 **29/35 航段存在直连中断**（平均中断占比 31.3%）→ **中继为必需项**；链路门限：直连 122 dB / 中继接入 116 dB / 中继回传 126 dB；中继 30 架次、总能耗 99.68 kWh |
| **Q4** | 任务分区与资源配置 | ★ **按题目规则不存在合法的 2 组或 3 组分区** —— Q3 的 21 个多点架次把 15 区串成**单一连通分量**，唯一合法分区是「全部一组」。且分区越多资源需求越大（K=1/2/3 → 13/17/21 台·组），**分区无收益** |

---

## 七、关键物理与通信口径（详见规范第 5 节）

| 项 | 口径 |
|---|---|
| 巡航海拔 | 航段经过 DEM 像元的**最高地面高程 + 50 m** |
| 作业高度 | O01 = 地面海拔；服务区 = 地面海拔 **+ 30 m** |
| 载荷–航程 | `L_g(q) = L_g0 − (L_g0 − L_gF)·(q/Q_g)^(3/2)` |
| 最大安全载荷 | 能量约束**二分反解**（无闭式解），回代误差 5.6e-15 |
| 水平巡航能耗 | 由航程反推 `E = (d/L_g(q))·E_g^use`（ADR-021，附件未给巡航功率） |
| 爬升能耗 | `m·g·h⁺ / η_up`，η_up = 0.72（ADR-020） |
| 下降能耗 | **不单独计**（附件下降能耗效率 = 0） |
| 返航余量 | `E_p^T ≤ (1 − 0.20)·E_g^use` |
| 充电 | 两阶段：SOC<90% 占 `T_full` 的 65%，90–100% 占 35%（在 s=0.9 处连续） |
| FSPL | `32.45 + 20log₁₀f(MHz) + 20log₁₀D(km)` ★ 单位是 km |
| 双向门限 | `min(两方向)` |
| 通信三态 | 直连 > 中继（两段**同时**可用）> 中断；**不允许多跳** |
| 多点载荷递减 | 第 m 段携带"尚未投送的货"（飞到第 k 站时仍带第 k..M 站的货） |

**关键事实**：附件 DEM 是 **DSM（数字表面模型，含植被/建筑）**，用于净空与遮挡判定偏保守（ADR-019）。

---

## 八、学术规范红线（违反即取消参评资格）

1. 不得引入其他数据集替换赛题附件
2. 不得以 AI 输出作为学术依据；公式与结论须引用**正式文献或可核验数据**
3. 不得直接复制 AI 生成的建模方案
4. **论文末尾必须披露 AI 工具使用情况**（工具名、输入、输出处理策略、框架、假设、超参数）
5. 提交材料中严禁出现参赛单位、队员姓名、队伍编号
6. ★ `docs/reference/` 中的第三方解答**只能作为格式模板与自查**，
   **不得**将其文字、公式或数字写入本队论文（查重会判定违规）

---

## 九、接手步骤

```powershell
git pull --rebase origin main
Get-Content docs\PROGRESS.md -TotalCount 60        # 进度与阻塞项
Select-String -Path docs\PROGRESS.md -Pattern '\[ \]'   # 未完成项
```

然后按 `docs/IMPLEMENTATION_PLAN.md` 的顺序继续；**每完成一小步就提交**（铁律 R1）。
