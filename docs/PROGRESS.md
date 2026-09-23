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

## 环境探测结果（自动生成）

| 项 | 值 |
|---|---|
| Python | 3.13.7 (CPython)，`D:\python\python.exe` |
| 平台 | Windows 11 / AMD64 |
| CPU 核数 | 24 |
| 已安装 | numpy 2.4.4、scipy 1.17.1、pandas 3.0.2、scikit-learn 1.8.0、matplotlib 3.10.9、joblib 1.5.3 |
| 缺失 | pyarrow、statsmodels、lmfit、iminuit、pymoo、cvxpy、dowhy、econml、mapie、powerlaw、seaborn、PyYAML、tqdm、pytest |

**行动项**：环境当前为 `incomplete`。开工前先执行
```powershell
pip install -r requirements.txt
python scripts\check_env.py     # 期望 status: ok
```
若某个库在 Python 3.13 下安装失败（如 `cvxpy`/`dowhy`/`econml` 的兼容性），
**必须在 `OPS_SPEC_F题.md` 第 9 节登记替代方案**，不得静默跳过。


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
