# D 题进度看板

最后更新：F 题 → D 题切换 | 当前 HEAD：`<见 git log>`

> **接手步骤**：`git pull --rebase origin main` → 读本文件 → 读 `OPS_SPEC_D题.md`

---

## 阶段状态

- [ ] **P0 数据获取与发现**（★ 阻塞性前置任务）
- [ ] **P0b 航段预计算**（`leg_cache.parquet`，Q1–Q4 共同依赖）
- [ ] **P1** Q1 单点往返最大安全载荷与货箱组批
- [ ] **P2** Q2 异构无人机多点多架次运输调度
- [ ] **P3** Q3 通信约束下的运输与中继联合调度
- [ ] **P4** Q4 救援任务分区与资源配置优化
- [ ] **P5** 论文撰写与图表定稿

---

## 已完成

### 仓库与规范
- [x] 初始化仓库结构（`.gitignore` / `.gitattributes` / `requirements.txt`）
- [x] `scripts/commit.ps1` —— 一键提交并推送（含收工自检，未推送则抛异常）
- [x] `scripts/check_env.py` —— 环境自检，输出 `outputs/env_report.json`
- [x] `scripts/run_all.ps1` —— 端到端复现骨架
- [x] **`OPS_SPEC_D题.md` v2.0** —— D 题操作规范（含铁律 R1–R10、物理口径章、四问验收清单）
- [x] F 题遗留物归档至 `docs/legacy_F题/`

### 公共层（可复用，已测试）
- [x] `src/common/config.py` —— 路径 / SEED / 全局常量
- [x] `src/common/io_utils.py` —— 统一读写 + 结果溯源（自动记录 git commit 与 seed）
- [x] `src/common/metrics.py` —— R²/调整R²/RMSE/MAE/AIC/BIC/F1/区间覆盖率
- [x] `src/common/simplex.py` —— CLR/ALR/ILR 变换（D 题一般用不到，保留备选）
- [x] `src/q0_data/discover.py` —— 数据发现脚本（已通过空数据 + 正常数据冒烟测试）
- [x] 测试 **45 项全部通过**

### 环境（已验证，无需重装）
- [x] 依赖栈全部安装并导入通过（含 `rasterio` / `geopandas` / `ortools` 等 D 题新增项）
- [x] `PROJ 9.8.1` 可用，`EPSG:4326` 正常 → 投影变换可用

| 项 | 值 |
|---|---|
| Python | 3.13.7 (CPython) |
| 平台 | Windows 11 / AMD64 |
| CPU 核数 | 24 |
| 状态 | ✅ `status: ok` |

---

## 待实现（按依赖顺序）

| 模块 | 状态 | 依赖 |
|---|---|---|
| `src/q0_data/validate.py` | ⬜ | P0 数据到位 |
| `src/q0_data/build_processed.py` | ⬜ | 同上 |
| `src/geo/crs.py` | ⬜ | 确认附件坐标 CRS |
| `src/geo/dem.py` | ⬜ | DEM 到位 |
| `src/geo/los.py` | ⬜ | `dem.py` |
| `src/geo/grid.py` | ⬜ | `dem.py`（Q3 悬停候选点） |
| `src/physics/leg.py` | ⬜ | `geo/dem.py` |
| `src/physics/energy.py` | ⬜ | `leg.py` |
| `src/physics/payload.py` | ⬜ | `energy.py` |
| `src/physics/battery.py` | ⬜ | — |
| `src/physics/precompute.py` | ⬜ | `leg.py` `energy.py` |
| `src/comms/link.py` | ⬜ | `geo/los.py` |
| `src/comms/service.py` | ⬜ | `link.py` |
| `src/verify/feasibility.py` | ⬜ | `physics/` `comms/` |
| `src/q1_payload_grouping/*` | ⬜ | `physics/` |
| `src/q2_transport_schedule/*` | ⬜ | `verify/` |
| `src/q3_comms_relay/*` | ⬜ | `comms/` |
| `src/q4_partitioning/*` | ⬜ | Q3 方案 |
| `tests/test_physics.py` | ⬜ | ★ 物理公式必须先写测试 |
| `tests/test_geo.py` / `test_comms.py` / `test_verify.py` | ⬜ | 对应模块 |
| `src/common/plotting.py` / `registry.py` | ⬜ | — |
| `src/report/*` | ⬜ | 各问结果 |

---

## 阻塞项（需人工介入）

- [ ] **缺失数据**：工作区内目前只有 6 份题目 Word 文档，`data/raw/` 为空。
      D 题所需附件**必须先从竞赛官方渠道下载**：

  | # | 附件 | 状态 |
  |:--:|---|---|
  | 1 | `调度中心与服务区.xlsx` | ⬜ 缺 |
  | 2 | `物资需求与配送时限.xlsx` | ⬜ 缺 |
  | 3 | `运输无人机数据.xlsx` | ⬜ 缺 |
  | 4 | `中继无人机数据.xlsx` | ⬜ 缺 |
  | 5 | `通信链路参数.xlsx` | ⬜ 缺 |
  | 6 | 30 m DEM（镇龙乡） | ⬜ 缺 |
  | 7 | `镇龙乡地理空间数据说明.docx` | ⬜ 缺 |

  在数据到位前，**P0 无法启动，P1–P4 全部阻塞**。

---

## 未决问题（P0 阶段必须回答）

- [ ] 附件坐标是**经纬度还是投影坐标**？单位是什么？（决定 `geo/crs.py` 的实现，★ 见规范 2.3 节）
- [ ] DEM 的 **CRS / 分辨率 / nodata / 高程基准**
- [ ] 3 种运输机型的**型号代码**与全部参数列名（`L_g0` `L_gF` `Q_g` `Q_g^vol` `v↑` `v_c` `v↓` `E_g^use` `ρ_g` `T_full`）
- [ ] **8 架实体无人机在 3 种机型间如何分配**
- [ ] 80 个货箱的**箱号 / 所属服务区 / 质量 / 体积 / 物资类型 / 期望送达时间 / 首批截止时间**列名
- [ ] "医疗物资期望送达时间"与"首批保障货箱截止时间"在附件中的**确切字段**
- [ ] 共享电池**分机型的总数**；中继能源组件总数
- [ ] 中继无人机**悬停离地高度上限**、水平巡航功率、悬停功率、通信附加功率
- [ ] 链路参数中各主体（G01 / 运输机 / 中继机）的 `P_t` `G_t` `G_r` `P_sens` `M` `L_sys` `L_obs` `f` 取值差异
- [ ] 连续通信判定的**采样步长**取多少（需做敏感性分析）
- [ ] 附件模板要求的**结果文件格式**（题目提到"按附件模板提交必要的结果文件"）

---

## 交接备忘

- 下一个 agent 应先执行：`git pull --rebase origin main`，然后读本文件与 `OPS_SPEC_D题.md`
- **铁律 R1：每次更改代码必须提交仓库**（改完即 commit，commit 即 push）
- 提交入口：`.\scripts\commit.ps1 -Scope <q0|q1|q2|q3|q4|phys|geo|comms|verify|spec|env|repo> -Type <type> -Message "..."`
- **建议实现顺序**（尊重依赖）：
  `geo/crs.py` → `geo/dem.py` → `physics/leg.py` → `physics/energy.py` → `physics/payload.py`
  → `physics/battery.py` → `geo/los.py` → `comms/link.py` → `comms/service.py`
  → `verify/feasibility.py` → Q1 → Q2 → Q3 → Q4
- **物理公式先写测试**：新增/修改 `src/physics/`、`src/comms/` 的任何公式，
  必须同步补 `tests/test_physics.py`（规范 7.3 节给出了必测清单）
- F 题的历史决策在 `docs/legacy_F题/`，**仅作参考，不要套用**
