# 山区洪涝灾害下无人机运输与通信协同优化 —— 论文工程

2026 中国研究生数学建模竞赛 D 题的 LaTeX 论文工程。以本仓库的建模结果为数据源，
按国赛模板重写为可直接提交的论文，并补齐 draw.io 示意图与高级图表。

**编译入口**：双击 `build.cmd`（或 `xelatex → bibtex → xelatex ×2`），产物为 `document.pdf`。
依赖 XeLaTeX（MiKTeX / TeX Live 均可）与 `gbt7714` 参考文献样式。

> 本目录是**独立的论文工程**，不依赖仓库其余部分即可编译：
> `tables/`、`data/` 已是建模结果的快照，`figures/` 是已导出的成图。
> 重新生成图表或复算需回到仓库根目录运行求解程序。

---

## 一、目录结构

| 目录 / 文件 | 说明 |
|---|---|
| `document.tex` | 论文入口（CUMCM 模板），逐章 `\input{texfile/*}` |
| `texfile/` | 各章正文（摘要 / 重述 / 分析 / 假设 / 建模 / 检验 / 评价 / 附录） |
| `texfile/tab_*.tex` | 三线表，**由 `code/make_tables.py` 从 CSV 自动生成**，勿手工改 |
| `figures/` | 全部插图（38 张），PNG 供排版 + PDF 矢量备份 |
| `diagrams/` | 5 个**可编辑** `.drawio` 源文件（技术路线图 + 四张流程图）及 `content.json` |
| `tables/` | 全部表格数据源（CSV），来自仓库 `paper/tables` 与 `outputs/qN/tables` |
| `data/` | 建模就绪数据、四问 metrics/params、独立复算与审计结果 |
| `code/` | 全部绘图、复算、制表脚本 |
| `results/` | 按赛题《结果提交模板》生成的 6 个交付 sheet（xlsx + csv） |
| `book.bib` | 16 条参考文献，全部经 DOI 反查核验 |
| `cumcmthesis.cls` | 国赛论文文档类 |

---

## 二、常用命令

```bat
build.cmd                                   :: 一键编译论文
```

```powershell
# 重新生成全部图表与表格
python code\fig_common.py     # 总体分析 + 公共模型章图（fig06–fig12）
python code\fig_q1.py         # 问题一图（fig13–fig19）
python code\fig_q2.py         # 问题二图（fig20–fig25）
python code\fig_q3.py         # 问题三图（fig26–fig31）
python code\fig_q4.py         # 问题四图（fig32–fig35）
python code\fig_check.py      # 检验 / 审计 / 汇总图（fig36–fig38）
python code\make_tables.py    # 由 CSV 生成 LaTeX 三线表
python code\make_submission.py# 生成结果提交文件

# 重新生成 draw.io 示意图（改完 spec 后需导出）
python code\make_flowcharts.py
# 导出：见下方"示意图导出"
```

---

## 三、示意图导出

`.drawio` 是可编辑源文件；改完后需用 draw.io 桌面版重新导出 PNG/PDF。
若已安装桌面版（命令行在 PATH 上），可这样批量导出：

```powershell
$d = "draw.io"          # 或 draw.io.exe 的完整路径
foreach ($f in Get-ChildItem diagrams\*.drawio) {
  & $d -x -f png -s 2 -b 0 -o ([IO.Path]::ChangeExtension($f.FullName,'.png')) $f.FullName
  & $d -x -f pdf --crop  -o ([IO.Path]::ChangeExtension($f.FullName,'.pdf')) $f.FullName
}
```

导出后需把 `diagrams\f00_roadmap.png` 复制为 `figures\fig01_roadmap.png`，
把 `f01..f04_flow.png` 依次复制为 `figures\fig02..fig05_flow_q1..q4.png`。
没有安装 draw.io 时，也可用其网页版（app.diagrams.net）打开 `.drawio` 后 File → Export as。

> 运行时终端会打印一串 `Unable to move the cache` —— 那是 Electron 的缓存告警，
> **不影响导出**，只要末尾出现 `xxx.drawio -> xxx.png` 即为成功。

---

## 四、绘图约定

- 全局样式在 `code/plotstyle.py`：中文字体 **SimSun**、统一调色板、`savefig.dpi = 330`。
- `plotstyle.fs((w, h))` 把画布缩到 **0.72 倍**。原因：图按 `0.98\textwidth`（≈6.3 in）排入 A4，
  若在 11.6 in 画布上作图，缩印后 7 pt 的字只剩约 4 pt 不可读；缩画布、不缩字号才是纸面真实字号。
- `save()` 会做**缺字自检**，若用了 SimSun 没有的字形（如 `⇒` `⁻` `↔`）会打印警告——
  应改用数学模式（`$\Rightarrow$`、`$\mathrm{km^{-1}}$`、`$\leftrightarrow$`），否则打印出来是方框。
- 图注只写短图题（≤20 字），**解读一律写进正文**并用 `\ref{}` 引用图号。

---

## 五、已知环境问题

| 现象 | 原因 | 处理 |
|---|---|---|
| 参考文献显示为 `[?]`，`bibtex` 报退出码 `-1073740940`（0xC0000374 堆损坏） | MiKTeX 的 `bibtex.exe` 加载较大的 `.bst`（`gbt7714-*.bst` 约 88 KB）时会**堆损坏崩溃**，`.bbl` 写不出来，且**间歇性**（同样输入时成时不成）；实测 10 个 gbt7714 变体均会触发 | `build.cmd` 已改为**优先使用 `bibtex8`**（实测连跑 5 次全稳），并保留最多 10 次重试兜底。手动排查：`bibtex8 document` |
| `book.bib` 必须**无 BOM** | 带 BOM 会让 bibtex 直接失败 | 用 `[IO.File]::WriteAllText($p, $s, (New-Object Text.UTF8Encoding($false)))` 写回 |

---

## 六、数据与结果来源

论文全部数值来自本仓库（即上一级目录）的求解输出，**未做任何手工改写**：

- Q1：18 架次（全 C 型）、75.07 kWh，逐服务区等于 Martello–Toth 解析下界 ⇒ 架次数可证最优
- Q2：25 架次（A 型 8 + B 型 10 + C 型 7，8 架无人机全部使用）、77.30 kWh、完工 3.02 h（10855.1 s）、期望送达准时率 100.0%（80/80 箱按时送达，首批违规 0 箱、期望违规 0 箱）；独立校验器 **违规 0 条**。质量装载率 71% → **79%**，理论下界 24 架次（单轮容量 320 kg，总需求 758 kg），25 架次仅高 1 个。架次数压缩靠「真实调度器 0 违规」硬前提下的逐候选合并复核（`consolidate_real`），**不是**调高架次权重——权重法虽能到 25 架次却留下 4 箱超期（准时率 95.0%）而代理目标看不见（`violation_point` = 1 与 1e3 结果逐位相同）；另修复 `local_search` relocate 走法缺失 `frozen` 判断的缺陷（会把货箱搬出首批专架次）。旧版"首批保障时限物理不可行"系机队坍缩（仅用 2 架 C 型）＋派发退化（无违规时按能耗打破平局）两处建模缺陷所致，现已证伪
- Q3：运输 25 架次 + 中继 **6 架次**（20/25 = 80.0% 需中继）、**时间轴覆盖率 11/20 = 55.0%**、总能耗 **79.65 kWh**（运输 77.30 + 中继 **2.35**，中继占 3.0%）、联合完工 **3.05 h（10968.7 s）**、平均直连中断占比 28.4%；独立校验**硬违规 0 条 + 42 条软违规**（均为「中继资源不足」）
- ⚠️ **两个覆盖率口径不可混用（ADR-031 / ADR-032）**：**几何可达覆盖率 = 20/20 = 100%** 只回答"是否存在合适的悬停点"；**时间轴覆盖率 = 11/20 = 55.0%** 才回答"中继那一刻在不在站"，是**唯一可上报口径**。题目仅给 **2 架**中继（可用能量 2.56 kWh ÷ 服务功率 1.10 kW ⇒ **在站时长上限约 140 min**，而 20 个架次真实中断合计约 168.5 min、最大并发 6 架次）⇒ **中继资源缺口 4 架**，属题目内在缺口，应如实报告。**不得**把几何可达当作"已保障"上报
- Q4：3 个连通分量（原子单元：{S010}、{S014}、含 13 个服务区的主分量）⇒ K=2 与 K=3 均**零架次改动**可行；桥接架次 6 个（T019、T017、T018、T021、T024、T025）；K=1/2/3 资源总量 **33/34/38**，组间不均衡度 0/1.8517/2.7035，最大组工作量 13.95/13.43/13.00 h；★ **最关键的缺口是中继**（库存 2 架 vs 需 4~5 架），三种分区下都存在；其余为 A/B/C 三型共享电池各缺 1 组（K=1），K=2 另缺 1 架 B 型运输机，K=3 再缺 1 架 B 型运输机 + 1 组 B 型电池

其中问题二的能耗与返航 SOC 另由 `code/verify_q2_energy.py` 与 `code/audit_q2_plan.py`
用 240 条航段缓存**独立复算**验证，与求解器上报值完全一致。
