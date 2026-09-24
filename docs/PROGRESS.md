# D 题进度看板

最后更新：**P6 已完成**（论文排版整改：MathType 公式 / 三线表 / 章页分页 / 图表同页） | 当前 HEAD：`<见 git log>`

> **接手步骤**：`git pull --rebase origin main` → **读 [`AGENT_GUIDE.md`](AGENT_GUIDE.md)**（四问位置索引 + 答案 + 思维链 + 初稿须知）→ 读本文件 → 读 `OPS_SPEC_D题.md`

---

## 阶段状态

- [x] **P0 数据发现**（附件已到位，全部字段结构实测完成）
- [x] **P0b 航段预计算**（`leg_cache.parquet`，240 条有序航段，哈希索引，构建 0.2 s）
- [x] **P1** Q1 单点往返最大安全载荷与货箱组批 —— 18 架次，逐区达到下界，**可证最优**
- [x] **P2** Q2 异构无人机多点多架次运输调度 —— **16 架次（全 C 型）/ 81.34 kWh / 完工 5.72 h / 准时 51.2%**；物理类违规 0 条
- [x] **P3** Q3 通信约束下的运输与中继联合调度 —— **14 中继架次 / 14-14 全程覆盖 / 91.68 kWh**
- [x] **P4** Q4 救援任务分区与资源配置优化 —— **2 个原子单元 ⇒ K=2 直接可行**、K=3 需拆 1 架次 + 桥接定位与资源核算
- [x] **P5** 论文撰写与图表定稿 —— 24 图 / 28 表 / 51 页 docx + PDF + 分目录备份
- [x] **P6** 论文排版整改 —— 公式 96 个（Word 原生对象，可双击编辑）/ 三线表 28 张 / 章页分页 / 图表同页

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
- [x] `src/report/make_figures.py` / `make_figures2.py` —— 24 图 / 32 表 + **按问题分目录备份**
- [x] `src/report/equations.py` —— ★ 类 LaTeX → **OMML（Word 原生公式对象）**；含 MathType 转换链路（调研用，ADR-028）
- [x] `src/report/build_paper.py` —— ★ 论文装配（三线表 / 分页 / 图表同页 / 表头公式化）
- [x] 交付物：`paper/*.docx`（51 页 / 96 个可编辑公式）、`paper/*.pdf`、`论文体量报告.json`、图表清单与备份清单

### 测试
- [x] **240 passed**（物理公式逐条锁死 + 校验器负样本 + **硬约束闸门** + 四问端到端）

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
- [ ] 论文页数 51 页（要求 50~100）**贴近下限**；若删减内容会跌破下限，需重新核算

### 已解决（P0 实测 + 后续）

- [x] 附件坐标 **WGS84 经纬度（EPSG:4326）**，必须先投影
- [x] DEM：**EPSG:4326 / 30 m / 无无效像元**；16 节点全部在范围内；**是 DSM 而非裸地 DEM**（ADR-019）
- [x] 8 架实体无人机机型分配：**A×4（U01–U04）、B×2（U05–U06）、C×2（U07–U08）**
- [x] 共享电池分机型总数：**A:6 / B:4 / C:4**；中继能源组件 **6 组**
- [x] 链路三条双向门限：**直连 122 dB / 中继接入 116 dB / 中继回传 126 dB**
- [x] 结果格式：**`结果提交模板.xlsx` 的 6 个 sheet**
- [x] 连续通信采样步长 **1 s**（已在第 8 章做敏感性分析）

---

## 交接备忘

- 下一个 agent 应先执行：`git pull --rebase origin main`，然后**先读 `docs/AGENT_GUIDE.md`**（★ 四问的程序/图表/数据位置、答案与思维链、初稿使用须知都在那里），再读本文件与 `OPS_SPEC_D题.md`
- **铁律 R1：每次更改代码必须提交仓库**（改完即 commit，commit 即 push）
- 提交入口：`.\scripts\commit.ps1 -Scope <q0|q1|q2|q3|q4|phys|geo|comms|verify|spec|env|repo|report> -Type <feat|fix|data|model|exp|doc|repo|chore> -Message "..."`
- **物理公式先写测试**：改 `src/physics/`、`src/comms/` 的任何公式，必须同步补测试
- 被推翻的 D 题方案归档到 `docs/legacy_D题/`，说明**为何弃用**，不要就地删除
- ★ **改论文排版前先读 README「一·六 论文排版规范」**，尤其是 `w:tblPr` 顺序与
  `w:gridCol` 单位这两个坑（出错会让 Word 无法分页与导出 PDF）
- ★ **交付格式是硬约束**：`结果提交模板.xlsx` 的 6 个 sheet（题目正文未提及，极易漏）
- ★ **每个服务区恰好 2 个首批箱**（医疗 1 + 饮用水 1）→ 这两箱须同架次送达才能同时满足时限
