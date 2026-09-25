# MathAgent

2026 年中国研究生数学建模竞赛 **D 题**（山区洪涝灾害下无人机运输与通信协同优化）的建模工作仓库。

> **归档约定**：`docs/legacy_D题/` 存放**被推翻或已废弃**的 D 题方案（旧模型形式、试过但不 work 的算法），
> 只读保留、不再维护，目的是留下"为什么否掉某个方案"的轨迹。
> `docs/reference/` 存放**第三方同题解答**（非本队产出），仅作风格模板与交叉验证，
> **不得引用其文字或数字**（详见该目录 README）。
>
> ★ **接手请先读 [`docs/AGENT_GUIDE.md`](docs/AGENT_GUIDE.md)** —— 四问的
> 「程序 / 图表 / 数据」详细位置索引、**答案与完整思维链**，以及**初稿
> （`docs/reference/参考文稿2.pdf`）哪些能放心参考、哪些公式有错必须修正**。

---

## 一、当前状态

| 阶段 | 状态 | 关键产出 |
|---|:--:|---|
| **P0** 数据发现 + 航段预计算 | ✅ 完成 | `outputs/data_inventory.json`、`data/processed/leg_cache.parquet`（240 条有序航段） |
| **P0b** 物理 / 地理 / 通信 / 校验器 | ✅ 完成 | `src/physics/`、`src/geo/`、`src/comms/`、`src/verify/` |
| **P1 / Q1** 载荷能力与货箱组批 | ✅ 完成 | **18 架次（B×9 + C×9）/ 59.087498 kWh / 累计作业 32676.33 s**；逐区等于下界（下界合计 18 = 精确 DP 架次数，**gap 0**）。方法：`exact_pack.py` 箱型聚合 + 可行批次枚举 + **精确字典序 DP** `min_lex(#架次, 能耗, 累计作业时间)` |
| **P2 / Q2** 异构多点多架次调度 | ✅ 完成 | **23 架次（A6+B9+C8，8 架实体机全投入）/ 66.789867 kWh / 完工 7843.2266 s（2.179 h）**；**首批 30/30、期望 80/80 全部按时**，独立校验器 **0 违规**（最大能耗偏差 0.003241 kWh / SOC 0.002044） |
| **P3 / Q3** 通信约束下运输与中继联合调度 | ✅ 完成 | **运输 23 + 中继 3 架次 / 66.789867 + 4.306050 = 71.095918 kWh / 联合完工 7939.2924 s**；沿完整轨迹按 **0.25 s** 采样诊断（99,889 个样本，LOS 步长 60 m）：18 个架次需中继，**19/23 全程零中断**，928 个中断样本（**0.929%**），集中于 T10/T20/T18/T15；最小直连裕量 −6.205 dB、最小中继裕量 +0.436 dB |
| **P4 / Q4** 任务分区与资源配置 | ✅ 完成 | **15 个原子单元 / 0 个桥接架次**；K=2 与 K=3 均可行且**改动 0 架次**；资源总量 K=1/2/3 = **28/29/30（台·组）**（运输机 8/9/10、电池 15/15/15、中继机 2/2/2、中继组件 3/3/3），组间不均衡 **0/0.2289/0.8425**，单组最大工作量 **11.27/6.28/5.62 h**；资源缺口（逐机型）：K=1 → **C 型电池 +1 组**；K=2 → **B 型运输机 +1 架 且 C 型电池 +1 组**；K=3 → **B 型运输机 +1 架、C 型运输机 +1 架 且 C 型电池 +1 组**。★ 中继按**唯一归属**核算（`assign_relays_to_groups`，属乐观口径，见下） |
| **P5** 论文与 Word 生成 | ✅ 完成 | **53 页论文**（24 图 / 29 表 / **106 个 Word 原生公式对象** / 2.1 万字），`paper/` 下含 docx + PDF + 分目录图表备份 |
| **P6** 排版整改（公式 / 三线表 / 章页分页 / 图表同页） | ✅ 完成 | 见「一·六 论文排版规范」；公式形态见 **ADR-028** |
| **P7** ★ Q2 建模缺陷修复 | ✅ 完成 | 异构机队退化 + 首批专架次未铺开 + 派发准则退化 ⇒ 首批结论由"不可行"翻转为 **准时率 100%**，见 **ADR-029** |
| **P8** LaTeX 工具链与论文格式转换 | ✅ 完成 | 装 MiKTeX 25.12 + pandoc 3.11；打通 LaTeX→PDF（56 页/0 报错）与三条 PDF→Word 路径；仓库仅保留 pdf2docx 一份论文产物，见「一·五」与 `docs/PDF_TO_WORD.md` |
| **P9** ★★ Q3 中继「时间轴覆盖」缺陷修复（**旧管线**） | ✅ 完成（历史） | 三处根因全修（服务区间被静默截短 / 排班不认服务窗口 / **校验器从未执行该项检查**），按 **A 口径**（同点可共享）重排。该轮的 11/20、6 中继架次等数值属**旧管线**，已被 **P10** 取代。见 **ADR-031 / ADR-032** |
| **P10** ★★ **数值全量重建（本文件所述口径以本轮为准）** | ✅ 完成 | Q1 改走 `exact_pack.py` **精确字典序 DP**（18 架次 / 59.087498 kWh / gap 0）；Q2 改由 `dispatcher.py` **CP-SAT 资源区间调度**（23 架次 / 66.789867 kWh / 7843.2266 s / 30:30 + 80:80 全达标）；Q3 改由 `timeline.py` **时间轴诊断**（3 中继架次 / 19-23 零中断 / 928 中断样本）；Q4 重算为 **15 原子单元 / 0 桥接**。见 **ADR-033 ~ ADR-036** |
| **P10b** ★★ **第二轮重跑（Q4 中继归属 + Q1 ρ 扫描同口径）** | ✅ 完成 | ① **Q4 中继归属修复**：旧 `group_resources()` 要求"中继保障的运输架次**全部**在本组"才计入，而 `R01-1` 保障全部 23 个架次 ⇒ K=2/K=3 曾算出**中继 0 架 / 0 组**；新增 `assign_relays_to_groups()`（归给"覆盖架次最多"的组，平票取服务区交集更多者、再取组号小者），并修掉 `load_q3()` 把 `q3_通信保障.csv`（47 条 pair）读成**一对一字典**的覆盖 bug ⇒ 资源 **28/29/30**、缺口重算为 **K=1 C 型电池 +1 / K=2 B 型机 +1 与 C 型电池 +1 / K=3 再加 C 型机 +1**。② **Q1 ρ 扫描改走精确 DP**（`sweep_reserve_ratio_exact`）⇒ ρ=0.10 与 0.20 的扫描值 = 答案值 **18 架次 / 59.087498 kWh**，ρ=0.30 → 20 架次 / 67.180487 kWh，≥0.40 不可行；启发式版本另存 `q1_4_rho_sweep_heuristic_ref.csv`（**仅对照，不进论文**）。见 **ADR-037 / ADR-038** |

> ## ★ 数值口径：三档信息必须分清（本轮重建后）
> | 档位 | 含义 | 本轮对应物 |
> |---|---|---|
> | **附件核对的输入** | 直接读赛题附件得到的参数（机型/机队/电池/货箱/时限/DEM/链路预算） | `data/processed/`、`docs/DATA_NOTES.md` |
> | **本文复现的结果** | 本仓程序算出、并经独立校验器复核 | `outputs/q1..q4/metrics.json` + `outputs/summary.json` |
> | **仅作对照的候选结果** | 只用于权衡比较，不声称最优性 | 给定方案的 7740.19 s 时刻表、4 中继对照方案（`outputs/q3_4relay/`）、`q2_机队对比.csv` |
>
> **不得**把候选结果写成"本文方案更优/更差"之外的结论。
> ★ **Q1 的 ρ 扫描（`q1_4_rho_sweep.csv`）与答案路径同口径**（`sweep_reserve_ratio_exact` → 精确字典序 DP），
> 可直接引用；启发式版本另存 `q1_4_rho_sweep_heuristic_ref.csv`，**仅作策略对照、不进论文**。

> ## ★ Q4 中继核算的**乐观口径**（必须与 Q4 结论同时说明）
> 中继按**唯一归属**计入某一组：`assign_relays_to_groups()` 把每个中继架次归给
> "它保障的、落在该组的运输架次最多"的那一组（平票取服务区交集更多者，再取组号小者）。
> 因此**某组的通信若实际依赖别组的中继，本核算不额外补偿** ——
> 这是"资源不得跨组调配"下偏乐观的读法（实测 K=2 的 G2、K=3 的 G2/G3 名下中继均为 0），
> 论文中必须与缺口结论并列写出（见 **ADR-037**）。

> ## ★ Q3 结论附带的两条强制警示（必须随数值一起引用）
> 1. **巡航海拔是显式扩展模型**：3/4 中继方案取
>    `巡航海拔 = max(沿线 DEM 最高点 + 50 m, 悬停海拔)`；按附录 2 的严格读法，
>    "最高地面高程 + 50 m"未必等于该值 ⇒ 相关结论在该扩展模型下成立，属**有条件结论**。
> 2. **通信结论建立在有限采样上**：时间轴诊断按 **0.25 s** 步长采样（99,889 个样本，
>    LOS 步长 60 m），**不构成连续时间的数学证明**；只能表述为"在 0.25 s 采样下未发现中断"。
>
> 现行 Q3 事实（`outputs/q3/metrics.json`）：运输 **23** + 中继 **3** 架次、
> 总能耗 **71.095918 kWh**、联合完工 **7939.2924 s**、
> **19/23** 个架次零中断、**928** 个中断样本（0.929%）、
> 最小直连裕量 **−6.205 dB**、最小中继裕量 **+0.436 dB**。
> 中断缺口全部集中在 4 个架次：T10（S013，615 点）、T20（S009，138）、
> T18（S005，146）、T15（S004，29）—— 其根因是**中继站位时间这一资源限制**
> （仅 2 架中继机），故按**资源限制**如实上报，不再声称"覆盖率 100%"。

**环境**：Python 3.13.7 / Windows 11 / 24 核；依赖已锁定（`requirements.txt`），`check_env.py` 返回 `status: ok`。
**测试**：`251 passed`。

---

## 一·五、论文交付物（paper/）

| 文件 | 说明 |
|---|---|
| `paper/山区洪涝灾害下无人机运输与通信协同优化_论文_PDF转Word_pdf2docx.docx` | ★ **本仓库唯一在库的论文产物**（由 `otheragent/document.pdf` 转出，pdf2docx 路径，版面对齐 PDF 原文；**公式为文本/图片，非原生公式对象**） |
| `paper/山区洪涝灾害下无人机运输与通信协同优化_论文.docx` / `.pdf` | 正文 Word/PDF（**53 页**，Python 管线产出；公式 106 个 Word 原生对象，**双击可编辑**）。**已从版本库移除、仅保留在本地**，用 `python -m src.report.build_paper` + `python scripts\check_paper.py --pdf` 重新生成 |
| `paper/山区洪涝灾害下无人机运输与通信协同优化_论文_LaTeX公式版.docx` / `.pdf` | pandoc 由 LaTeX 源转出（**554 个原生可编辑公式**），75 页。**已从版本库移除、仅保留在本地**，用 `pwsh -File scripts\build_word_from_latex.ps1` 重新生成 |
| `paper/山区洪涝灾害下无人机运输与通信协同优化_论文_PDF转Word.docx` | Word 自带 PDF 重排（分块）转出，**公式为图片**、但保留公式编号与原版面。**已从版本库移除、仅保留在本地**，用 `python scripts\diag\pdf_to_docx_chunked.py` 重新生成 |
| `paper/论文体量报告.json` | 页数/字数/表格/图片统计（`scripts/check_paper.py` 生成） |
| `paper/chart_manifest.csv` | 全部图表的编号、标题、章节与文件清单（24 图 / 33 个表文件（正文 29 张表）） |
| `paper/backup_manifest.csv` | 分目录备份统计 |
| `paper/figures/` `paper/tables/` `paper/data/` | 全部图 / 表 / 图表数据源 |
| **`paper/by_question/{common,q1,q2,q3,q4}/{figures,tables,data}`** | ★ **按问题分目录的图表与原始数据备份** |

论文结构依 **`docs/reference/参考文稿2.pdf`** 的章节骨架（引言与问题重述 → 总体分析 → 公共物理模型 →
四问 → 模型检验 → 结论 → 附录）；**论文排版规范以参考文稿2 为准**（详见下节）。

### 论文生成流程

```powershell
python -m src.report.make_figures    # 基础图表（17 图 / 21 表）
python -m src.report.make_figures2   # 补充图表 + 分目录备份（→ 24 图 / 33 个表文件（正文 29 张表））
python -m src.report.build_paper     # 装配 Word（公式为 Word 原生公式对象）
python scripts\verify_paper.py       # 一键回归：结构自检 + 页数核算 + 导出 PDF
```

> `python -m src.report.build_paper --mathtype` 为实验开关（MathType OLE 路线，见 ADR-028），
> 默认不使用。

---

## 一·六、论文排版规范（4 项硬性要求 + 自检脚本）

| # | 要求 | 实现方式 | 自检脚本 |
|:--:|---|---|---|
| 1 | **公式可用、比例正确**（正文嵌入、表格嵌入均含） | ★ 公式以 **Word 原生 OMML 公式对象**（`m:oMath`）交付：**双击即可编辑**，字号由 Word 排版引擎决定、**与正文一致**。正文 60 个 + 表头 19 个 ≈ **96 个**（含表格内） | `scripts\check_docx_structure.py`（统计 `m:oMath` 与表格内数量） |
| 2 | **每一章另起新页** | 写进 `Heading 1` 样式 `pageBreakBefore`，不逐处插分页符（目录页显式关闭） | `check_docx_structure.py`（逐个一级标题校验） |
| 3 | **三线表**（参照参考文稿2） | 顶线 / 表头下线 / 底线，**无竖线**；列宽按内容自适应（幂律压缩，列宽比 ≤4:1）；≥9 列自动降字号 | `check_docx_structure.py`（逐表校验边框） |
| 4 | **图与表跟题注同页** | 图片段落 `keepNext` → 图与图题同页；表题 `keepNext` → 表与表题同页；图高按比例限制 ≤9 cm | `check_docx_structure.py` + `scripts\check_pagination.py` |

其它配套：表头中文化并把单位渲染为行内公式（如"最大安全载荷 / $\mathrm{kg}$"）、
符号表改为参考文稿2 的双栏版式、插图内部**不再重复写图号**（避免同一张图两个编号）。

### ★ 公式形态：为什么用 OMML 而不是 MathType OLE（ADR-028）

曾按要求走过 `docx-equation` 的 **MathType `Equation.DSMT4` OLE** 路线，实测**不可用**：

| 问题 | 现象 | 证据 |
|---|---|---|
| **双击打不开** | `OLEFormat.ProgID` 为空，`Activate()` 抛"此对象已损坏或不再可用" | 隔离实验：最小 docx（仅 1 个公式）同样失败；换成自建**合规 CFB 容器**重打包仍失败；而 Word+MathType 亲手插入的**真品**对象可正常激活 |
| **公式退化成普通文字** | 该库把 `mml:math` 原样嵌入 HTML，而 **HTML 解析器不做命名空间解析** → 上下标/分式全丢 | `--dump-dom` 显示 `<math>` 出现 0 次、`<msub>` 0 次 |

因此交付形态改为 **OMML**（Word 内置公式对象），两项硬要求同时满足：

- **可编辑**：Word COM 实测 **96 个 `m:oMath` 全部可选中、可 `BuildUp`**，双击进入公式编辑器；
- **比例正确**：公式由 Word 排版引擎渲染，字号随正文（12 pt）自动匹配，不再出现"公式偏大/偏小"。

> 若确实需要 MathType 对象：打开 docx → MathType 加载项 →「转换公式 / Convert Equations」→
> 选"Word 内置公式 → MathType 公式"，一次性批量转换即可（MathType 自己生成的对象是可用的）。
> 本仓库保留 `--mathtype` 实验开关与 `src/report/equations.py` 的转换链路，仅用于调研复现。

**排版相关自检工具**：

```powershell
python scripts\check_docx_structure.py   # 分页/三线表/公式对象/图表同页（不依赖 Word）
python scripts\check_pagination.py       # 逐页量测页尾留白，找排版异常页
python scripts\render_pdf_pages.py 13 14 # 渲染指定页为 PNG，供人工核对
python scripts\smoke_mathtype.py         # MathType 链路冒烟测试（含 Word 打开校验）
python scripts\diag\span_sizes.py 本论文 13   # 列出各 span 字号，核对正文/公式比例
python scripts\diag\line_heights.py 13        # 逐行量测墨迹高度
python scripts\diag\calibrate_scale.py 12     # 标定"预览图像素 → 文档点数"
```

> ⚠️ **踩过的坑（已修复，勿回退）**：
>
> | 坑 | 症状 | 处理 |
> |---|---|---|
> | `w:tblPr` 子元素顺序不符合 schema | Word 判定文档异常：**无法分页、无法导出 PDF**（"无法准备用于导出的文档"） | `build_paper.py::_order_tblpr()` 按 CT_TblPrBase 顺序重排 |
> | `w:gridCol/@w:w` 误写 EMU（`int(Cm(x))` 给的是 EMU，与 twips 差 635 倍） | 同上 | 一律用 `Cm(x).twips` |
> | 表格数据行里残留 `$\mathrm{kg}$` 等公式标记 | Word 里出现 LaTeX 原文 | `build_paper.py::_math_to_plain()` 在数据行剥成纯文本（表头保留行内公式） |
> | 超长单元格（如货箱编号列表）不截断 | 列宽被拉满、整表撑到跨页 | `_shorten()` 截断为 34 字符并注明完整数据见附件 CSV |
> | 所有公式挤成同一高度 | 公式被渲染成"一行普通文字"（上下标/分式丢失）——见 ADR-023 | `check_docx_structure.py` 增加预览图高度分布检查，异常即报错 |

---


### 论文格式转换（PDF ↔ Word）

本仓论文有 4 份形态，**公式可编辑性差别很大，别搞混**（完整对比见 `docs/PDF_TO_WORD.md`）：

| 产物 | 生成方式 | 公式 | 可编辑 | 页数 | 入库 |
|---|---|---|---|---|---|
| `…_论文.docx` / `.pdf` | Python 管线（**正式提交稿**） | 106 个 OMML | ✅ | 53 | ❌ |
| `…_论文_LaTeX公式版.docx` / `.pdf` | pandoc 转 LaTeX 源（**公式基准版**） | **554 个原生 OMML** | ✅ | 75 | ❌ |
| `…_论文_PDF转Word.docx` | Word 自带 PDF 重排（分块） | **图片**（保留公式编号） | ❌ | 71 | ❌ |
| **`…_论文_PDF转Word_pdf2docx.docx`** | **pdf2docx** 转 PDF | 文本/图片 | ❌ | — | ✅ **唯一在库** |

```powershell
pwsh -File scripts\build_word_from_latex.ps1    # LaTeX 源 → Word（554 个原生公式）
python scripts\diag\pdf_to_docx_chunked.py otheragent\document.pdf out.docx 4   # PDF → Word（分块）
```

> ★ **关键结论：从 PDF 转出的 Word，公式一定是图片** —— PDF 里公式已是矢量字形、
> 语义结构已丢失，任何工具都无法还原为可编辑公式对象（实测 Word 重排与 pdf2docx
> 的 `m:oMath` 均为 **0**）。要"可双击编辑的原生公式"，**只能从 LaTeX 源转**（pandoc）。
>
> **为什么分块**：整本 56 页一次性给 Word 重排会崩（`RPC 服务器不可用`）且极慢
> （3 页 274 s，含冷启动）；按 4 页切片后单片约 15 s、全量约 8 min。
> 另有两个坑：Word COM **不继承进程 cwd**（相对路径会被解析到 `C:\Windows\system32`，
> 必须 `.resolve()`）；**切片进行中不要清理切片目录**，否则 Word 卡死在模态对话框。

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
python -m src.report.solve_solution       # ★ 权威入口：Q1 精确 DP（含 ρ 扫描）+ Q2/Q3 装配 + 双中继对照 + 汇总（实测 135.3 s）
python -m src.q1_payload_grouping.run_q1  # 可选：Q1 独立入口
python -m src.q2_transport_schedule.run_q2 # 可选：旧求解器入口（不在答案路径）
python -m src.q3_comms_relay.run_q3       # 可选：Q3 选址/排班入口（旧口径会重写遗留表）
python -m src.q4_partitioning.run_q4      # 可选：Q4 独立入口（实测 99.3 s）
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
│   ├── q1_payload_grouping/     Q1：载荷表 / **exact_pack.py 精确字典序 DP 组批** / 下界 / rho_g 敏感性
│   ├── q2_transport_schedule/   Q2：多点串飞 / 资源周转 / **dispatcher.py CP-SAT 资源区间调度** / solution.py 方案装配与独立复核
│   ├── q3_comms_relay/          Q3：中继选址 / 轨迹覆盖 / **timeline.py 联合时间轴通信诊断**
│   ├── q4_partitioning/         Q4：分区（原子单元/连通分量）与资源核算
│   └── report/                  论文装配
│       ├── make_figures.py      基础图表（17 图 / 21 表）
│       ├── make_figures2.py     补充图表 + 按问题分目录备份
│       ├── equations.py         ★ 公式：类 LaTeX → OMML（Word 原生公式对象）
│       ├── cfb.py               OLE2 复合文档生成器（MathType 调研用，见 ADR-028）
│       └── build_paper.py       ★ 论文装配（三线表 / 章页分页 / 图表同页）
├── outputs/                     ★ 证据链：metrics / params / 数据表 / 校验报告
│   ├── q1/  q2/  q3/  q4/      每问含 metrics.json、params.json、tables/（**旧 figures/ 目录已移除**，图统一在 paper/figures/）
│   ├── q3_3relay/  q3_4relay/  中继架次数参数化对照（主方案 3 / 对照 4）
│   ├── solution/  report/      方案求解与论文产出的运行日志
│   └── p0_inspect/  p0_smoke/  附件勘察与冒烟验证记录
├── scripts/
│   ├── commit.ps1               ★ 一键提交并推送（含收工自检）
│   ├── check_env.py             环境自检
│   ├── verify_paper.py          ★ 论文一键回归（构建 + 自检 + 页数 + PDF）
│   ├── check_docx_structure.py  ★ 分页/三线表/公式/图表同页 结构自检
│   ├── check_pagination.py      逐页留白体检
│   ├── check_equations.py       公式解析自检（42 条样例）
│   ├── check_paper.py           页数与体量核算（Word COM）
│   ├── render_pdf_pages.py      PDF 指定页转 PNG（人工核对）
│   ├── smoke_mathtype.py        MathType 链路冒烟测试
│   ├── inspect_attachments.py   附件结构勘察
│   ├── smoke_physics_real_data.py / smoke_comms_real_data.py / smoke_verify_real_data.py
│   ├── diag/                    ★ 30 个诊断脚本（排版量测、OLE 解剖、CFB 调试等）
│   └── run_all.ps1              端到端复现
├── docs/
│   ├── AGENT_GUIDE.md           ★★ 交接导航（四问位置索引 / 答案与思维链 / 初稿使用须知）
│   ├── PROGRESS.md              ★ 进度看板
│   ├── DATA_NOTES.md            ★ 附件字段结构实测记录
│   ├── MODEL_NOTES.md           ★ 各问数学形式与推导
│   ├── IMPLEMENTATION_PLAN.md   五层解耦结构与实现顺序
│   ├── DECISIONS.md             决策记录（ADR-001~036；ADR-029~032 已标注"属旧管线"）
│   ├── TOOLS.md                 外部工具来源/版本/许可证
│   ├── reference/               ★ 参考文稿2（章节与排版模板）+ 第三方同题解答（仅作模板/交叉验证）
│   └── legacy_D题/              废弃的 D 题方案归档（只读）
└── tests/                       240 项测试（物理公式逐条锁死 + 负样本 + 硬约束闸门）
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
| **Q1** | 单点往返最大安全载荷 + 货箱组批 | A 型 **15/15**、B 型 14/15 全区受**结构载重**约束，能量仅为次要约束；**精确字典序 DP** 给出 **18 架次（B×9 + C×9）/ 59.087498 kWh / 累计作业 32676.33 s**，逐区达到架次数下界（下界合计 **18**，gap **0**）。同组批改全 C 型对照为 18 架次 / 74.2611 kWh ⇒ 混用 B 型省 **20.43%** 能耗。★ ρ 敏感性同走精确 DP：ρ=0.10 与 0.20 均为 18 架次 / 59.087498 kWh（**该区间不损失效率**），ρ=0.30 → 20 架次 / 67.180487 kWh，ρ ≥ 0.40 起 2 个区无可行组批 |
| **Q2** | 异构多点多架次调度 | **23 架次（A6+B9+C8，8 架实体机全投入）/ 66.789867 kWh / 完工 7843.2266 s（2.179 h）**；**首批 30/30、期望 80/80 全部按时**。组批继承 Q1 的精确 DP，仅对 **S006/S007/S008/S013** 4 个区增开先行小架次以满足首批/医疗时限（18→23）；调度用 **CP-SAT 区间调度**（可选区间 + `NoOverlap` + 两阶段充电占用 + 逐箱硬时限 + 可行解提示）。★ 给定方案的 7740.19 s 时刻表**更短但违反 S015 医疗箱 7200 s 硬时限**（实际 7470.0 s 交付）⇒ 本方案的 7843.20 s 是"满足全部硬时限"下的最优值，**不是模型更慢** |
| **Q3** | 通信约束下运输与中继联合调度 | 运输 23 + 中继 **3** 架次（2 架中继机，`R01-1` / `R02-1` / `R02-2`）；总能耗 66.789867 + 4.306050 = **71.095918 kWh**；联合完工 **7939.2924 s**。链路门限：直连 122 dB / 中继接入 116 dB / 中继回传 126 dB。沿完整轨迹 **0.25 s** 采样（99,889 样本）：**18 个架次需中继**，**19/23 全程零中断**，**928** 个中断样本（0.929%）集中在 T10(S013)/T20(S009)/T18(S005)/T15(S004)；最小直连裕量 **−6.205 dB**、最小中继裕量 **+0.436 dB**。★ 两条强制警示：巡航海拔取 `max(沿线 DEM 最高+50 m, 悬停海拔)` 属**显式扩展模型**；结论基于**有限采样**，非连续时间证明 |
| **Q4** | 任务分区与资源配置 | ★ 合法组数 **K ∈ [1, 原子单元数]**；本轮方案 23 个架次**全部为单点路线** ⇒ **15 个原子单元**（每区独立）、**0 个桥接架次** ⇒ **K=2 与 K=3 均可行且改动 0 架次**。资源总量 K=1/2/3 → **28/29/30 台·组**（K=2 起每组要独立储备运输机峰值），组间不均衡 **0/0.2289/0.8425**，单组最大工作量 **11.27/6.28/5.62 h**（K=3 比 K=1 低约 **50%**）。缺口（逐机型）：**K=1 → C 型电池 +1 组**；**K=2 → B 型机 +1 架、C 型电池 +1 组**；**K=3 → B 型机 +1 架、C 型机 +1 架、C 型电池 +1 组**。中继机与中继能源组件三种分区下均**不缺**（2/2、3/6）。★ 中继唯一归属为**乐观口径**，须与结论并列说明 |

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
Get-Content docs\AGENT_GUIDE.md                    # ★★ 先读这个（位置索引 + 答案 + 思维链）
Get-Content docs\PROGRESS.md -TotalCount 60        # 进度与阻塞项
Select-String -Path docs\PROGRESS.md -Pattern '\[ \]'   # 未完成项
python scripts\verify_paper.py                     # 确认当前交付物状态
```

然后按 `docs/AGENT_GUIDE.md` 第五节的**优先级建议**继续；**每完成一小步就提交**（铁律 R1）。
