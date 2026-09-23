"""评价指标。

规范：
    - 所有模型的性能报告必须使用本模块的指标函数，保证口径一致
    - 回归：R² / RMSE / MAE / 调整 R² / AIC / BIC
    - 分类（Q4 若需要）：Accuracy / F1
    - 区间预测（Q4）：经验覆盖率 / 平均区间宽度
"""

from __future__ import annotations

import numpy as np

EPS = 1e-12


# ---------------------------------------------------------------- 回归

def r2(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    ss_res = float(np.sum((y_true - y_pred) ** 2))
    ss_tot = float(np.sum((y_true - y_true.mean()) ** 2))
    return 1.0 - ss_res / (ss_tot + EPS)


def adjusted_r2(y_true: np.ndarray, y_pred: np.ndarray, n_params: int) -> float:
    """调整 R²，用于比较参数个数不同的模型（Q2 的经典 vs 广义标度律）。"""
    n = len(np.asarray(y_true))
    r = r2(y_true, y_pred)
    if n <= n_params + 1:
        return float("nan")
    return 1.0 - (1.0 - r) * (n - 1) / (n - n_params - 1)


def rmse(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    d = np.asarray(y_true, dtype=float) - np.asarray(y_pred, dtype=float)
    return float(np.sqrt(np.mean(d**2)))


def mae(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    d = np.asarray(y_true, dtype=float) - np.asarray(y_pred, dtype=float)
    return float(np.mean(np.abs(d)))


def mape(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    return float(np.mean(np.abs((y_true - y_pred) / (np.abs(y_true) + EPS))) * 100)


# ---------------------------------------------------------------- 信息准则

def aic(y_true: np.ndarray, y_pred: np.ndarray, n_params: int) -> float:
    """赤池信息准则（残差平方和形式，假设高斯误差）。

    AIC = n·ln(RSS/n) + 2k
    """
    y_true = np.asarray(y_true, dtype=float)
    resid = y_true - np.asarray(y_pred, dtype=float)
    rss = float(np.sum(resid**2))
    n = len(y_true)
    return float(n * np.log(rss / n + EPS) + 2 * n_params)


def bic(y_true: np.ndarray, y_pred: np.ndarray, n_params: int) -> float:
    """贝叶斯信息准则：BIC = n·ln(RSS/n) + k·ln(n)。"""
    y_true = np.asarray(y_true, dtype=float)
    resid = y_true - np.asarray(y_pred, dtype=float)
    rss = float(np.sum(resid**2))
    n = len(y_true)
    return float(n * np.log(rss / n + EPS) + n_params * np.log(n))


def regression_report(
    y_true: np.ndarray, y_pred: np.ndarray, n_params: int | None = None
) -> dict[str, float]:
    """一次给出全部回归指标（Q2 报告的标准入口）。"""
    out = {
        "r2": r2(y_true, y_pred),
        "rmse": rmse(y_true, y_pred),
        "mae": mae(y_true, y_pred),
        "mape": mape(y_true, y_pred),
        "n": int(len(np.asarray(y_true))),
    }
    if n_params is not None:
        out["adjusted_r2"] = adjusted_r2(y_true, y_pred, n_params)
        out["aic"] = aic(y_true, y_pred, n_params)
        out["bic"] = bic(y_true, y_pred, n_params)
        out["n_params"] = int(n_params)
    return out


# ---------------------------------------------------------------- 分类

def accuracy(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    y_true = np.asarray(y_true)
    y_pred = np.asarray(y_pred)
    return float(np.mean(y_true == y_pred))


def f1_macro(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """宏平均 F1（不依赖 sklearn，便于单元测试）。"""
    y_true = np.asarray(y_true)
    y_pred = np.asarray(y_pred)
    labels = np.unique(np.concatenate([y_true, y_pred]))
    f1s = []
    for lab in labels:
        tp = float(np.sum((y_pred == lab) & (y_true == lab)))
        fp = float(np.sum((y_pred == lab) & (y_true != lab)))
        fn = float(np.sum((y_pred != lab) & (y_true == lab)))
        prec = tp / (tp + fp + EPS)
        rec = tp / (tp + fn + EPS)
        f1s.append(0.0 if prec + rec < EPS else 2 * prec * rec / (prec + rec))
    return float(np.mean(f1s))


# ---------------------------------------------------------------- 区间预测（Q4）

def empirical_coverage(
    y_true: np.ndarray, lo: np.ndarray, hi: np.ndarray
) -> float:
    """预测区间的经验覆盖率 —— 应接近名义水平（如 0.9）。"""
    y_true = np.asarray(y_true, dtype=float)
    lo = np.asarray(lo, dtype=float)
    hi = np.asarray(hi, dtype=float)
    return float(np.mean((y_true >= lo) & (y_true <= hi)))


def interval_width(lo: np.ndarray, hi: np.ndarray) -> float:
    """平均区间宽度 —— 越窄越好（在覆盖率达标的前提下）。"""
    return float(np.mean(np.asarray(hi, dtype=float) - np.asarray(lo, dtype=float)))


def interval_report(
    y_true: np.ndarray, lo: np.ndarray, hi: np.ndarray, nominal: float = 0.9
) -> dict[str, float]:
    cov = empirical_coverage(y_true, lo, hi)
    return {
        "nominal_coverage": float(nominal),
        "empirical_coverage": cov,
        "coverage_gap": float(cov - nominal),
        "mean_interval_width": interval_width(lo, hi),
    }
