# 山区洪涝灾害下无人机运输与通信协同优化 —— 论文工程

2026 中国研究生数学建模竞赛 D 题的 LaTeX 论文工程。以 `MathAgent` 仓库的建模结果为数据源，
按国赛模板重写为可直接提交的论文，并补齐 draw.io 示意图与高级图表。

**编译入口**：双击 `build.cmd`（或 `xelatex → bibtex → xelatex ×2`），产物为 `document.pdf`。

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

> 本目录是**独立的论文工程**，不依赖仓库其余部分即可编译：
> `tables/`、`data/` 已是建模结果的快照，`figures/` 是已导出的成图。
> 重新生成图表或复算需回到仓库根目录运行求解程序。

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
| 参考文献显示为 `[?]`，`bibtex` 报退出码 `-1073740940`（0xC0000374 堆损坏） | 本机 MiKTeX 25.12 的 `bibtex.exe` 在加载较大的 `.bst`（`gbt7714-*.bst` 约 88 KB）时会**堆损坏崩溃**，`.bbl` 写不出来。实测 `gbt7714-numeric` 等样式均会触发，且**间歇性**（同样输入时成时不成） | `build.cmd` 已改为**优先使用 `bibtex8`**（实测 5/5 稳定），并内置最多 10 次重试作为兜底。手动排查：`bibtex8 document` |
| `book.bib` 必须**无 BOM** | 带 BOM 会让 bibtex 直接失败 | 用 `[IO.File]::WriteAllText($p, $s, (New-Object Text.UTF8Encoding($false)))` 写回 |

---

## 六、数据与结果来源

论文全部数值来自 `MathAgent` 仓库的求解输出，**未做任何手工改写**：

- Q1：18 架次（全 C 型）、75.07 kWh，逐服务区等于 Martello–Toth 解析下界 ⇒ 架次数可证最优
- Q2：16 架次（全 C 型，12 个多点串飞）、81.34 kWh、完工 5.73 h、准时率 51.3%；**物理类硬约束违规 0 条**
- Q3：运输 16 架次 + 中继 14 架次、覆盖 14/14、总能耗 91.68 kWh、联合完工 5.81 h
- Q4：2 个原子单元 ⇒ K=2 分区直接可行；K=1/2/3 资源总量 13/17/20

其中问题二的能耗与返航 SOC 另由 `code/verify_q2_energy.py` 与 `code/audit_q2_plan.py`
用 240 条航段缓存**独立复算**验证，与求解器上报值完全一致。
