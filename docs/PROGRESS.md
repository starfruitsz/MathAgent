# F 题进度看板

最后更新：初始建立 | 当前 HEAD：`<见 git log>`

> **接手步骤**：`git pull --rebase origin main` → 读本文件 → 读 `OPS_SPEC_F题.md`

---

## 阶段状态

- [ ] **P0 数据获取与发现**（★ 阻塞性前置任务）
- [ ] **P1** Q1 数据质量评价、冲突消解与领域配比建模
- [ ] **P2** Q2 跨维度数据融合与广义标度律
- [ ] **P3** Q3 算力约束下多维资源联合优化与结构性转移
- [ ] **P4** Q4 技术演进分析与前沿预测
- [ ] **P5** 论文撰写与图表定稿

---

## 已完成

- [x] 初始化仓库结构（`.gitignore` / `requirements.txt` / `scripts/` / `docs/`）
- [x] 写入操作规范 `OPS_SPEC_F题.md` v1.0
- [x] 写入一键提交脚本 `scripts/commit.ps1`
- [x] 写入环境自检脚本 `scripts/check_env.py`
- [x] 环境探测完成 → `outputs/env_report.json`
- [x] **依赖栈全部安装并导入验证通过**（20/20，Python 3.13.7）
- [x] `requirements.txt` 锁定精确版本 + `requirements.lock.txt` 完整依赖树
- [x] `src/common/config.py`：全局路径/种子/题目常量（含 `L_CTX_CRIT = 30000`）
- [x] `src/q0_data/discover.py`：数据发现脚本（已通过空数据 + 正常数据两类冒烟测试）
- [x] `src/common/simplex.py`：CLR/ALR/ILR 变换 + 零值替换 + Aitchison 距离（Q1/Q3 基础）
- [x] `src/common/metrics.py`：R²/调整R²/RMSE/MAE/AIC/BIC/F1/区间覆盖率
- [x] `src/common/io_utils.py`：统一读写 + 结果溯源（自动记录 git commit 与 seed）
- [x] 测试 **45 项全部通过**（`tests/test_q0_discover.py` + `tests/test_common.py`）

## 已就绪 / 待实现

| 模块 | 状态 |
|---|---|
| `src/common/config.py` | ✅ 完成（含题目常量与 `L_CTX_CRIT=30000`） |
| `src/common/simplex.py` | ✅ 完成 |
| `src/common/metrics.py` | ✅ 完成 |
| `src/common/io_utils.py` | ✅ 完成 |
| `src/common/plotting.py` | ⬜ 待实现（论文统一出图风格） |
| `src/common/registry.py` | ⬜ 待实现（运行记录与哈希） |
| `src/q0_data/discover.py` | ✅ 完成 |
| `src/q0_data/validate.py` | ⬜ 待实现（形状/缺失/重复/范围校验） |
| `src/q0_data/map_codes.py` | ⬜ 待实现（A/B/C 编号映射） |
| `src/q1_quality_mixture/*` | ⬜ 待实现 |
| `src/q2_scaling_law/*` | ⬜ 待实现 |
| `src/q3_optimization/*` | ⬜ 待实现（**先读 `docs/MODEL_NOTES.md` 第 3.6 节的陷阱**） |
| `src/q4_frontier/*` | ⬜ 待实现 |
| `src/report/*` | ⬜ 待实现 |

> ⚠️ `scripts/run_all.ps1` 会依次调用 q1–q4 的入口，这些入口**尚未实现**，
> 因此该脚本目前只能跑到「数据发现」一步就会失败。这是预期状态 ——
> 数据未到位前不应继续，实现顺序应是 **P0 → P1 → P2 → P3 → P4**。

## 环境探测结果（自动生成）

| 项 | 值 |
|---|---|
| Python | 3.13.7 (CPython)，`D:\python\python.exe` |
| 平台 | Windows 11 / AMD64 |
| CPU 核数 | 24 |
| 状态 | ✅ `status: ok` —— 全部核心依赖就绪（20/20 导入通过） |

**已锁定版本**（详见 `requirements.txt`）：

| 包 | 版本 | 包 | 版本 |
|---|---|---|---|
| numpy | 2.4.4 | pandas | 3.0.2 |
| scipy | 1.17.1 | pyarrow | 25.0.1 |
| statsmodels | 0.15.0 | scikit-learn | 1.8.0 |
| lmfit | 1.3.4 | iminuit | 2.33.0 |
| pymoo | 0.6.2 | cvxpy | 1.9.3 |
| dowhy | 0.14 | econml | 0.17.0 |
| mapie | 1.5.0 | powerlaw | 2.0.0 |
| matplotlib | 3.10.9 | seaborn | 0.13.2 |
| PyYAML | 6.0.3 | tqdm | 4.70.1 |
| joblib | 1.5.3 | pytest | 9.1.1 |

> **重要结论**：`dowhy`、`econml`、`cvxpy`、`pymoo` 这些偏冷门的库在 **Python 3.13 下均可正常安装与导入**，
> 无需降级 Python 或替换工具。环境层无阻塞项。

**接手动作**：环境已就绪，**无需重新安装**。如需在干净机器上重建：
```powershell
pip install -r requirements.txt
python scripts\check_env.py     # 期望 status: ok
```



## 进行中

- [ ] 等待 `data/raw/real_attachments/` 数据到位，随后执行 `python -m src.q0_data.discover`

## 阻塞项（需人工介入）

- [ ] **缺失数据**：工作区内目前只有 6 份题目 Word 文档，`data/raw/` 为空。
      F 题所需的 A1–A18 / B1–B12 / C1–C10 全部附件与《数据说明》**必须先从竞赛官方渠道下载**。
      在数据到位前，**P0 无法启动，P1–P4 全部阻塞**。

## 未决问题

- [ ] `C7` 的具体内容未知（决定 Q3 中 `L_ctx` 的可行取值集合，需在 P0 阶段确认）
- [ ] `C5/C6` 的"可比性等级"字段结构未知（Q4 桥接映射需用到）
- [ ] 附件编号（A1–A18 等）与实际文件名的对照表未知，需由 `discover.py` 生成
- [ ] 质量体系与配比体系的跨体系关联规则待定（A16 给了参考映射，需核对）

---

## 交接备忘

- 下一个 agent 应先执行：`git pull --rebase origin main`，然后读本文件与 `OPS_SPEC_F题.md`
- **铁律 R1：每次更改代码必须提交仓库**（改完即 commit，commit 即 push）
- 提交入口：`.\scripts\commit.ps1 -Scope <q0|q1|q2|q3|q4|spec|env|repo> -Type <type> -Message "..."`
- 收工自检（两条都必须为空）：
  ```powershell
  git status --porcelain
  git log origin/main..HEAD --oneline
  ```
