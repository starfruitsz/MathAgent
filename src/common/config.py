"""全局配置与常量。

规范（OPS_SPEC 第 7.1 节）：
    - 所有超参、路径、常量集中在本文件与 configs/*.yaml
    - 代码里禁止硬编码魔法数字
    - 所有随机过程必须使用 SEED
"""

from __future__ import annotations

from pathlib import Path

# ---------------------------------------------------------------- 路径

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_RAW = REPO_ROOT / "data" / "raw"
DATA_INTERIM = REPO_ROOT / "data" / "interim"
DATA_PROCESSED = REPO_ROOT / "data" / "processed"
OUTPUTS = REPO_ROOT / "outputs"
DOCS = REPO_ROOT / "docs"
CONFIGS = REPO_ROOT / "configs"

# 竞赛附件根目录（题目所述 real_attachments/）
REAL_ATTACHMENTS = DATA_RAW / "real_attachments"


def outputs_dir(question: str) -> Path:
    """返回某问的输出目录并自动创建，例如 outputs_dir('q2') -> outputs/q2。"""
    p = OUTPUTS / question
    p.mkdir(parents=True, exist_ok=True)
    return p


# ---------------------------------------------------------------- 随机性

SEED = 42
"""全局随机种子。任何随机过程都必须使用它，保证结果可复现。"""


# ---------------------------------------------------------------- 题目给定的物理/数学常量

# --- 问题三：算力成本模型（题目正文明确给出，不得改动）---

CHINCHILLA_COEF = 6.0
"""C_train = 6 * N * D（Chinchilla 近似）。"""

ETA = 2e-4
"""长文本注意力开销系数：C_attn = eta * N * D * L_ctx。"""

L_CTX_CRIT = CHINCHILLA_COEF / ETA
"""临界上下文长度：使注意力开销与基础训练开销相当的 L_ctx。

    eta * N * D * L_ctx = 6 * N * D  =>  L_ctx = 6 / eta = 30000

题目明确要求"解析给出"，此为解析结果。
"""

BUDGETS = (1e19, 1e22, 1e24)
"""题目建议考察的三档算力预算（FLOPs）。可自行选取其他档位，但至少三个不同量级。"""

BUDGET_SCAN_RANGE = (15.0, 27.0)
"""结构性转移识别时 log10(C) 的扫描区间。"""

BUDGET_SCAN_STEPS = 241
"""扫描点数（步长约 0.05 dex）。"""

# --- 附录 B：数据质量成本函数 g(Q) ---

QUALITY_COST_FORMS = {
    "exponential": {"gamma": 1e7, "lambda": 6.0, "label": "指数型"},
    "power": {"gamma": 5e9, "lambda": 4.0, "label": "幂函数型"},
    "log_asymptotic": {"gamma": 2e9, "lambda": 10.0, "label": "对数渐进型"},
}
"""附录 B.1 给出的三种 g(Q) 形式及其参数：

    exponential:    g(Q) = gamma * exp(lambda * Q)
    power:          g(Q) = gamma * Q ** lambda
    log_asymptotic: g(Q) = gamma * ln(1 + lambda * Q)

成本项为 C_Q = D * [g(Q) - g(Q0)]_+（增量成本形式）。
"""

QUALITY_BOUNDS = (1e-6, 1.0)
"""质量 Q 的取值区间 (0, 1]。下界取 1e-6 而非 0，避免 log/幂运算奇异。"""


# ---------------------------------------------------------------- 数据编号（题目正文已明确）

# 质量信号数据
A_QUALITY_SAMPLED = ("A1",)
A_QUALITY_EXTENDED = ("A2", "A3")
A_QUALITY_ALL = A_QUALITY_SAMPLED + A_QUALITY_EXTENDED

# 配方实验数据
A_MIXTURE_TRAIN = ("A4", "A5")
A_MIXTURE_TEST = ("A6", "A7", "A8", "A9", "A10", "A11")
A_MIXTURE_EXTRAP = ("A12", "A13", "A14", "A15")
A_MIXTURE_ALL = A_MIXTURE_TRAIN + A_MIXTURE_TEST + A_MIXTURE_EXTRAP

A_CROSSWALK = "A16"
"""跨体系域分类参考映射。"""
A_VERIFY = "A18"
"""质量评分验算（可选用）。"""

# 标度律数据
B_MAIN_FIT = "B1"
B_TRAJECTORY = ("B2", "B3")
"""模型族外 / 插值轨迹验证，须使用其中之一。"""
B_CROSSFAMILY = ("B4", "B5")
"""跨族 / 文献验证。"""
B_SEMISYNTH = ("B6", "B7", "B8")
"""半合成补充集 —— 可用于补充分析，但不得表述为直接实验观测。"""
B_EXTRAPOLATION = ("B9", "B10")
"""百亿参数以上外推讨论，须标注可信度边界。"""
B_AUX = ("B11", "B12")

# 评测与桥接数据
C_EVAL_PRIMARY = ("C1", "C2")
C_EVAL_META = "C3"
C_MODEL_META = "C4"
"""含算力、数据量、开源权重等字段。"""
C_BRIDGE = ("C5", "C6")
"""Loss–Benchmark 桥接数据，须按可比性等级区分使用。"""
C_CTX_LENGTH = "C7"
"""★ 上下文长度 L_ctx 的可行取值依据。Q3 中 L_ctx 外生给定，可行取值必须依据 C7。"""
C_PERTASK = "C8"
"""逐任务评测明细 —— Q4 须做至少一项逐任务分析，不得仅用汇总表。"""
C_10 = "C10"

# ---------------------------------------------------------------- 可信度等级

CREDIBILITY_LEVELS = {
    "measured": "直接实验观测",
    "semi_synthetic": "半合成（基于真实数据校准）—— 可补充分析，不得表述为直接观测",
    "estimated": "估算/外推 —— 须标注边界",
}


# ---------------------------------------------------------------- 领域与指标规模

N_DOMAINS = 17
"""17 个训练领域（The Pile 子领域）。配比 p 是 17 维单纯形上的点。"""

N_QUALITY_INDICATORS = 22
"""22 个质量指标，方向须全部统一为"越高越好"。"""


# ---------------------------------------------------------------- 数值容差

SIMPLEX_TOL = 1e-6
"""判断 sum(p) == 1 的容差。"""
