"""P0 数据发现模块的测试。

覆盖 OPS_SPEC 第 7.3 节要求的测试类型：
    - 形状与类型
    - 边界条件（空目录、无数据文件）
    - 可复现性
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.common.config import L_CTX_CRIT, ETA, CHINCHILLA_COEF, N_DOMAINS, N_QUALITY_INDICATORS
from src.q0_data.discover import discover, guess_code


# ---------------------------------------------------------------- 编号识别

@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        # 单数字编号 + 下划线（回归测试：不能用 \b，下划线属于 \w）
        ("B1_scaling.csv", "B1"),
        ("A1_quality.json", "A1"),
        ("C7_ctx.xlsx", "C7"),
        # 双数字编号
        ("A12.xlsx", "A12"),
        ("A18_verify.csv", "A18"),
        ("C10.csv", "C10"),
        ("data_B12_aux.xlsx", "B12"),
        # 中文前缀
        ("附件B1.csv", "B1"),
        # 纯编号
        ("B1.csv", "B1"),
        # 不应误匹配
        ("readme.txt", None),
        ("abc.csv", None),
        ("summary.csv", None),
    ],
)
def test_guess_code(filename: str, expected: str | None) -> None:
    assert guess_code(filename) == expected


def test_guess_code_does_not_match_letters_inside_words() -> None:
    """'abc.csv' 中的 'b'/'c' 后面没有数字，且前面是字母，不得匹配。"""
    assert guess_code("abc.csv") is None
    assert guess_code("summary.csv") is None
    # 前缀是下划线时应当匹配（下划线不算字母数字）
    assert guess_code("table_c3.csv") == "C3"
    # 前缀是数字时不应匹配（避免 '9C3' 这类版本号误判）
    assert guess_code("x9c3") is None
    assert guess_code("9C3") is None


# ---------------------------------------------------------------- 空数据目录

def test_discover_empty_dir_is_blocked(tmp_path: Path) -> None:
    """空目录必须报告 blocked，且不抛异常。"""
    rep = discover(root=tmp_path, out=tmp_path / "inv.json", deep=False)
    assert rep["status"] == "blocked"
    assert "reason" in rep
    assert "action" in rep


def test_discover_ignores_gitkeep(tmp_path: Path) -> None:
    """只有 .gitkeep 的目录应视为空（这是仓库的默认状态）。"""
    (tmp_path / ".gitkeep").write_text("", encoding="utf-8")
    rep = discover(root=tmp_path, out=tmp_path / "inv.json", deep=False)
    assert rep["status"] == "blocked"
    assert rep.get("n_files", 0) == 0


def test_discover_nonexistent_dir_is_blocked(tmp_path: Path) -> None:
    rep = discover(root=tmp_path / "does_not_exist", out=tmp_path / "inv.json", deep=False)
    assert rep["status"] == "blocked"


# ---------------------------------------------------------------- 正常解析

def test_discover_relative_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """回归测试：相对路径作为 root 时不得抛 ValueError（原先的 bug）。"""
    import os

    (tmp_path / "B1_x.csv").write_text("N,D,loss\n1e8,1e9,3.2\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    rep = discover(root=Path("."), out=tmp_path / "inv.json", deep=True)
    assert rep["status"] == "ok"
    assert rep["n_files"] == 1


def test_discover_parses_csv(tmp_path: Path) -> None:
    (tmp_path / "B1_scaling.csv").write_text(
        "N,D,loss\n1e8,1e9,3.2\n2e8,2e9,3.0\n", encoding="utf-8"
    )
    rep = discover(root=tmp_path, out=tmp_path / "inv.json", deep=True)
    assert rep["status"] == "ok"
    assert rep["code_to_files"]["B1"] == [
        p for p in rep["code_to_files"]["B1"]
    ]
    probe = rep["files"][0]["probe"]
    assert probe["kind"] == "table"
    assert probe["columns"] == ["N", "D", "loss"]
    assert probe["n_rows_est"] == 2


def test_discover_writes_json(tmp_path: Path) -> None:
    (tmp_path / "A1_q.json").write_text('{"q": 1}', encoding="utf-8")
    out = tmp_path / "sub" / "inv.json"
    discover(root=tmp_path, out=out, deep=True)
    assert out.exists()
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["status"] == "ok"
    assert data["n_files"] == 1


def test_discover_is_reproducible(tmp_path: Path) -> None:
    """同输入两次运行，除时间戳外结果应一致（OPS_SPEC 第 7.3 节可复现性）。

    注意：清单文件必须写到**被扫描目录之外**，否则第二次扫描会把上一轮的
    输出当成输入数据，导致结果不可复现。这也是 discover 的实际用法
    （扫描 data/raw，输出到 outputs/）。
    """
    scan_dir = tmp_path / "raw"
    scan_dir.mkdir()
    out_dir = tmp_path / "out"
    (scan_dir / "B2.csv").write_text("a,b\n1,2\n", encoding="utf-8")

    r1 = discover(root=scan_dir, out=out_dir / "i1.json", deep=True)
    r2 = discover(root=scan_dir, out=out_dir / "i2.json", deep=True)
    r1.pop("timestamp"), r2.pop("timestamp")
    assert r1 == r2


def test_discover_output_inside_scan_dir_is_not_reproducible(tmp_path: Path) -> None:
    """固化已知陷阱：清单写进被扫描目录会让结果自我污染。

    这条测试记录的是**设计约束**，不是 bug —— 调用方必须把 out 放在扫描目录外。
    """
    (tmp_path / "B2.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    r1 = discover(root=tmp_path, out=tmp_path / "inv.json", deep=False)
    r2 = discover(root=tmp_path, out=tmp_path / "inv.json", deep=False)
    assert r1["n_files"] == 1
    assert r2["n_files"] == 2  # 上一轮的 inv.json 被当成了输入


# ---------------------------------------------------------------- 题目常量（防手误）

def test_ctx_crit_analytic_value() -> None:
    """L_ctx^crit = 6 / eta = 30000 —— 题目要求解析给出，此处锁定数值。"""
    assert ETA == pytest.approx(2e-4)
    assert CHINCHILLA_COEF == pytest.approx(6.0)
    assert L_CTX_CRIT == pytest.approx(30000.0)


def test_problem_scale_constants() -> None:
    assert N_DOMAINS == 17
    assert N_QUALITY_INDICATORS == 22
