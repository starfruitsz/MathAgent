# 外部工具清单（TOOLS）

> **规范（OPS_SPEC 第 5.1 节）**：每引入一个工具，必须在下表登记名称、来源 URL、版本/commit、许可证、用途、是否修改源码。
> 从 GitHub 克隆的工具需记录**上游 commit hash**，并保留原始 `LICENSE` 文件。

---

## 1. 通过 PyPI 安装的工具

| 工具 | 来源 URL | 版本 | 许可证 | 用途 | 对应问题 | 是否改源码 |
|---|---|---|---|---|---|---|
| numpy | https://github.com/numpy/numpy | 2.4.4 | BSD-3 | 数值计算 | 全部 | 否 |
| scipy | https://github.com/scipy/scipy | 1.17.1 | BSD-3 | 优化/拟合/统计 | Q2 Q3 | 否 |
| pandas | https://github.com/pandas-dev/pandas | 3.0.2 | BSD-3 | 数据处理 | 全部 | 否 |
| pyarrow | https://github.com/apache/arrow | 25.0.1 | Apache-2.0 | Parquet/列式存储 | 全部 | 否 |
| statsmodels | https://github.com/statsmodels/statsmodels | 0.15.0 | BSD-3 | 回归诊断/假设检验 | Q2 Q4 | 否 |
| scikit-learn | https://github.com/scikit-learn/scikit-learn | 1.8.0 | BSD-3 | 回归/交叉验证/度量 | Q1 Q2 | 否 |
| lmfit | https://github.com/lmfit/lmfit-py | 1.3.4 | BSD-3 | 非线性最小二乘 + 参数置信区间 | Q2 | 否 |
| iminuit | https://github.com/scikit-hep/iminuit | 2.33.0 | MIT | Hessian 误差估计（备选） | Q2 | 否 |
| pymoo | https://github.com/anyoptimization/pymoo | 0.6.2 | Apache-2.0 | 多目标/全局优化 | Q3 | 否 |
| cvxpy | https://github.com/cvxpy/cvxpy | 1.9.3 | Apache-2.0 | 凸优化与 KKT 检验 | Q3 | 否 |
| dowhy | https://github.com/py-why/dowhy | 0.14 | MIT | 因果图与效应识别 | Q4 | 否 |
| econml | https://github.com/py-why/econml | 0.17.0 | MIT | 双重机器学习（DML） | Q4 | 否 |
| mapie | https://github.com/scikit-learn-contrib/MAPIE | 1.5.0 | BSD-3 | 保形预测区间 | Q4 | 否 |
| powerlaw | https://github.com/jeffalstott/powerlaw | 2.0.0 | MIT | 幂律拟合与拟合优度比较 | Q2 | 否 |
| matplotlib | https://github.com/matplotlib/matplotlib | 3.10.9 | PSF-based | 绘图 | 全部 | 否 |
| seaborn | https://github.com/mwaskom/seaborn | 0.13.2 | BSD-3 | 统计可视化 | 全部 | 否 |
| PyYAML | https://github.com/yaml/pyyaml | 6.0.3 | MIT | 配置文件 | 全部 | 否 |
| tqdm | https://github.com/tqdm/tqdm | 4.70.1 | MIT/MPL-2.0 | 进度条 | 全部 | 否 |
| joblib | https://github.com/joblib/joblib | 1.5.3 | BSD-3 | 并行与缓存 | 全部 | 否 |
| pytest | https://github.com/pytest-dev/pytest | 9.1.1 | MIT | 单元测试 | 全部 | 否 |

**验证状态**：以上 20 个包已在 **Python 3.13.7 / Windows 11 / AMD64** 环境下
**全部安装成功且导入通过**（`python scripts/check_env.py` 返回 `status: ok`）。
精确版本已锁进 `requirements.txt`，完整依赖树见 `requirements.lock.txt`。

> **重要结论**：`dowhy` / `econml` / `cvxpy` / `pymoo` 这几个偏冷门的库
> 在 Python 3.13 下均**无需降级 Python 或替换工具**，环境层无阻塞项。

---

## 2. 从 GitHub 克隆到 `scripts/tools/` 的工具

> 目前为空。**从 GitHub 拉取时执行以下步骤**：

```powershell
cd C:\Users\28447\Desktop\数学建模\MathAgent\scripts\tools
git clone --depth 1 https://github.com/<owner>/<repo>.git
cd <repo>
git rev-parse HEAD          # ★ 记录 commit hash
cd ..
Remove-Item -Recurse -Force <repo>\.git   # 避免嵌套仓库
```

| 工具 | 来源 URL | 上游 commit | 许可证 | 用途 | 是否改源码 |
|---|---|---|---|---|---|
| （暂无） | | | | | |

---

## 3. 许可证合规备忘

- **可安全使用**：MIT / BSD-2 / BSD-3 / Apache-2.0
- **需谨慎**：LGPL（动态链接可用，静态嵌入需注意）
- **禁止直接嵌入交付代码**：GPL / AGPL —— 只能作为独立进程调用，并在论文中声明
- 任何 vendoring 必须保留上游 `LICENSE` 原文

---

## 4. 参考开源实现（仅参考思路，不纳入依赖）

| 主题 | 参考仓库 | 借鉴点 |
|---|---|---|
| 数据配比即回归（RegMix 思路） | https://github.com/sail-sg/regmix | 凸组合搜索配比 → 损失 |
| 标度律拟合 | https://github.com/DeqingFu/scaling-laws | 幂律 + 不可约损失的拟合方式 |
| 成分数据变换（CLR/ILR） | https://github.com/scikit-learn/scikit-learn（`compose` 变换自实现） | 单纯形约束下的回归 |
| 变点检测 | https://github.com/deepcharles/ruptures | Q3 结构性转移的独立验证 |

> 参考实现**必须在论文中标注来源**，且不得以其输出作为学术依据（须引用正式文献）。

---

## 5. 变更记录

| 日期 | 变更 | 提交 |
|---|---|---|
| 初始 | 建立工具清单骨架，登记核心栈 | `<commit>` |
