# D 题进度看板

最后更新：**P9 已完成**（ADR-031 中继「时间轴覆盖」缺陷修复） | 当前 HEAD：`<见 git log>`

> **接手步骤**：`git pull --rebase origin main` → **读 [`AGENT_GUIDE.md`](AGENT_GUIDE.md)**（四问位置索引 + 答案 + 思维链 + 初稿须知）→ 读本文件 → 读 `OPS_SPEC_D题.md`

---

## 阶段状态

- [x] **P0 数据发现**（附件已到位，全部字段结构实测完成）
- [x] **P0b 航段预计算**（`leg_cache.parquet`，240 条有序航段，哈希索引，构建 0.2 s）
- [x] **P1** Q1 单点往返最大安全载荷与货箱组批 —— 18 架次，逐区达到下界，**可证最优**
- [x] **P2** Q2 异构无人机多点多架次运输调度 —— **25 架次（A8+B10+C7，8 架全投入）/ 77.30 kWh / 完工 3.02 h / 准时 100.0%**；**校验器 0 违规**
- [x] **P3** Q3 通信约束下的运输与中继联合调度 —— 6 中继架次 / **时间轴真实覆盖 11/20 = 55.0%** / 总能耗 79.65 kWh / 联合完工 3.05 h；✅ **ADR-031 缺陷已修复**（见 P9）
- [x] **P4** Q4 救援任务分区与资源配置优化 —— **3 个原子单元 ⇒ K=2 与 K=3 均可直接合并得到（改动 0 架次）** + 桥接定位与资源核算
- [x] **P5** 论文撰写与图表定稿 —— 24 图 / 29 表 / 53 页 docx + PDF + 分目录备份
- [x] **P6** 论文排版整改 —— 公式 106 个（Word 原生对象，可双击编辑）/ 三线表 29 张 / 章页分页 / 图表同页
- [x] **P7** ★ Q2 建模缺陷修复（异构机队退化 / 首批专架次未铺开 / 派发准则退化）—— 见 ADR-029，结论由"首批时限不可行"翻转为"准时率 100%"
- [x] **P8** LaTeX 工具链与论文格式转换 —— 装 MiKTeX 25.12 + pandoc 3.11；LaTeX→PDF 56 页/0 报错；三条 PDF→Word 路径实测（公式可编辑性见 `docs/PDF_TO_WORD.md`）；仓库仅保留 pdf2docx 一份论文产物
- [x] **P9** ★★ **ADR-031 修复：Q3 中继「时间轴覆盖」缺陷** —— 三处缺陷全部修掉（服务区间被静默截短 / 排班不认服务窗口 / 校验器**从未执行**该项检查），并按 **A 口径**（同一悬停点可被多架运输机共享）重排；**实测时间轴覆盖 11/20，中继缺口 4 架**（如实上报）。见 **ADR-031 / ADR-032**

---

## ★ 当前 Q3 口径（P9 之后，写论文务必按此）

| 指标 | 值 | 口径说明 |
|---|---|---|
| 运输架次 | **25**（继承 Q2） | 其中 **20** 个存在直连中断 |
| 中继架次 | **6** | 2 架中继机 × 3 轮 |
| `coverage_rate_geometric` | **20/20 = 100%** | 只回答"**存在**一个悬停点能覆盖该架次全部中断样本"——选址能力的**上界**，**不是**保障结论 |
| `coverage_rate_timeline` | **11/20 = 55.0%** | ★ **唯一可上报口径**：中继在站时段 ∩ 所需中断区间 |
| 中继资源缺口 | **4 架**（`relay_resource_shortage`） | 实际需 6 个中继架次 vs 库存 2 架 ⇒ 缺 4 |
| 运输 / 中继 / 总能耗 | 77.30 / **2.35** / **79.65 kWh** | ★ 按**真实中断区间集合**计，不用包络（见 ADR-032，包络会虚高 39% 站岗时长） |
| 联合完工 | 3.05 h | |
| 校验器 | 42 条**软**违规（全为 `COMMS_RELAY_INSUFFICIENT`） | **硬违规 0 条** ⇒ 方案本身物理/资源可行 |

> ⚠️ **不得**把 `coverage_rate_geometric`（几何可达）当作"已保障"上报。
> ⚠️ 校验器报 `ok=false` 是**设计如此**：42 条全是"中继资源不足"这一**题目内在缺口**，
> 属软违规（如实报告、不中止产出）；**硬约束闸门仍全绿**。

---

## 已完成（摘要）

### 仓库与规范
- [x] 仓库结构、`.gitignore`、`.gitattributes`、`requirements.txt`
- [x] `scripts/commit.ps1` —— 一键提交并推送（含收工自检）
- [x] `scripts/check_env.py` / `run_all.ps1`
- [x] **`OPS_SPEC_D题.md` v2.1** —— 唯一操作规范（铁律 R1–R10、物理口径、四问验收清单）
- [x] `docs/legacy_D题/` —— 废弃 D 题方案归档（只读，含归档规范）
- [x] `docs/reference/` —— `参考文稿2.pdf`（★ 权威排版模板）+ 第三方同题解答（仅模板/交叉验证）

### 公共层（L0–L3，已被四问共用）
- [x] `common/`：`config.py`（D 题口径常量）、`io_utils.py`（结果溯源）、`metrics.py`
- [x] `q0_data/`：`discover.py`（附件清点）、`build_processed.py`（唯一附件解析器）
- [x] `geo/`：`crs.py`（局部切平面 + WGS84 曲率半径）、`dem.py`（`ElevationProvider` 协议）、`leg.py`
- [x] `physics/`：`payload.py`（`brentq` 反解最大安全载荷）、`energy.py`、`battery.py`（两阶段充电）、`leg_cache.py`
- [x] `comms/`：`link.py`（FSPL + 双向链路预算）、`los.py`（三维视线遮挡）、`service.py`（直连/中继/中断三态）
- [x] `verify/feasibility.py` —— **独立校验器**：不 import 任何 `qN_*`，从附件与 DEM 重算全部物理量，18 类约束 + 负样本测试

### 问题层（L4）
- [x] Q1 `q1_payload_grouping/`：载荷表 / FFD 组批 / Martello–Toth 下界 / Pareto / ρ 敏感性
- [x] Q2 `q2_transport_schedule/`：多点串飞（载荷递减）/ 资源池 + 两阶段充电周转 / 时限驱动贪心派发 / 局搜改进
- [x] Q3 `q3_comms_relay/`：轨迹逐时刻采样 / 悬停候选点 / 单点全程覆盖 + 分段接力 / 联合调度
- [x] Q4 `q4_partitioning/`：图与连通分量（原子单元）/ 桥接架次 / RGS 枚举分区 / 资源核算

### 论文层
- [x] `src/report/make_figures.py` / `make_figures2.py` —— 24 图 / 33 个表文件（正文 29 张表） + **按问题分目录备份**
- [x] `src/report/equations.py` —— ★ 类 LaTeX → **OMML（Word 原生公式对象）**；含 MathType 转换链路（调研用，ADR-028）
- [x] `src/report/build_paper.py` —— ★ 论文装配（三线表 / 分页 / 图表同页 / 表头公式化）
- [x] 交付物：`paper/` 论文（Python 管线 **53 页 / 106 个可编辑公式**；另有 LaTeX 公式版 75 页、PDF 转 Word 71 页）、`论文体量报告.json`、图表清单与备份清单

### 测试
- [x] **251 passed**（物理公式逐条锁死 + 校验器负样本 + **硬约束闸门** + 四问端到端 + **ADR-031 中继窗口/区间集合 8 项新测试**）

---

## 环境（已验证，无需重装）

| 项 | 值 |
|---|---|
| Python | 3.13.7 (CPython) |
| 平台 | Windows 11 / AMD64 |
| CPU 核数 | 24 |
| 状态 | ✅ `status: ok` |

公式排版另需：Microsoft Office（提供 `OMML2MML.XSL`）、MathType 9+、Edge/Chrome（Chromium 内核）。

---

## 未决问题

### 仍待定

- [ ] `镇龙乡地理空间数据说明.pdf` 的正文内容尚未逐条提取（需确认是否还有额外口径约定）—— **OPEN-013**
- [ ] 论文页数 53 页（要求 50~100）；若删减内容会跌破下限，需重新核算
- [ ] ★ **Q3 时间轴覆盖率（55%）需写入论文 Q3 章**：把"中继缺口 4 架"作为**资源缺口**如实讨论；
      论文/Q3 图表现仍按旧口径（几何 100%）绘制，**必须重跑 `make_figures*` 与 `build_paper`**（见 P9 交接）

### 已解决（P0 实测 + 后续）

- [x] 附件坐标 **WGS84 经纬度（EPSG:4326）**，必须先投影
- [x] DEM：**EPSG:4326 / 30 m / 无无效像元**；16 节点全部在范围内；**是 DSM 而非裸地 DEM**（ADR-019）
- [x] 8 架实体无人机机型分配：**A×4（U01–U04）、B×2（U05–U06）、C×2（U07–U08）**
- [x] 共享电池分机型总数：**A:6 / B:4 / C:4**；中继能源组件 **6 组**
- [x] 链路三条双向门限：**直连 122 dB / 中继接入 116 dB / 中继回传 126 dB**
- [x] 结果格式：**`结果提交模板.xlsx` 的 6 个 sheet**
- [x] 连续通信采样步长 **1 s**（已在第 8 章做敏感性分析）
- [x] ★★ **ADR-031 中继时间轴覆盖缺陷**（P9）：三处根因已修 + 校验器补交叉检查 + 如实上报缺口

---

## 交接备忘

- **★ P9 之后第一件事**：论文与 `otheragent/` 的 Q3 数字**仍是旧口径**（几何覆盖 100% / 中继 20 架次 / 82.14 kWh），
  必须按本文件「当前 Q3 口径」表更新，并重跑：
  ```powershell
  python -m src.report.make_figures
  python -m src.report.make_figures2
  python -m src.report.build_paper
  python scripts\verify_paper.py
  python scripts\diag\check_paper_numbers.py   # 核对论文数字与 metrics
  ```
- 下一个 agent 应先执行：`git pull --rebase origin main`，然后**先读 `docs/AGENT_GUIDE.md`**（★ 四问的程序/图表/数据位置、答案与思维链、初稿使用须知都在那里），再读本文件与 `OPS_SPEC_D题.md`
- **铁律 R1：每次更改代码必须提交仓库**（改完即 commit，commit 即 push）
- 提交入口：`.\scripts\commit.ps1 -Scope <q0|q1|q2|q3|q4|phys|geo|comms|verify|spec|env|repo|report> -Type <feat|fix|data|model|exp|doc|repo|chore> -Message "..."`
- **物理公式先写测试**：改 `src/physics/`、`src/comms/` 的任何公式，必须同步补测试
- ★ **改动 Q3 的口径或结果后必须重跑 Q4**（Q4 继承 Q3 的架次划分，原子单元数会变；**不得硬编码**）
- 被推翻的 D 题方案归档到 `docs/legacy_D题/`，说明**为何弃用**，不要就地删除
- ★ **改论文排版前先读 README「一·六 论文排版规范」**，尤其是 `w:tblPr` 顺序与
  `w:gridCol` 单位这两个坑（出错会让 Word 无法分页与导出 PDF）
- ★ **交付格式是硬约束**：`结果提交模板.xlsx` 的 6 个 sheet（题目正文未提及，极易漏）
- ★ **每个服务区恰好 2 个首批箱**（医疗 1 + 饮用水 1）→ 这两箱须同架次送达才能同时满足时限
