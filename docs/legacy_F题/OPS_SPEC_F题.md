# F 题操作规范（OPS SPEC）
## 算力约束下提升大语言模型能力的资源配置建模

> **文件定位**：本文件是 F 题全部建模工作的**唯一操作规范（single source of truth）**。
> 任何 agent（人或 AI）在动手之前必须先完整读完本文件，并严格遵守第 1 节的提交铁律。
>
> **远程仓库**：https://github.com/starfruitsz/MathAgent.git
> **仓库本地路径**：`C:\Users\28447\Desktop\数学建模\MathAgent`
> **规范版本**：v1.0
> **适用赛题**：2026 年中国研究生数学建模竞赛 F 题

---

## 0. 铁律速查（TL;DR）

| # | 规则 | 违反后果 |
|:--:|---|---|
| **R1** | **每次更改代码必须提交仓库。** 改完即 `commit`，`commit` 后即 `push`。禁止累积多次改动后再一次性提交。 | 视为任务未完成 |
| **R2** | **本规范文件本身如有修改，也必须提交并推送至仓库。** | 视为任务未完成 |
| **R3** | 原始数据 `data/raw/**` **只读**，永不修改、永不删除。所有派生数据写入 `data/interim/` 或 `data/processed/`。 | 数据不可追溯，返工 |
| **R4** | 每问**必产出** `outputs/qN/metrics.json` + `params.json` + 图 + 表，缺一不可。 | 论文无据可写 |
| **R5** | 禁止把原始大数据集、模型权重、`__pycache__` 提交进仓库（见第 1.4 节）。 | 仓库膨胀 |
| **R6** | 所有随机过程必须固定种子（`SEED = 42`），结果必须可复现。 | 结果不可信 |
| **R7** | 允许使用开源库/预训练工具，但**必须**在论文与 `docs/` 中标注名称、版本号、核心参数。 | 学术规范扣分 |
| **R8** | 论文正文若使用 AI 工具，**必须在文末附录披露**；不得直接复制 AI 生成的建模方案。 | **一经查实取消参评资格** |

---

## 1. 版本控制与提交规范（最高优先级）

### 1.1 铁律 R1：每次更改代码必须提交仓库

> ### ⚠️ 每次更改代码必须提交仓库
>
> **这是一条不可协商的硬性要求，适用于每一个 agent、每一次修改、每一个文件。**
>
> - 修改了任何一个 `.py` / `.md` / `.ipynb` / `.yaml` / `.txt` / `.json` 文件 → **立刻** `git add` + `git commit` + `git push`
> - 修好一个 bug → 立刻提交
> - 调整了一个超参数 → 立刻提交
> - 新增一个绘图函数 → 立刻提交
> - **禁止**"等我全部写完再一起提交"
> - **禁止**留下未提交的工作区改动过夜（或过一个任务回合）
> - 提交信息必须写清**改了什么、为什么改**
>
> 提交前自检（必须全部为真才能收工）：
> ```powershell
> git status --porcelain   # 输出必须为空
> git log origin/main..HEAD --oneline   # 输出必须为空（即已全部推送）
> ```

### 1.2 标准提交流程

```powershell
# 在仓库根目录执行
cd C:\Users\28447\Desktop\数学建模\MathAgent

# 一键脚本（推荐，见 scripts/commit.ps1）
.\scripts\commit.ps1 -Scope q2 -Type model -Message "加入 Q=1 退化约束的广义标度律"

# 等价的手工流程
git add -A
git commit -m "model(q2): 加入 Q=1 退化约束的广义标度律"
git push origin main
```

**一键脚本 `scripts/commit.ps1`**（需在本仓库内创建，见第 6 节交付物清单）：

```powershell
param(
  [Parameter(Mandatory=$true)][string]$Message,
  [string]$Scope = "",
  [string]$Type  = "chore"
)
$ErrorActionPreference = 'Stop'
if (-not (Test-Path .git)) { throw "不在仓库根目录" }
$prefix = if ($Scope) { "$Type($Scope)" } else { $Type }
git add -A
if (-not (git status --porcelain)) { Write-Host "无改动，跳过提交"; exit 0 }
git commit -m "$prefix`: $Message"
git push origin main
if ($LASTEXITCODE -ne 0) { throw "push 失败：请检查网络与凭据" }
Write-Host "已提交并推送：$prefix`: $Message"
```

### 1.3 提交信息规范

格式：`<type>(<scope>): <简要说明>`

| type | 用途 |
|---|---|
| `feat` | 新增功能/脚本 |
| `fix` | 修复 bug |
| `data` | 数据处理与派生数据 |
| `model` | 模型/数学形式变更 |
| `exp` | 实验、调参、结果产出 |
| `doc` | 文档、论文、规范更新 |
| `repo` | 仓库结构、依赖、CI 等 |

| scope | 对应内容 |
|---|---|
| `q1` `q2` `q3` `q4` | 四个问题 |
| `q0` | 数据发现与公共层 |
| `spec` | 本规范文件 |
| `env` | 环境与依赖 |

示例：
- `feat(q0): 新增 raw 数据自动清点脚本，输出 data_inventory.json`
- `model(q1): 用 ILR 变换替代直接线性回归处理单纯形约束`
- `fix(q2): 修正 Q=1 时广义标度律未退化为经典形式的 bug`
- `exp(q3): 预算 10^19/10^22/10^24 三档求解并记录 KKT 乘子`
- `doc(spec): 补充结构性转移的数学定义`

### 1.4 提交边界（`data/raw/` 与产物分离）

仓库**只**纳入：代码、文档、配置、小体量结果（`outputs/**` 中 < 5 MB 的 csv/json/md/png）。

`.gitignore`（必须在仓库根目录存在）：

```gitignore
# ---- 环境 ----
__pycache__/
*.py[cod]
.venv/
venv/
.ipynb_checkpoints/
.env

# ---- 原始与中间数据（体积大，不入库）----
data/raw/**
data/interim/**
!data/raw/.gitkeep
!data/interim/.gitkeep

# ---- 大体积产物 ----
*.pkl
*.h5
*.hdf5
*.pt
*.pth
*.ckpt
*.parquet
*.zip
*.7z
large_files/

# ---- 规范：outputs 中的小文件要入库，大文件不入库 ----
outputs/**/*.tmp

# ---- 编辑器/系统 ----
.vscode/
.idea/
.DS_Store
Thumbs.db
```

> **注意**：`outputs/**` 的 `metrics.json` / `params.json` / `*.csv` / `*.png` 是**论文的证据链**，必须入库（体积通常很小）。只有超出 5 MB 的大中间产物才排除。

### 1.5 分支策略

- 主线：`main`，**始终可运行、可复现**。
- 允许临时分支 `feat/qN-xxx`，但**合并回 main 后必须推送**，并在最终交付前删除临时分支。
- 禁止 `git push --force` 到 `main`。
- 换机器/换 agent 接手前，先 `git pull --rebase origin main`。

### 1.6 接手与交接协议

**接手时**：
```powershell
cd C:\Users\28447\Desktop\数学建模\MathAgent
git pull --rebase origin main
# 读取进度
Get-Content docs\PROGRESS.md -TotalCount 60
# 查看未完成项
Select-String -Path docs\PROGRESS.md -Pattern '\[ \]'
```

**收工时**：必须更新 `docs/PROGRESS.md`，随后提交（这一步也受 R1 约束）。

---

## 2. 环境与依赖

### 2.1 Python 环境

- **Python ≥ 3.11**（3.12 亦可）
- 使用虚拟环境，禁止污染全局环境：

```powershell
cd C:\Users\28447\Desktop\数学建模\MathAgent
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
pip install -r requirements.txt
```

### 2.2 依赖清单

**必须在 `requirements.txt` 中锁定版本**（用 `==`，不用 `>=`）。核心栈：

```
# ---- 数值与数据 ----
numpy
scipy
pandas
pyarrow

# ---- 统计建模与回归 ----
statsmodels
scikit-learn
lmfit                # 带参数置信区间的非线性最小二乘（标度律拟合）
iminuit              # 备选：Hesse 误差估计

# ---- 优化 ----
pymoo                # 多目标/全局优化
cvxpy                # 凸优化与 KKT 检验（Q3 的凸化版本）

# ---- 不确定性与因果 ----
dowhy                # 因果图 + 效应估计（Q4）
econml               # 双重机器学习 DML（Q4）
mapie                # 保形预测，给出预测区间（Q4）

# ---- 幂律/标度律专用 ----
powerlaw             # 幂律拟合与拟合优度比较

# ---- 可视化 ----
matplotlib
seaborn

# ---- 实验管理 ----
pyyaml
tqdm
joblib

# ---- 测试 ----
pytest
```

> `requirements.txt` 的实际内容以 `scripts/check_env.py` 探测结果为准；**若某库安装失败或不存在，必须在本文件第 9 节"工具与依赖决策记录"中登记替代方案**，不得静默跳过。

### 2.3 环境自检

```powershell
python scripts\check_env.py
```
该脚本需输出：Python 版本、关键库版本、CPU 核数、可用内存，并写入 `outputs/env_report.json`。

---

## 3. 仓库目录结构（必须遵守）

```
MathAgent/
├── README.md                        # 仓库导航
├── OPS_SPEC_F题.md                  # ★ 本文件
├── requirements.txt                 # 锁定依赖版本
├── .gitignore
├── Makefile                         # 或 run_all.ps1：一键全流程复现
│
├── data/
│   ├── raw/                         # ★ 只读★ 竞赛官方附件（不入库）
│   │   ├── real_attachments/        #   题目所述 real_attachments/
│   │   ├── 数据说明.*               #   编号-文件名对照表（关键！）
│   │   └── .gitkeep
│   ├── interim/                     # 清洗后中间数据（不入库）
│   └── processed/                   # 建模就绪的派生数据（小文件可入库）
│
├── src/
│   ├── common/
│   │   ├── config.py                # 路径、SEED、全局常量
│   │   ├── io_utils.py              # 统一读写（csv/json/pkl）
│   │   ├── plotting.py              # 统一绘图风格（论文出图）
│   │   ├── metrics.py               # R²/RMSE/MAE/AIC/BIC/覆盖率
│   │   └── registry.py              # 运行记录与哈希
│   ├── q0_data/
│   │   ├── discover.py              # ★ 清点 raw 数据 → data_inventory.json
│   │   ├── validate.py              # 形状/缺失/重复/范围校验
│   │   └── map_codes.py             # A1–A18 / B1–B12 / C1–C10 编号映射
│   ├── q1_quality_mixture/
│   │   ├── preprocess.py            # 22 指标方向统一 + 多维列表压缩为标量
│   │   ├── quality_score.py         # 综合质量评分 Q（含聚合方式）
│   │   ├── conflict.py              # 冲突定义 + 消解规则
│   │   ├── mixture_model.py         # 17 域配比 → Loss 模型（单纯形约束）
│   │   ├── validate_extrapolate.py  # A6–A11 检验 / A12–A15 外推
│   │   └── run_q1.py                # 入口
│   ├── q2_scaling_law/
│   │   ├── classic_fit.py           # 经典标度律 B1 拟合（基线）
│   │   ├── generalized_law.py       # L(N,D,Q,p) 广义形式
│   │   ├── elasticity.py            # 边际效用/弹性/替代条件
│   │   ├── validate.py              # B2/B3 轨迹、B4/B5 跨族、B9/B10 外推
│   │   └── run_q2.py
│   ├── q3_optimization/
│   │   ├── cost_model.py            # 三项成本 + 三种 g(Q)
│   │   ├── optimize.py              # 预算约束下的联合优化（多起点全局）
│   │   ├── regime_shift.py          # ★ 结构性转移的定义与识别
│   │   ├── sensitivity.py           # L_ctx 敏感性 + L_ctx^crit=30000
│   │   └── run_q3.py
│   ├── q4_frontier/
│   │   ├── decompose.py             # 规模扩张 vs 非规模技术进步
│   │   ├── bridge.py                # Loss ↔ Benchmark 桥接映射
│   │   ├── forecast.py              # 12/24 个月前沿预测 + 不确定性
│   │   ├── causal.py                # DoWhy/EconML 因果分析
│   │   └── run_q4.py
│   └── report/
│       ├── make_tables.py           # 生成论文用 LaTeX/Markdown 表
│       └── make_figures.py          # 生成论文用矢量图
│
├── outputs/                         # ★ 证据链，小文件必须入库
│   ├── env_report.json
│   ├── data_inventory.json
│   ├── q1/{metrics.json,params.json,tables/*.csv,figures/*.png}
│   ├── q2/{...}
│   ├── q3/{...}
│   └── q4/{...}
│
├── scripts/
│   ├── commit.ps1                   # ★ 一键提交推送（第 1.2 节）
│   ├── check_env.py
│   ├── run_all.ps1                  # 端到端复现
│   └── tools/                       # 从 GitHub 拉取的外部工具（见第 5 节）
│       └── .gitkeep
│
├── docs/
│   ├── PROGRESS.md                  # ★ 进度看板（每次收工更新）
│   ├── DATA_NOTES.md                # 数据说明摘录与编号映射结论
│   ├── MODEL_NOTES.md               # 每问数学形式的推导与取舍
│   ├── TOOLS.md                     # 外部工具来源、版本、许可
│   ├── DECISIONS.md                 # 决策记录（ADR）
│   └── PAPER_OUTLINE.md             # 论文骨架与图表清单
│
└── tests/
    ├── test_q1.py
    ├── test_q2.py
    ├── test_q3.py
    └── test_q4.py
```

---

## 4. 数据协议

### 4.1 数据现实（开工前必读）

> **当前工作区 `C:\Users\28447\Desktop\数学建模` 内只有 6 份题目 Word 文档，没有任何附件数据。**
> F 题所需数据（`real_attachments/` 下的 A1–A18、B1–B12、C1–C10，以及《数据说明》）**必须先从竞赛官方渠道下载**，放入 `data/raw/`。

**因此，`src/q0_data/discover.py` 是所有工作的第一步，且是阻塞性前置任务。**

### 4.2 数据编号对照（题目已明确的必读信息）

| 编号段 | 用途 | 关键约束 |
|---|---|---|
| **A1–A3** | 质量信号数据（A1 抽样集，A2/A3 扩展集） | 质量评价**必须使用全量记录**；须给出域级 Q 并与 A1 抽样集结果对照 |
| **A4–A15** | 配方实验数据（17 域配比 ↔ 交叉熵损失） | A6–A11 为**检验集**；A12–A15 为**外推表**（配比表与 Loss 表须**成对使用**） |
| **A16** | 跨体系域分类参考映射 | 质量体系与配比体系域分类不同，须说明关联规则与假设 |
| **A18** | 质量评分验算（可选用） | — |
| **B1–B5** | 经典标度律数据 | B1 主拟合；B2 或 B3 之一做模型族外/插值轨迹验证；B4 与 B5 做跨族或文献验证 |
| **B6–B8** | **半合成补充集**（基于真实数据校准） | **可用于补充分析，但不得表述为直接实验观测**，须说明局限 |
| **B9–B10** | 百亿参数以上外推讨论 | 须标注可信度边界 |
| **B11–B12** | 辅助数据 | — |
| **C1–C2** | 模型评测数据（C1 或 C2） | Q4 须使用 |
| **C3** | 模型评测数据 | Q4 须使用 |
| **C4** | 模型元数据（算力、数据量、开源权重等字段） | Q4 须使用这些字段 |
| **C5–C6** | **Loss–Benchmark 桥接数据** | 须按**可比性等级**区分使用 |
| **C7** | **上下文长度 L_ctx 可行取值依据** | ★ Q3 的 L_ctx **外生给定**，可行取值**必须依据 C7** |
| **C8** | 逐任务评测明细 | Q4 须做**至少一项逐任务聚合分析**，**不得仅用汇总表** |
| **C10** | — | 待 `discover.py` 确认 |

> **行动项**：`discover.py` 运行后，必须把**实际磁盘文件名 ↔ 编号**的对照表写入 `docs/DATA_NOTES.md` 与 `data_inventory.json`。
> 题目原文已声明："若清单与实际磁盘文件不一致，**以实际文件为准**"。

### 4.3 数据处理五原则

1. **只读原则**：`data/raw/**` 永不写入。所有加工结果落到 `data/interim/` 或 `data/processed/`。
2. **可追溯原则**：每个派生文件必须在 `outputs/data_inventory.json` 中登记 `源文件 + 脚本 + git commit + 时间戳`。
3. **方向统一原则**：22 个质量指标全部转为"越高越好"。负向指标做补变换 `x' = 1 − MinMax(x)`，**并在代码注释与论文中逐一列明哪些指标被翻转**。
4. **类型归一原则**：多维列表型质量指标须先压缩为标量（`mean` / `norm` / 主成分第一分量），**压缩方式必须声明并做敏感性检验**。
5. **可信度标注原则**：B6–B8 半合成数据、B9–B10 估算数据，在数据表中**必须带 `credibility` 字段**，在论文中必须显式标注边界。

### 4.4 数据校验清单（每次读数据必做）

```python
# src/q0_data/validate.py 必检项
assert df.shape == expected_shape          # 形状
assert df.isna().sum().sum() == 0          # 缺失值（或说明填充策略）
assert not df.duplicated(subset=keys).any()# 重复记录
assert (p >= -1e-9).all()                  # 单纯形非负
assert abs(p.sum(axis=1) - 1) < 1e-6       # 单纯形归一
assert N.min() > 0 and D.min() > 0         # 正向性
assert (loss > 0).all()                     # 损失为正
```

---

## 5. 工具获取规范（GitHub 优先）

### 5.1 工具准入原则

1. **优先 PyPI 安装**（`pip install`），版本锁进 `requirements.txt`。
2. **需要私有化改造 / 无 PyPI 包 / 需要 vendoring 时**，才从 GitHub 克隆到 `scripts/tools/`。
3. **每引入一个工具，必须在 `docs/TOOLS.md` 登记**：

```
| 工具 | 来源 URL | 版本/commit | 许可证 | 用途 | 是否修改源码 |
|---|---|---|---|---|---|
| lmfit | https://github.com/lmfit/lmfit-py | 1.3.2 | BSD-3 | 标度律非线性拟合+置信区间 | 否 |
```

4. **许可证合规**：GPL/AGPL 类工具**不得**直接嵌入交付代码，只能作为独立进程调用并在论文中声明；**MIT/BSD/Apache-2.0 可安全使用**。
5. **vendoring 的代码必须保留原始 LICENSE 文件**，并在 `docs/TOOLS.md` 中记录上游 commit hash。

### 5.2 从 GitHub 拉取工具的标准命令

```powershell
cd C:\Users\28447\Desktop\数学建模\MathAgent\scripts\tools

# 方式一：浅克隆到固定 commit（推荐，可复现）
git clone --depth 1 https://github.com/<owner>/<repo>.git
cd <repo>
git rev-parse HEAD            # ★ 把 commit hash 记进 docs/TOOLS.md
cd ..

# 方式二：如果只是参考实现，不纳入依赖
#   则在 docs/TOOLS.md 记录 URL + commit，并在代码注释中标注参考来源
```

> ⚠️ **不要把上游仓库的 `.git` 目录提交进本仓库**（会成为嵌套仓库）。
> 克隆后执行 `Remove-Item -Recurse -Force <repo>\.git`，或把该路径加入 `.gitignore`。

### 5.3 候选工具（按需选用，用前先核实存在性与许可证）

| 用途 | 候选 | 来源 |
|---|---|---|
| 带置信区间的非线性最小二乘 | `lmfit` / `iminuit` | github.com/lmfit/lmfit-py · github.com/scikit-hep/iminuit |
| 单纯形/成分数据回归 | `scikit-learn` + 自实现 CLR/ILR；`composition_stats` | github.com/scikit-learn/scikit-learn |
| 全局/多起点非凸优化 | `scipy.optimize`（DE, basinhopping, dual_annealing） | github.com/scipy/scipy |
| 多目标优化 | `pymoo` | github.com/anyoptimization/pymoo |
| 凸优化与 KKT 检验 | `cvxpy` | github.com/cvxpy/cvxpy |
| 幂律拟合与模型比较 | `powerlaw` | github.com/jeffalstott/powerlaw |
| 因果推断 | `dowhy` / `econml` | github.com/py-why/dowhy · github.com/py-why/econml |
| 保形预测（预测区间） | `mapie` | github.com/scikit-learn-contrib/MAPIE |
| 变点/结构断点检测 | `ruptures` | github.com/deepcharles/ruptures |
| 贝叶斯回归与后验 | `pymc` 或 `statsmodels` 贝叶斯 | github.com/pymc-devs/pymc |
| 中文论文排版 | `pandoc` + LaTeX 模板 | 本地工具，非 GitHub |
| 数据质量/标注一致性 | `cleanlab`；Krippendorff α 自实现 | github.com/cleanlab/cleanlab |

> **注意**：本题**严禁引入任何其他公开或私有数据集**参与训练/微调/调参/阈值选择/结果统计（数据使用红线）。工具（算法库）可用，**数据不可换**。

---

## 6. 四问工作流（每问的输入 / 输出 / 验收）

> **通用要求**：每问产出 `outputs/qN/metrics.json`（评价指标）、`params.json`（模型参数估计值 + 标准误 + 置信区间）、`tables/*.csv`（论文表格源数据）、`figures/*.png + *.pdf`（矢量图）、`run_log.json`（git commit + 时间 + 耗时 + 随机种子）。

### 6.1 Q0：数据发现与公共层（阻塞性前置任务，最先做）

**输入**：`data/raw/**`
**输出**：`outputs/data_inventory.json`、`docs/DATA_NOTES.md`
**验收**：
- [ ] 列出 `real_attachments/` 下**全部**文件：路径、大小、扩展名、推测编号（A/B/C 段）
- [ ] 解析每个结构化文件的字段名、dtype、形状、缺失率、取值范围
- [ ] 生成**编号 ↔ 实际文件名对照表**（不一致处以实际文件为准并显式记录）
- [ ] 明确 **C7** 的真实内容（决定 Q3 中 L_ctx 的可行取值集合）
- [ ] 明确 **C5/C6** 的可比性等级字段
- [ ] 输出 `data/processed/` 下的统一建模接口文件

### 6.2 Q1：数据质量评价、冲突消解与领域配比建模

**输入**：A1–A3（质量信号）、A4–A15（配方实验）、A16（映射）、A18（验算）
**输出**：`outputs/q1/**`

**任务拆解**：

| 子任务 | 关键要求 | 建议方法 |
|---|---|---|
| 1a 质量评价 | 22 指标方向统一；多维列表压标量；给出样本级/语料级/领域级 Q；说明聚合方式；用**全量** A1+A2+A3；给出域级 Q 并与 A1 对照 | Min-Max 后负向取 `1−x`；熵权法/CRITIC/主成分；层次聚合（样本→语料→域） |
| 1b 冲突消解 | **定义"冲突"**（指标间显著不一致）、分析成因、建立消解规则；覆盖抽样集，在扩展集上检验 | 指标间秩相关矩阵 + 阈值判冲突；稳健聚合（中位数/截尾均值）；分组加权 |
| 1c 配比建模 | 建立 17 域配比 `p` → 交叉熵损失的定量关系；满足 `p_i≥0, Σp_i=1`；分析各域及组合影响；论证是否引入 Q | **ILR/CLR 变换 + 岭回归/GP**；或 RegMix 式凸组合搜索；单纯形上的正则化回归 |
| 1d 验证与外推 | A6–A11 检验；A12–A15 讨论外推稳健性 | 留出法 + 交叉验证；外推误差随偏离训练域的距离变化曲线 |

**验收**：
- [ ] 明确列出**被翻转方向的指标清单**及其原始定义
- [ ] "冲突"有**可计算的数学定义**（不能只是文字描述）
- [ ] 配比模型在 A6–A11 上的 R²/RMSE 报告完整
- [ ] A12–A15 外推结论有稳健性边界说明
- [ ] 质量体系 ↔ 配比体系的跨体系关联规则写入 `docs/MODEL_NOTES.md`

### 6.3 Q2：跨维度数据融合与广义标度律

**输入**：B1–B12 +（来自 Q1 的 Q、p）
**输出**：`outputs/q2/**`

**任务拆解**：

| 子任务 | 关键要求 |
|---|---|
| 2a 经典基线 | 用 B1 拟合 `L(N,D) = E + A·N^(−α) + B·D^(−β)`，报告参数 ± 标准误、R²、残差诊断 |
| 2b 广义标度律 | 构造含 **N, D, Q, p** 的 `L(N,D,Q,p)`；**建议**满足 `Q=1 且 p 均匀时退化为经典形式`（须说明依据） |
| 2c 弹性与边际效用 | 计算 ∂L/∂N、∂L/∂D、∂L/∂Q、∂L/∂p_i 与弹性系数；回答"同样多花一块钱，堆参数还是买好教材" |
| 2d 替代条件 | **推导可计算条件**："质量提升 0.1 等价于参数增加多少"——给出闭式或数值解法 |
| 2e 领域关系 | 分析领域间**替代 or 互补**关系（Hessian 交叉偏导符号） |
| 2f 验证 | B2 或 B3 之一（模型族外/插值轨迹）；B4 与 B5（跨族/文献）；B6–B8（半合成，标注局限）；B9–B10（百亿以上外推） |

**关键数学要求**：
- 附件 A 与附件 B 是**相互独立**的实验，却都以交叉熵损失为观测量 → **必须提出可检验的假设**把两者统一到同一模型
- 参数估计须给**置信区间**（bootstrap 或解析 Hessian）
- B6–B8 **不得表述为直接实验观测**

**验收**：
- [ ] Q=1 退化性有**数值验证**（代码断言 + 报告）
- [ ] 弹性系数的量级与物理意义解释清楚
- [ ] "质量 0.1 ↔ 参数增量"有**可复算的公式**与数值结果
- [ ] 所有验证数据源在 `metrics.json` 中分别列出

### 6.4 Q3：算力约束下的多维资源联合优化与结构性转移

**输入**：Q1 的 Q 与 p、Q2 的广义标度律、附录 B 的 g(Q) 参数、C7 的 L_ctx 可行取值
**输出**：`outputs/q3/**`

**成本模型（严格照抄题目）**：

```
C_total = C_train + C_Q + C_attn
C_train = 6 N D
C_Q     = D · [ g(Q) − g(Q0) ]⁺
C_attn  = η · N · D · L_ctx          ,  η = 2×10⁻⁴
约束    : C_total ≤ C ,  N>0, D>0, Q∈(0,1],  Σp_i=1, p_i≥0
```

**g(Q) 三选一（附录 B）**：

| 类型 | 形式 | 参数 |
|---|---|---|
| 指数型 | `g(Q) = γ e^{λQ}` | γ = 10⁷, λ = 6.0 |
| 幂函数型 | `g(Q) = γ Q^λ` | γ = 5×10⁹, λ = 4.0 |
| 对数渐进型 | `g(Q) = γ ln(1+λQ)` | γ = 2×10⁹, λ = 10.0 |

**任务拆解**：

| 子任务 | 关键要求 |
|---|---|
| 3a 优化模型 | 建立 `min L(N,D,Q,p) s.t. C_total ≤ C`；明确 p 是联立决策变量还是取前两问结果，**并说明理由** |
| 3b 预算扫描 | 至少三档：`C = 10¹⁹, 10²², 10²⁴` FLOPs（可加密） |
| 3c 成本函数影响 | 三种 g(Q) 分别求解并对比最优配置的差异 |
| 3d **结构性转移** | ★ 给出**明确的数学定义与识别方法**（见下） |
| 3e L_ctx 敏感性 | **解析给出** `L_ctx^crit = 6/η = 3×10⁴`，并在 **C7 的可行取值**上做敏感性分析 |

**结构性转移的数学定义（本问的核心得分点，须在论文中写成正式定义）**：

> **定义（结构性转移）**：设预算 `C` 的最优资源配置映射为 `C ↦ x*(C) = (N*, D*, Q*, p*)`。
> 若存在 `C₁ < C₂`，使得在 `(C₁, C₂)` 上 `x*(C)` 的**激活约束集合**发生变化
> （即 KKT 乘子中非零分量的支撑集改变），或最优解在**资源分配的主导维度**上发生切换
> （例如从"以扩参数为主导"转为"以提质量为主导"，可用弹性符号 `∂ln N*/∂ln C` 与 `∂ln Q*/∂ln C` 的相对大小刻画），
> 则称该预算区间内发生了**结构性转移**，转移点 `C*` 为该区间的分界。

**识别方法（须全部实现）**：
1. **网格扫描**：在 `log₁₀C ∈ [15, 27]` 上细密求解，记录 `(N*, D*, Q*, p*, 激活约束集, KKT 乘子)`
2. **弹性比值曲线**：绘制 `∂ln N*/∂ln C` 与 `∂ln Q*/∂ln C`，找符号/主序变化点
3. **激活集变化点**：记录每个约束的 KKT 乘子，标注其由 0 变正（或反之）的预算
4. **断点检测**：对 `(N*, D*, Q*)` 序列用 `ruptures` 做变点检测交叉验证
5. **解析补充**：在可解析的简化情形（如仅有 `C_train + C_attn` 两项、`L` 为幂律和）下给出**闭式解**，验证数值结论

> ⚠️ **低预算区必须加密**：预研（见 `docs/MODEL_NOTES.md` 第 3.6 节）表明，
> 在附录 B 的原始参数下，`Q*` 在 10²²、10²⁴ 预算下会**顶到上界 `Q* = 1`**（角点解），
> 真正的结构性转移信号出现在 **10¹⁸~10²⁰ 的低预算区间**。
> 因此扫描网格必须在低预算端加密，**不得只做 10¹⁹/10²²/10²⁴ 三档就下结论**。
>
> ⚠️ **边界解必须被解释而非回避**：若 `Q* = 1`，须显式报告并讨论其经济含义
> （预算充裕时"把数据做到最好"优于继续堆参数），不得静默略过。

**验收**：
- [ ] `L_ctx^crit = 6/η = 30000` 有**解析推导步骤**（不是直接写结论）
- [ ] 结构性转移有**正式定义 + 至少两种独立识别方法互相印证**
- [ ] 三种 g(Q) 下的最优解差异有对比表
- [ ] 扫描网格在**低预算端加密**（至少覆盖 10¹⁸~10²⁰）
- [ ] 全局优化的**多起点 + 收敛诊断**齐全（避免局部极小说成全局最优）
- [ ] 至少报告一次**边界解 vs 内点解**的讨论（最优是否在约束边界上）
- [ ] 数值实现采用 **log 参数化 + `np.errstate` 保护**（避免 overflow / divide-by-zero）

### 6.5 Q4：技术演进分析与前沿预测

**输入**：C1（或 C2）、C3、C4、C5–C6、C7、C8
**输出**：`outputs/q4/**`

**任务拆解**：

| 子任务 | 关键要求 |
|---|---|
| 4a 贡献分解 | 分离**规模扩张**与**非规模技术进步**各自的贡献占比；建立动力学模型或因果推断模型 |
| 4b Loss↔Benchmark 桥接 | 用 C5/C6 **或**可核验文献建立映射；**按可比性等级区分使用**；讨论映射误差对结论的影响 |
| 4c 前沿预测 | 预测未来 **12 / 24 个月**开源 LLM 能力前沿边界；给出**不确定性分析**（预测区间） |
| 4d 口径声明 | ★ 必须说明：**综合能力度量方式**、**开源筛选口径**（是否须开源权重 / 许可证是否允许研究与复现）、**模型类型区分**（pretrained vs chat/finetuned）、**时间轴口径**（提交日期 / 发布日期 / 版本日期） |
| 4e 逐任务分析 | 对 **C8** 做**至少一项逐任务聚合分析**，**不得仅用汇总表** |

**推荐方法**：

- **分解**：`Score_t = f(规模_t) + g(技术_t) + ε`；用双因素分解 / 面板回归 / DML 双重机器学习估计 `g(t)`；或用 logistic / Gompertz 型能力增长曲线 + 时间虚拟变量
- **桥接**：`Benchmark = h(Loss)`（单调、有界，如 logistic / 分段线性 / 保序回归），用 C5/C6 拟合并给 R²与残差
- **预测**：拟合 + **bootstrap / 保形预测**给出 12 & 24 个月的 80%/95% 预测区间；做**算力增长放缓情景**（如年增率减半）的条件预测
- **因果**：用 DoWhy 显式声明因果图与识别假设，用 EconML 估计"技术进步的边际效应"

**验收**：
- [ ] 贡献占比给出**数值**（如"规模扩张贡献 62%，技术进步贡献 38%"）并附区间
- [ ] 桥接映射的**误差传播**有分析（映射误差 → 预测区间放大多少）
- [ ] 四种口径（能力度量/开源筛选/模型类型/时间轴）全部显式声明
- [ ] C8 逐任务分析有**独立小节**与图
- [ ] 预测有**情景对比**（基准 / 算力放缓 / 技术加速）

---

## 7. 代码质量与复现规范

### 7.1 编码约定

- **统一入口**：每问有 `run_qN.py`，只接受 `--config configs/qN.yaml` 与 `--seed`。
- **统一配置**：所有超参、路径、常量写在 `configs/*.yaml`，**代码里禁止硬编码魔法数字**。
- **统一随机源**：`SEED = 42`（`src/common/config.py`）；所有 `numpy`/`random`/`sklearn`/`pymoo` 调用都要传 seed。
- **统一日志**：用 `logging`，输出到 `outputs/qN/run.log`，同时打印到控制台。
- **禁止 notebook 作为主流程**：`.ipynb` 只用于探索，最终结论必须落在 `.py` 脚本中。
- **函数式与可测**：核心数学过程必须写成**纯函数**，便于 `pytest` 断言。

### 7.2 结果记录模板（`outputs/qN/metrics.json`）

```json
{
  "question": "q2",
  "git_commit": "<由脚本自动写入 git rev-parse HEAD>",
  "timestamp": "2026-01-01T12:00:00+08:00",
  "seed": 42,
  "runtime_sec": 12.3,
  "data_sources": ["B1", "B2", "B4", "B5", "B6"],
  "model": {"form": "L = E + A*N^-alpha + B*D^-beta * Q^-gamma", "n_params": 6},
  "metrics": {"r2_train": 0.0, "r2_val": 0.0, "rmse_val": 0.0, "mae_val": 0.0, "aic": 0.0, "bic": 0.0},
  "params": {"E": {"value": 0.0, "stderr": 0.0, "ci95": [0.0, 0.0]}},
  "checks": {"q1_degeneracy_verified": true, "residual_normal_p": 0.0}
}
```

### 7.3 测试要求

`pytest tests/ -v` 必须全绿。每个测试至少覆盖：
- **形状与类型**：输入输出形状、dtype
- **退化性**：Q2 的 `Q=1 → 经典形式`；Q3 的 `L_ctx=0 → 无注意力开销`
- **约束满足**：Q1/Q3 的单纯形约束 `|Σp−1| < 1e-6`、`p_i ≥ 0`
- **单调性**：损失随 N、D、Q 的单调方向符合物理直觉
- **可复现性**：同 seed 两次运行结果完全一致（`np.allclose`）

### 7.4 一键复现

`scripts/run_all.ps1` 必须能在一台干净机器上端到端跑通：

```powershell
cd C:\Users\28447\Desktop\数学建模\MathAgent
.\.venv\Scripts\Activate.ps1
python scripts\check_env.py
python -m src.q0_data.discover
python -m src.q1_quality_mixture.run_q1
python -m src.q2_scaling_law.run_q2
python -m src.q3_optimization.run_q3
python -m src.q4_frontier.run_q4
python -m src.report.make_figures
python -m pytest tests\ -v
.\scripts\commit.ps1 -Scope repo -Type exp -Message "端到端复现通过"
```

---

## 8. 进度看板与交接（`docs/PROGRESS.md` 模板）

```markdown
# F 题进度看板
最后更新：<日期> | 当前 HEAD：<commit hash>

## 阶段状态
- [ ] P0 数据获取与发现（阻塞）
- [ ] P1 Q1 质量评价与配比建模
- [ ] P2 Q2 广义标度律
- [ ] P3 Q3 算力约束优化与结构性转移
- [ ] P4 Q4 前沿预测
- [ ] P5 论文撰写与图表定稿

## 已完成
- [x] <日期> 初始化仓库结构 `feat(q0)`
- [x] <日期> 写入操作规范 OPS_SPEC `doc(spec)`

## 进行中
- [ ] ...

## 阻塞项（需人工介入）
- [ ] **缺失数据**：`data/raw/real_attachments/` 为空，需下载官方附件

## 交接备忘
- 下一个 agent 应先执行：`git pull --rebase origin main`，然后读本文件与 OPS_SPEC
- 未决问题：...
```

---

## 9. 工具与依赖决策记录（ADR 摘要）

| 日期 | 决策 | 理由 | 影响 |
|---|---|---|---|
| v1.0 | 用 `lmfit` 而非手写 `scipy.optimize.curve_fit` | 自带参数置信区间与边界约束 | Q2 参数报告 |
| v1.0 | 配比建模优先 ILR 变换 + 岭回归 | 单纯形约束下直接线性回归有共线性与边界问题 | Q1 |
| v1.0 | Q3 用多起点 DE + 局部 SLSQP 精修 | 目标非凸，单起点不可信 | Q3 |
| v1.0 | Q4 用保形预测给区间 | 分布无关、样本少时比正态假设稳健 | Q4 |

> 后续每引入/替换一个工具，**必须在此表追加一行并提交**（受 R1 约束）。

---

## 10. 论文写作与提交要求

### 10.1 论文必答清单（逐条自检）

**Q1 必答**：22 指标预处理与方向统一清单 / 综合评价模型 / Q 的定义与聚合方式 / 域级 Q 与 A1 对照 / 冲突定义与消解规则 / A4–A15 配比模型 / 单纯形处理方式 / A6–A11 检验结果 / A12–A15 外推稳健性 / 跨体系关联规则

**Q2 必答**：经典标度律基线 / 广义标度律形式与依据 / Q=1 退化性验证 / 边际效用与弹性 / 替代条件（质量 0.1 ↔ 参数增量）/ 领域替代互补关系 / 参数估计与置信区间 / B2–B10 各验证结果 / 半合成数据的局限说明

**Q3 必答**：优化模型与约束 / p 的角色及理由 / 三档预算结果 / 三种 g(Q) 对比 / **结构性转移的定义与识别** / `L_ctx^crit = 30000` 解析推导 / C7 可行取值上的敏感性分析

**Q4 必答**：贡献分解方法与数值结果 / Loss–Benchmark 桥接映射与误差讨论 / 12 与 24 个月预测 + 不确定性 / 四种口径声明 / C8 逐任务聚合分析 / 算力放缓情景

### 10.2 提交物

- **论文正文**：所有问题的原理、建模过程、实验结果、分析结论**必须纳入正文**，不得只放附件
- **附件**：核心代码 + 说明文档 + 模型参数 + 配置文件 + 运行环境说明；**须附带详细运行说明与数据处理规则**
- **总附件 ≤ 50 MB**（注意：本题数据量不大，容易满足；但仍需检查）
- **严禁**出现参赛单位、队员姓名、队伍编号等身份信息
- **AI 使用披露**：论文末尾附录必须写明所用 AI 工具、输入内容、输出后续处理策略、开发框架、开源软件、技术路线、假设条件与超参数

### 10.3 学术规范红线（违反即取消资格）

1. 不得引入**任何其他公开或私有情感/语言数据集**参与训练、微调、参数优化、阈值选择或结果统计
2. 不得把 B6–B8 **半合成数据**表述为直接实验观测
3. 不得以 AI 输出作为学术依据；公式与结论须引用**正式发表文献或可核验数据**
4. 不得直接复制 AI 生成的建模方案（查重发现雷同即违规）
5. 不得隐瞒 AI 使用情况

---

## 11. Agent 工作循环（每次任务的标准动作）

```
┌─ 1. 接手 ────────────────────────────────────────────┐
│  git pull --rebase origin main                        │
│  读 docs/PROGRESS.md，确认当前阶段与阻塞项              │
│  读本文件 OPS_SPEC_F题.md 对应章节                     │
└──────────────────────────────────────────────────────┘
                        ↓
┌─ 2. 检查前置 ────────────────────────────────────────┐
│  data/raw/ 是否有数据？没有 → 先完成 P0 或报告阻塞       │
│  docs/DECISIONS.md 是否有未决问题拦截本次任务？          │
└──────────────────────────────────────────────────────┘
                        ↓
┌─ 3. 小步实施 ────────────────────────────────────────┐
│  一次只做一件事（一个函数 / 一个模型 / 一张图）           │
│  写完立即本地验证：python -m ... / pytest tests/ -k qN │
└──────────────────────────────────────────────────────┘
                        ↓
┌─ 4. 提交（★ 铁律 R1，不可跳过）★ ─────────────────────┐
│  .\scripts\commit.ps1 -Scope qN -Type <type> -Message "..." │
│  自检：git status --porcelain          必须为空         │
│        git log origin/main..HEAD       必须为空         │
└──────────────────────────────────────────────────────┘
                        ↓
┌─ 5. 更新看板 ────────────────────────────────────────┐
│  更新 docs/PROGRESS.md                                │
│  更新 docs/TOOLS.md（若引入新工具）                     │
│  再次 commit（同样受 R1 约束）                          │
└──────────────────────────────────────────────────────┘
```

---

## 12. 快速命令备忘

```powershell
# 进入仓库
cd C:\Users\28447\Desktop\数学建模\MathAgent

# 同步
git pull --rebase origin main

# 环境
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python scripts\check_env.py

# 运行
python -m src.q0_data.discover
python -m src.q1_quality_mixture.run_q1
python -m src.q2_scaling_law.run_q2
python -m src.q3_optimization.run_q3
python -m src.q4_frontier.run_q4

# 测试
pytest tests\ -v

# ★ 提交（每次改动必做）
.\scripts\commit.ps1 -Scope q2 -Type model -Message "说明"

# 状态自检
git status --porcelain
git log origin/main..HEAD --oneline
git log --oneline -10
```

---

## 附录 A：本规范的变更记录

| 版本 | 日期 | 变更 | 提交 |
|---|---|---|---|
| v1.0 | 初版 | 建立仓库结构、提交铁律、四问工作流、验收清单 | `<commit>` |

> 变更本文件后，必须同步更新上表并**提交推送**（铁律 R2）。

---

## 附录 B：本规范强制条款索引

| 条款 | 内容 | 出处 |
|---|---|---|
| **R1** | **每次更改代码必须提交仓库，改完即提交、提交即推送** | 第 1.1 节 |
| **R2** | **本 md 文件修改后必须上传至仓库** | 第 1.1 节 |
| R3 | `data/raw/**` 只读 | 第 4.3 节 |
| R4 | 每问必产出 metrics/params/图/表 | 第 6 节 |
| R5 | 大文件不入库 | 第 1.4 节 |
| R6 | 固定随机种子 | 第 7.1 节 |
| R7 | 工具/模型须标注版本与参数 | 第 5.1 节 |
| R8 | AI 使用必须披露 | 第 10.3 节 |

---

> **再次强调：每次更改代码必须提交仓库。**
> 这不是建议，是硬性操作要求。任何未提交的改动都视为未完成的工作。
