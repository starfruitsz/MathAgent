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

---

## 2. 从 GitHub 克隆到 `scripts/tools/` 的工具

> 目前为空。**从 GitHub 拉取时执行以下步骤**：

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

---

## 4. 许可证合规备忘

- **可安全使用**：MIT / BSD-2 / BSD-3 / Apache-2.0
- **需谨慎**：LGPL（动态链接可用，静态嵌入需注意）
- **禁止直接嵌入交付代码**：GPL / AGPL —— 只能作为独立进程调用，并在论文中声明
- 任何 vendoring 必须保留上游 `LICENSE` 原文

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
| v1.0 | （F 题）建立工具清单骨架 | `725a092` |
| **v2.0** | **由 F 题改写为 D 题**：登记地理空间栈（rasterio/geopandas/shapely/pyproj/scikit-image）与运筹栈（ortools/networkx/pymoo/cvxpy），新增"明确不采用的工具及理由"一节 | 本次提交 |
