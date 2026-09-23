# MathAgent

2026 年中国研究生数学建模竞赛 **F 题**（算力约束下提升大语言模型能力的资源配置建模）的建模工作仓库。

---

## 快速开始

```powershell
# 1. 同步仓库
git pull --rebase origin main

# 2. 环境
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python scripts\check_env.py

# 3. 读规范（必做）
#    OPS_SPEC_F题.md  —— 唯一操作规范
#    docs\PROGRESS.md —— 当前进度与阻塞项
```

---

## ⚠️ 铁律（每次操作前必读）

> ## 每次更改代码必须提交仓库
>
> 改完即 `commit`，`commit` 即 `push`。禁止累积多次改动后一次性提交。
> 本仓库的规范文件（`OPS_SPEC_F题.md` 等 `*.md`）修改后同样**必须提交并推送**。

标准提交入口：

```powershell
.\scripts\commit.ps1 -Scope q2 -Type model -Message "加入 Q=1 退化约束的广义标度律"
```

收工自检（两条输出都必须为空）：

```powershell
git status --porcelain
git log origin/main..HEAD --oneline
```

完整的提交规范、目录结构、四问工作流与验收清单见 **`OPS_SPEC_F题.md`**。

---

## 仓库结构

```
MathAgent/
├── OPS_SPEC_F题.md          ★ 唯一操作规范（先读这个）
├── requirements.txt           依赖清单
├── .gitignore                 提交边界（data/raw 与大数据不入库）
├── data/
│   ├── raw/                   ★ 只读★ 竞赛官方附件（不入库）
│   ├── interim/               清洗后中间数据（不入库）
│   └── processed/             建模就绪派生数据
├── src/                       源码（common / q0_data / q1…q4 / report）
├── outputs/                   ★ 证据链：metrics.json / params.json / 图表
├── scripts/
│   ├── commit.ps1             ★ 一键提交并推送
│   ├── check_env.py           环境自检
│   ├── run_all.ps1            端到端复现
│   └── tools/                 从 GitHub 拉取的外部工具
├── docs/
│   ├── PROGRESS.md            ★ 进度看板（每次收工更新）
│   ├── DATA_NOTES.md          数据说明摘录与编号映射
│   ├── MODEL_NOTES.md         各问数学形式的推导与取舍
│   ├── TOOLS.md               外部工具来源/版本/许可证
│   ├── DECISIONS.md           决策记录（ADR）
│   └── problem_statement.md   赛题原文存档
└── tests/                     单元测试
```

---

## 四问主线

| 阶段 | 内容 | 关键产出 |
|---|---|---|
| **P0** | 数据发现（★ 阻塞前置） | `outputs/data_inventory.json`、编号↔文件名对照 |
| **P1 / Q1** | 数据质量评价、冲突消解、17 域配比建模 | 质量分 Q、冲突定义、配比→Loss 模型 |
| **P2 / Q2** | 广义标度律 L(N,D,Q,p) 与弹性分析 | 参数估计、Q=1 退化验证、替代条件 |
| **P3 / Q3** | 算力约束下的资源联合优化 | 三档预算最优解、**结构性转移**定义与识别 |
| **P4 / Q4** | 技术演进分解与前沿预测 | 贡献占比、Loss↔Benchmark 桥接、12/24 月预测 |

---

## 当前状态

**⚠️ 阻塞中**：`data/raw/` 为空。F 题所需的 A1–A18 / B1–B12 / C1–C10 全部附件与《数据说明》
需先从竞赛官方渠道下载。详见 `docs/PROGRESS.md` 的"阻塞项"。

---

## 学术规范红线（违反即取消参评资格）

1. 不得引入任何其他公开或私有数据集参与训练、微调、调参、阈值选择或结果统计
2. 不得把 B6–B8 半合成数据表述为直接实验观测
3. 不得以 AI 输出作为学术依据；公式与结论须引用正式文献或可核验数据
4. 不得直接复制 AI 生成的建模方案
5. **论文必须披露 AI 工具使用情况**（工具名、输入、输出处理策略、框架、假设、超参数）
