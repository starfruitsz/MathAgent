# 外部工具清单（TOOLS）— D 题

> **规范（OPS_SPEC_D题 第 9 节 / ADR-009）**：每引入一个工具，必须在下表登记
> 名称、来源 URL、版本/commit、许可证、用途、是否修改源码。
> 从 GitHub 克隆的工具需记录**上游 commit hash**，并保留原始 `LICENSE` 文件。

---

## 1. 通过 PyPI 安装的工具（全部实测通过）

> 环境：**Python 3.13.7 / Windows 11 / AMD64**
> 验证方式：`python scripts/check_env.py` → `status: ok`（全部安装 + 导入通过）

### 1.1 数值与数据

| 工具 | 来源 URL | 版本 | 许可证 | 用途 | 对应问题 |
|---|---|---|---|---|---|
| numpy | https://github.com/numpy/numpy | 2.4.4 | BSD-3 | 数值计算 | 全部 |
| scipy | https://github.com/scipy/scipy | 1.17.1 | BSD-3 | 优化 / 求根（`brentq`）/ 统计 | 全部 |
| pandas | https://github.com/pandas-dev/pandas | 3.0.2 | BSD-3 | 数据处理 | 全部 |
| pyarrow | https://github.com/apache/arrow | 25.0.1 | Apache-2.0 | **`leg_cache.parquet` 读写** | 全部 |

### 1.2 地理空间（★ D 题新增，核心）

| 工具 | 来源 URL | 版本 | 许可证 | 用途 | 对应问题 |
|---|---|---|---|---|---|
| rasterio | https://github.com/rasterio/rasterio | 1.5.1 | BSD-3 | **★ DEM 栅格读写与采样** | `geo/` 全部 |
| geopandas | https://github.com/geopandas/geopandas | 1.1.4 | BSD-3 | 矢量数据与空间连接 | `geo/` |
| shapely | https://github.com/shapely/shapely | 2.1.2 | BSD-3 | 几何运算（LineString 视线） | `geo/los.py` |
| pyproj | https://github.com/pyproj4/pyproj | 3.8.0 | MIT | **★ 坐标投影（经纬度 → 米制）** | `geo/crs.py` |
| scikit-image | https://github.com/scikit-image/scikit-image | 0.26.0 | BSD-3 | 沿线采样（Bresenham）、栅格处理 | `geo/dem.py` |

**已验证**：`PROJ 9.8.1` 可用，`CRS.from_epsg(4326)` 正常 → 投影变换可正常工作。
这是**计算水平距离与 DEM 采样**的前提（见规范 2.3 节）。

### 1.3 运筹与优化（★ D 题新增，核心）

| 工具 | 来源 URL | 版本 | 许可证 | 用途 | 对应问题 |
|---|---|---|---|---|---|
| ortools | https://github.com/google/or-tools | 9.15.6755 | Apache-2.0 | **★ VRP / CP-SAT：路径与调度求解** | Q1 Q2 Q3 |
| pymoo | https://github.com/anyoptimization/pymoo | 0.6.2 | Apache-2.0 | 多目标进化（Pareto 前沿） | Q1 Q2 Q3 |
| cvxpy | https://github.com/cvxpy/cvxpy | 1.9.3 | Apache-2.0 | 凸优化（松弛下界） | Q2 Q3 |
| networkx | https://github.com/networkx/networkx | 3.7 | BSD-3 | 服务区图、依赖图、拓扑序 | Q2 Q3 Q4 |

### 1.4 统计与不确定

| 工具 | 来源 URL | 版本 | 许可证 | 用途 | 对应问题 |
|---|---|---|---|---|---|
| statsmodels | https://github.com/statsmodels/statsmodels | 0.15.0 | BSD-3 | 回归诊断、假设检验 | Q1 敏感性 |
| scikit-learn | https://github.com/scikit-learn/scikit-learn | 1.8.0 | BSD-3 | 聚类（Q4 分区备选）、度量 | Q4 |
| lmfit | https://github.com/lmfit/lmfit-py | 1.3.4 | BSD-3 | 非线性拟合 + 参数置信区间 | Q1 敏感性 |
| iminuit | https://github.com/scikit-hep/iminuit | 2.33.0 | MIT | Hessian 误差估计（备选） | Q1 |
| mapie | https://github.com/scikit-learn-contrib/MAPIE | 1.5.0 | BSD-3 | 保形预测区间（一般用不到） | 备选 |
| dowhy | https://github.com/py-why/dowhy | 0.14 | MIT | 因果识别（一般用不到） | 备选 |
| econml | https://github.com/py-why/econml | 0.17.0 | MIT | 双重机器学习（一般用不到） | 备选 |
| powerlaw | https://github.com/jeffalstott/powerlaw | 2.0.0 | MIT | 幂律拟合（一般用不到） | 备选 |

### 1.5 可视化

| 工具 | 来源 URL | 版本 | 许可证 | 用途 | 对应问题 |
|---|---|---|---|---|---|
| matplotlib | https://github.com/matplotlib/matplotlib | 3.10.9 | PSF-based | 静态图（论文主图） | 全部 |
| seaborn | https://github.com/mwaskom/seaborn | 0.13.2 | BSD-3 | 统计可视化 | 全部 |
| folium | https://github.com/python-visualization/folium | 0.20.0 | MIT | **交互式地图（路线/悬停点展示）** | Q2 Q3 Q4 |

### 1.6 工程与测试

| 工具 | 来源 URL | 版本 | 许可证 | 用途 |
|---|---|---|---|---|
| PyYAML | https://github.com/yaml/pyyaml | 6.0.3 | MIT | 配置文件 |
| tqdm | https://github.com/tqdm/tqdm | 4.70.1 | MIT/MPL-2.0 | 进度条 |
| joblib | https://github.com/joblib/joblib | 1.5.3 | BSD-3 | 并行与缓存 |
| pytest | https://github.com/pytest-dev/pytest | 9.1.1 | MIT | 单元测试 |
| python-docx | https://github.com/python-openxml/python-docx | 1.2.0 | MIT | 生成论文 docx |
| pywin32 | https://github.com/mhammond/pywin32 | — | PSF-based | Word COM：页数统计、PDF 导出 |
| tabulate | https://github.com/astanin/python-tabulate | 0.10.0 | MIT | `DataFrame.to_markdown` |
| **docx-equation** | https://pypi.org/project/docx-equation/ | **0.3.0** | **MIT** | ★ **OMML → MathType（`Equation.DSMT4`）公式对象转换** |
| PyMuPDF | https://github.com/pymupdf/PyMuPDF | — | AGPL-3.0 / 商业双许可 | **仅开发期**用于排版体检（逐页留白量测、页面转 PNG）；**不进入交付代码、不参与建模** |
| Pillow | https://github.com/python-pillow/Pillow | — | MIT-CMU | 图片尺寸读取（图高控制） |

### 1.7 ★ 公式排版工具链（MathType）

> 要求：论文公式（含正文嵌入与表格嵌入）必须用 **MathType** 生成。

| 环节 | 工具 | 说明 |
|---|---|---|
| 公式书写 | 本仓库 `src/report/equations.py` | 类 LaTeX 语法（`\frac{}{}`、`_{}`、`^{}`、`\sum_{}^{}`、`\rho`…）→ **OMML**（Word 原生可编辑公式） |
| OMML → MathML | `C:\Program Files\Microsoft Office\root\Office16\OMML2MML.XSL` | **随 Microsoft Office 安装**，Apache-2.0；上游固定版本见 `github.com/chang-shuai/omml2mml` @ `55edcfd`，SHA-256 `FF1A7184…49DEB` |
| MathML → MTEF | `docx-equation` 0.3.0（MIT） | 生成 `Equation.DSMT4` OLE 对象 + PNG 预览图 |
| 浏览器（渲染预览图） | Microsoft Edge（Chromium 内核） | `docx-equation` 需要 Chromium 渲染 MathML；库只按 PATH 名查找，Windows 默认安装路径需由本仓库显式注入（见 `equations.find_browser()`） |
| MathType 本体 | MathType 9+（`C:\Program Files (x86)\MathType\MathType.exe`） | 阅读/编辑公式对象；`ProgID = Equation.DSMT4` |

**参数标定**：预览图缩放 `preview_pt_per_px = 0.23`。
标定过程与依据见 `scripts/diag/line_heights.py`（逐行量测墨迹高度，300 dpi）：
12 pt 字号的公式基字高约 49 px → 0.23 pt/px，使行内公式与正文相称。

> ⚠️ **该库的预览图渲染有缺陷（必须修正）**：它把 `mml:math` 原样嵌入 HTML，
> 而 HTML 解析器不做命名空间解析，公式会退化成"一行普通文字"（上下标/分式全丢）。
> 本仓库在转换后用 `equations.render_previews()` + `reembed_previews()` 重绘并写回 docx。

**合规说明**：只使用 **MIT** 许可的 `docx-equation`。另外调研过的
`biyu0608/mathtype-word-equations-skill` 为 **AGPL-3.0**，
**未纳入本仓库、未复制其代码**（AGPL 只允许作为独立进程调用，不可 vendoring）。

## 2. 从 GitHub 克隆到 `scripts/tools/` 的工具

> 目前为空（`scripts/tools/` 仅有 `.gitkeep`）。**从 GitHub 拉取时执行以下步骤**：

```powershell
cd C:\Users\28447\Desktop\数学建模\MathAgent\scripts\tools
git clone --depth 1 https://github.com/<owner>/<repo>.git
cd <repo>
git rev-parse HEAD                        # ★ 记录 commit hash
cd ..
Remove-Item -Recurse -Force <repo>\.git   # 避免嵌套仓库
```

| 工具 | 来源 URL | 上游 commit | 许可证 | 用途 | 是否改源码 |
|---|---|---|---|---|---|
| （暂无） | | | | | |

---

## 3. 明确**不采用**的工具及理由

| 工具 | 不采用的理由 |
|---|---|
| `richdem` | Python 3.13 支持风险高、编译依赖重；`rasterio` + `scikit-image` 已足够做沿线采样与视线判定 |
| `elevation` | **需要联网下载 SRTM 瓦片** —— 与"不得引入其他数据"的红线冲突；且附件已直接提供 DEM |
| `vrpy` | 依赖重、版本兼容风险；本题约束高度定制（充电周转、连续通信、载荷递减），通用 VRP 库收益有限 |
| `contextily` / 在线底图库 | 需联网拉取底图瓦片，**离线不可用**且引入外部数据；用 `folium` + 本地 DEM 出图即可 |
| `mathtype-word-equations-skill` | 许可证为 **AGPL-3.0**，不可 vendoring；其功能已由 MIT 许可的 `docx-equation` 覆盖 |
| `latex2mathml` / `pylatexenc` | 已用自研 `equations.py` 覆盖本题所需语法，避免重复依赖与口径分叉 |

---

## 4. 许可证合规备忘

- **可安全使用**：MIT / BSD-2 / BSD-3 / Apache-2.0
- **需谨慎**：LGPL（动态链接可用，静态嵌入需注意）；**AGPL**（只能外部进程调用、不可复制代码）
- **禁止直接嵌入交付代码**：GPL / AGPL —— 只能作为独立进程调用，并在论文中声明
- 任何 vendoring 必须保留上游 `LICENSE` 原文
- ★ **本项目仅把 PyMuPDF（AGPL）用于开发期排版体检**，其输出（PNG/统计）不参与建模，
  也未将其代码并入 `src/`；正式交付物只依赖 MIT / BSD / Apache 许可组件

---

## 5. 参考实现（仅参考思路，不纳入依赖）

| 主题 | 参考 | 借鉴点 |
|---|---|---|
| 无人机配送 VRP | Dorling et al. 2017（题目参考文献 [4]） | 多趟次无人机路径问题建模 |
| 无人机能耗模型 | Zhang et al. 2021（题目参考文献 [5]） | 载荷-能耗关系与对比评估 |
| 自由空间衰减 | ITU-R P.525-5（题目参考文献 [6]） | FSPL 公式的权威出处 |
| 无人机通信 | Zeng et al. 2016（题目参考文献 [8]） | 悬停/轨迹与通信的联合优化 |
| DEM 数据 | Copernicus DEM（题目参考文献 [3]） | 30 m DEM 的来源与精度 |
| 充电两阶段模型 | TI SLAA287B（题目参考文献 [7]） | 锂电池 CC/CV 充电曲线 |

> 参考实现**必须在论文中标注来源**，且不得以其输出作为学术依据（须引用正式文献）。

---

## 6. 变更记录

| 日期 | 变更 | 提交 |
|---|---|---|
| v2.0 | 建立 D 题工具清单：登记地理空间栈（rasterio/geopandas/shapely/pyproj/scikit-image）与运筹栈（ortools/networkx/pymoo/cvxpy），新增"明确不采用的工具及理由"一节 | `9f6201a` |
| **v2.1** | 归档目录更名为 `docs/legacy_D题/`，本文件随规范同步（工具清单本身无变化） | 本次提交 |
| **v3.0** | ★ 新增 1.7 节**公式排版工具链（MathType）**：`docx-equation`(MIT) + Office 自带 `OMML2MML.XSL`(Apache-2.0) + Edge 渲染预览；登记预览图缩放标定值 0.32 pt/px；补充 `python-docx`/`pywin32`/`tabulate`/`PyMuPDF`/`Pillow`；新增不采用项（AGPL 的 `mathtype-word-equations-skill` 等）与 AGPL 使用边界说明 | 本次提交 |
