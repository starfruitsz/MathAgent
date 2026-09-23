"""单纯形（成分数据）工具。

用途：Q1 的 17 域配比建模、Q3 的配比决策变量。

为什么需要（ADR-002）：
    配比 p 满足单纯形约束 `p_i >= 0, sum(p_i) = 1`，直接把 p 当普通自变量做线性回归会有两个问题：
      1. 设计矩阵严格共线（sum(p) = 1 使 17 列线性相关），回归系数不可辨识；
      2. 边界解 p_i = 0 会让 log 型变换奇异。
    解决方式是先做**对数比变换**把单纯形等距映到无约束的 R^(D-1)，在变换空间建模，
    再逆变换回单纯形。

提供的变换：
    CLR  —— 中心化对数比（centered log-ratio），D 维，和恒为 0（仍有一维冗余）
    ALR  —— 加性对数比（additive log-ratio），D-1 维，以最后一维为参照
    ILR  —— 等距对数比（isometric log-ratio），D-1 维，保持 Aitchison 距离（**推荐用于回归**）
"""

from __future__ import annotations

import numpy as np

from src.common.config import SIMPLEX_TOL

EPS = 1e-12


# ---------------------------------------------------------------- 零值处理

def replace_zeros(p: np.ndarray, method: str = "multiplicative") -> np.ndarray:
    """处理成分中的零值（log 变换前必须做）。

    参数
    ----
    p : ndarray, shape (n, D) 或 (D,)
    method :
        'multiplicative' —— 乘性替换：把 0 替换为检测限的小比例，再重新归一化
        'additive'       —— 加性替换：给所有分量加一个小常数 δ 后归一化

    参考：Martín-Fernández et al. (2003) 的乘性替换策略。
    """
    p = np.atleast_2d(np.asarray(p, dtype=float)).copy()
    if p.min() < 0:
        raise ValueError("成分数据不得含负值")

    D = p.shape[1]
    n_zeros = int(np.sum(p == 0))
    if n_zeros == 0:
        return p

    if method == "additive":
        delta = 1e-6
        p = p + delta
        return p / p.sum(axis=1, keepdims=True)

    if method != "multiplicative":
        raise ValueError(f"未知的零值处理方法: {method}")

    # 乘性替换：用非零分量的最小值的一个比例作为检测限
    out = p.copy()
    for i in range(p.shape[0]):
        row = out[i]
        zeros = row == 0
        if not zeros.any():
            continue
        dl = max(row[~zeros].min() * 0.65, EPS) if (~zeros).any() else 1.0 / D
        row[zeros] = dl
        out[i] = row / row.sum()
    return out


# ---------------------------------------------------------------- CLR

def clr(p: np.ndarray) -> np.ndarray:
    """中心化对数比变换：clr(p)_i = ln(p_i) - mean_j ln(p_j)。

    输出 D 维，且每行之和为 0（有一维冗余）。
    """
    p = np.atleast_2d(np.asarray(p, dtype=float))
    p = replace_zeros(p)
    logp = np.log(p + EPS)
    return logp - logp.mean(axis=1, keepdims=True)


def clr_inv(z: np.ndarray) -> np.ndarray:
    """CLR 逆变换：softmax。"""
    z = np.atleast_2d(np.asarray(z, dtype=float))
    e = np.exp(z - z.max(axis=1, keepdims=True))
    return e / e.sum(axis=1, keepdims=True)


# ---------------------------------------------------------------- ALR

def alr(p: np.ndarray, ref: int = -1) -> np.ndarray:
    """加性对数比：以第 ref 个分量为参照，返回 D-1 维。"""
    p = np.atleast_2d(np.asarray(p, dtype=float))
    p = replace_zeros(p)
    D = p.shape[1]
    idx = np.arange(D)
    keep = idx != (ref % D)
    return np.log(p[:, keep] + EPS) - np.log(p[:, ref % D] + EPS)[:, None]


def alr_inv(z: np.ndarray, ref: int = -1, D: int | None = None) -> np.ndarray:
    """ALR 逆变换。"""
    z = np.atleast_2d(np.asarray(z, dtype=float))
    D = D or (z.shape[1] + 1)
    idx = np.arange(D)
    keep = idx != (ref % D)
    e = np.exp(z)
    out = np.ones((z.shape[0], D))
    out[:, keep] = e
    return out / out.sum(axis=1, keepdims=True)


# ---------------------------------------------------------------- ILR

def _ilr_basis(D: int) -> np.ndarray:
    """构造 ILR 的正交基（Helmert 型），形状 (D-1, D)。"""
    basis = np.zeros((D - 1, D))
    for i in range(1, D):
        basis[i - 1, :i] = 1.0 / i
        basis[i - 1, i] = -1.0
        basis[i - 1] *= np.sqrt(i / (i + 1.0))
    return basis


def ilr(p: np.ndarray) -> np.ndarray:
    """等距对数比变换，返回 D-1 维。

    ILR 保持 Aitchison 距离，因此**在 ILR 空间做线性回归等价于在单纯形上做
    关于 Aitchison 几何的线性建模** —— 这是 Q1 配比建模的推荐做法。
    """
    p = np.atleast_2d(np.asarray(p, dtype=float))
    D = p.shape[1]
    return clr(p) @ _ilr_basis(D).T


def ilr_inv(z: np.ndarray, D: int | None = None) -> np.ndarray:
    """ILR 逆变换，返回 D 维成分（和为 1）。"""
    z = np.atleast_2d(np.asarray(z, dtype=float))
    D = D or (z.shape[1] + 1)
    return clr_inv(z @ _ilr_basis(D))


# ---------------------------------------------------------------- 距离与校验

def aitchison_distance(p: np.ndarray, q: np.ndarray) -> np.ndarray:
    """Aitchison 距离（成分数据的自然距离），基于 ILR 的欧氏距离。"""
    return np.linalg.norm(ilr(p) - ilr(q), axis=1)


def validate_simplex(p: np.ndarray, tol: float = SIMPLEX_TOL) -> None:
    """校验单纯形约束，不满足即抛异常（OPS_SPEC 第 7.3 节约束满足测试）。"""
    p = np.atleast_2d(np.asarray(p, dtype=float))
    if (p < -tol).any():
        raise ValueError("配比含负分量")
    s = p.sum(axis=1)
    if not np.allclose(s, 1.0, atol=tol):
        bad = np.where(~np.isclose(s, 1.0, atol=tol))[0][:5]
        raise ValueError(f"配比之和不等于 1（前几个违规行: {bad.tolist()}）")


def check_simplex(p: np.ndarray, tol: float = SIMPLEX_TOL) -> bool:
    """校验单纯形约束，返回布尔值（用于测试断言）。"""
    try:
        validate_simplex(p, tol)
        return True
    except ValueError:
        return False
