"""公共层测试：指标、单纯形变换、IO 溯源。

覆盖 OPS_SPEC 第 7.3 节要求的四类测试：
    - 形状与类型
    - 退化性
    - 约束满足
    - 可复现性
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from src.common import metrics as M
from src.common import simplex as S
from src.common.io_utils import load_json, save_json, provenance


# ================================================================ 指标

def test_metrics_perfect_fit() -> None:
    y = np.array([1.0, 2.0, 3.0, 4.0])
    r = M.regression_report(y, y, n_params=2)
    assert r["r2"] == pytest.approx(1.0)
    assert r["rmse"] == pytest.approx(0.0)
    assert r["mae"] == pytest.approx(0.0)


def test_metrics_known_values() -> None:
    y_true = np.array([1.0, 2.0, 3.0])
    y_pred = np.array([1.0, 2.0, 4.0])
    # 残差 = [0, 0, -1]
    assert M.rmse(y_true, y_pred) == pytest.approx(np.sqrt(1 / 3))
    assert M.mae(y_true, y_pred) == pytest.approx(1 / 3)


def test_adjusted_r2_penalises_params() -> None:
    rng = np.random.default_rng(0)
    y = rng.normal(size=50)
    yp = y + rng.normal(scale=0.3, size=50)
    r_lo = M.adjusted_r2(y, yp, n_params=2)
    r_hi = M.adjusted_r2(y, yp, n_params=20)
    assert r_hi < r_lo, "参数越多，调整 R² 应越小"


def test_aic_bic_prefer_better_fit() -> None:
    y = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    good = y + 0.01
    bad = y + 1.0
    assert M.aic(y, good, 3) < M.aic(y, bad, 3)
    assert M.bic(y, good, 3) < M.bic(y, bad, 3)


def test_aic_bic_prefer_fewer_params_when_fit_equal() -> None:
    y = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    yp = y + 0.1
    assert M.aic(y, yp, 2) < M.aic(y, yp, 10)
    assert M.bic(y, yp, 2) < M.bic(y, yp, 10)


def test_classification_metrics() -> None:
    y = np.array([0, 1, 1, 0, 1])
    assert M.accuracy(y, y) == pytest.approx(1.0)
    assert M.f1_macro(y, y) == pytest.approx(1.0)
    assert M.accuracy(y, np.array([0, 0, 1, 0, 1])) == pytest.approx(0.8)


def test_interval_metrics() -> None:
    y = np.array([1.0, 2.0, 3.0])
    lo = np.array([0.0, 1.0, 2.0])
    hi = np.array([2.0, 3.0, 4.0])
    rep = M.interval_report(y, lo, hi, nominal=0.9)
    assert rep["empirical_coverage"] == pytest.approx(1.0)
    assert rep["mean_interval_width"] == pytest.approx(2.0)


# ================================================================ 单纯形变换

def _random_simplex(n: int, D: int, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    p = rng.dirichlet(np.ones(D), size=n)
    return p


def test_clr_roundtrip() -> None:
    p = _random_simplex(20, 17)
    assert np.allclose(S.clr_inv(S.clr(p)), p, atol=1e-9)


def test_alr_roundtrip() -> None:
    p = _random_simplex(20, 17)
    z = S.alr(p)
    assert z.shape == (20, 16), "ALR 应降到 D-1 维"
    assert np.allclose(S.alr_inv(z, D=17), p, atol=1e-9)


def test_ilr_roundtrip() -> None:
    p = _random_simplex(20, 17)
    z = S.ilr(p)
    assert z.shape == (20, 16), "ILR 应降到 D-1 维"
    assert np.allclose(S.ilr_inv(z, D=17), p, atol=1e-9)


def test_clr_rows_sum_to_zero() -> None:
    """CLR 的退化性质：每行之和恒为 0。"""
    p = _random_simplex(10, 17)
    assert np.allclose(S.clr(p).sum(axis=1), 0.0, atol=1e-9)


def test_ilr_is_isometric() -> None:
    """ILR 保持 Aitchison 距离：ILR 空间的欧氏距离 == Aitchison 距离。"""
    p = _random_simplex(5, 17, seed=1)
    q = _random_simplex(5, 17, seed=2)
    d_ait = S.aitchison_distance(p, q)
    d_ilr = np.linalg.norm(S.ilr(p) - S.ilr(q), axis=1)
    assert np.allclose(d_ait, d_ilr, atol=1e-9)


def test_ilr_output_is_simplex() -> None:
    """ILR 逆变换的输出必须满足单纯形约束。"""
    rng = np.random.default_rng(3)
    z = rng.normal(size=(30, 16))
    p = S.ilr_inv(z, D=17)
    assert S.check_simplex(p)
    assert (p > 0).all()


def test_zeros_are_replaced() -> None:
    """含零成分必须能被处理，且处理后仍是合法单纯形。"""
    p = np.array([[0.5, 0.5, 0.0], [0.0, 0.3, 0.7]])
    r = S.replace_zeros(p)
    assert (r > 0).all()
    assert S.check_simplex(r)
    # 非零分量之间的比例关系应保持（乘性替换的性质）
    assert r[0, 0] == pytest.approx(r[0, 1], rel=1e-9)


def test_clr_handles_documented_gotcha() -> None:
    """零值会让 log 变换奇异 —— 但 replace_zeros 必须先行处理，不得产生 nan。"""
    p = np.array([[1.0, 0.0, 0.0]])
    z = S.clr(p)
    assert np.isfinite(z).all()


def test_negative_component_rejected() -> None:
    with pytest.raises(ValueError, match="负值"):
        S.replace_zeros(np.array([[1.1, -0.1]]))


def test_validate_simplex_rejects_bad() -> None:
    assert not S.check_simplex(np.array([[0.5, 0.4]]))
    assert not S.check_simplex(np.array([[1.2, -0.2]]))
    with pytest.raises(ValueError):
        S.validate_simplex(np.array([[0.5, 0.4]]))


def test_zeros_do_not_break_roundtrip() -> None:
    """边界情形：含零成分经替换后仍能往返。"""
    p = np.array([[0.5, 0.5, 0.0]])
    r = S.replace_zeros(p)
    assert np.allclose(S.ilr_inv(S.ilr(r), D=3), r, atol=1e-9)


# ================================================================ IO 与溯源

def test_save_load_json_roundtrip(tmp_path: Path) -> None:
    obj = {"中文键": [1, 2, 3], "nested": {"a": 1.5}}
    p = save_json(obj, tmp_path / "x.json")
    assert p.exists()
    assert load_json(p) == obj


def test_save_json_handles_numpy(tmp_path: Path) -> None:
    """numpy 标量/数组必须能被序列化（否则每个脚本都要手写转换）。"""
    obj = {"scalar": np.float64(1.5), "arr": np.array([1, 2, 3])}
    p = save_json(obj, tmp_path / "n.json")
    back = load_json(p)
    assert back["scalar"] == pytest.approx(1.5)
    assert back["arr"] == [1, 2, 3]


def test_json_is_utf8_not_escaped(tmp_path: Path) -> None:
    p = save_json({"k": "中文"}, tmp_path / "u.json")
    raw = p.read_text(encoding="utf-8")
    assert "中文" in raw, "中文不应被转义为 \\uXXXX"
    assert "\\u" not in raw


def test_provenance_has_required_fields() -> None:
    prov = provenance({"extra": 1})
    assert "git_commit" in prov
    assert "timestamp" in prov
    assert prov["seed"] == 42, "必须记录全局随机种子"
    assert prov["extra"] == 1
