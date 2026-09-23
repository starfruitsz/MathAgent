"""第 0 步：数据发现（★ 阻塞性前置任务）。

用途：
    在 data/raw/ 下清点竞赛官方附件，解析结构化文件的字段结构，
    生成"编号 ↔ 实际文件名"对照表，并输出 data_inventory.json。

为什么必须先做：
    题目原文声明"若清单与实际磁盘文件不一致，以实际文件为准"。
    因此 A1–A18 / B1–B12 / C1–C10 的真实文件名、字段名、形状
    必须以实测为准；尤其 C7（决定 Q3 中 L_ctx 的可行取值）与
    C5/C6（决定 Q4 桥接映射的分层方式）必须在此阶段确认。

用法：
    python -m src.q0_data.discover
    python -m src.q0_data.discover --root data/raw --out outputs/data_inventory.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from src.common.config import (
    CREDIBILITY_LEVELS,
    DATA_RAW,
    OUTPUTS,
    REPO_ROOT,
)

# Windows 控制台默认 GBK，中文输出会乱码 —— 强制 UTF-8
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass


# ---------------------------------------------------------------- 编号识别

# 附件编号形如 A1 / A12 / B6 / C10，可能出现在文件名任意位置（如 "B1_scaling.csv"）。
# 注意：不能用 \b —— 下划线属于 \w，`B1_x` 中 1 与 _ 之间没有单词边界，会漏匹配。
# 因此改用显式 lookaround，只要求两侧不是字母数字。
_CODE_RE = re.compile(r"(?<![A-Za-z0-9])([ABC])(\d{1,2})(?![0-9])", re.IGNORECASE)


def guess_code(name: str) -> str | None:
    """从文件名中推测附件编号（A1–A18 / B1–B12 / C1–C10）。

    只取第一个匹配；无法判断时返回 None，交由人工核对。
    """
    m = _CODE_RE.search(name)
    if not m:
        return None
    return f"{m.group(1).upper()}{int(m.group(2))}"


def file_sha256(path: Path, chunk: int = 1 << 20) -> str:
    """计算文件 sha256（用于可追溯性与去重）。"""
    h = hashlib.sha256()
    with path.open("rb") as f:
        while block := f.read(chunk):
            h.update(block)
    return h.hexdigest()


# ---------------------------------------------------------------- 结构化文件探测

def probe_csv(path: Path, nrows: int = 5) -> dict[str, Any]:
    """探测 CSV/TSV 的字段结构。"""
    import pandas as pd

    sep = "\t" if path.suffix.lower() in {".tsv", ".txt"} else ","
    try:
        df = pd.read_csv(path, sep=sep, nrows=200)
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}
    full_rows = None
    try:
        with path.open("rb") as f:
            full_rows = sum(1 for _ in f) - 1
    except Exception:  # noqa: BLE001
        pass
    return {
        "kind": "table",
        "n_rows_est": full_rows,
        "n_cols": int(df.shape[1]),
        "columns": [str(c) for c in df.columns],
        "dtypes": {str(c): str(t) for c, t in df.dtypes.items()},
        "missing_rate": {
            str(c): round(float(df[c].isna().mean()), 6) for c in df.columns
        },
        "head": json.loads(df.head(nrows).to_json(orient="records", force_ascii=False)),
    }


def probe_excel(path: Path, nrows: int = 5) -> dict[str, Any]:
    """探测 Excel 的 sheet 与字段结构。"""
    import pandas as pd

    try:
        sheets = pd.read_excel(path, sheet_name=None, nrows=200)
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}
    out: dict[str, Any] = {"kind": "excel", "n_sheets": len(sheets), "sheets": {}}
    for name, df in sheets.items():
        out["sheets"][name] = {
            "n_cols": int(df.shape[1]),
            "columns": [str(c) for c in df.columns],
            "dtypes": {str(c): str(t) for c, t in df.dtypes.items()},
            "missing_rate": {
                str(c): round(float(df[c].isna().mean()), 6) for c in df.columns
            },
            "head": json.loads(
                df.head(nrows).to_json(orient="records", force_ascii=False)
            ),
        }
    return out


def probe_json(path: Path) -> dict[str, Any]:
    """探测 JSON 的顶层结构。"""
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}
    top = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            top[str(k)] = (
                f"list[{len(v)}]" if isinstance(v, list) else type(v).__name__
            )
    return {"kind": "json", "top_level": top}


def probe_pickle(path: Path) -> dict[str, Any]:
    """探测 pickle 的顶层键与数组形状（不加载全部数据）。"""
    import pickle

    try:
        with path.open("rb") as f:
            obj = pickle.load(f)
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}

    def describe(v: Any, depth: int = 0) -> Any:
        if depth > 2:
            return type(v).__name__
        if isinstance(v, dict):
            return {str(k): describe(x, depth + 1) for k, x in list(v.items())[:40]}
        if isinstance(v, (list, tuple)):
            inner = describe(v[0], depth + 1) if v else "empty"
            return f"seq[{len(v)}] of {inner}"
        if hasattr(v, "shape"):
            return f"ndarray{v.shape} {getattr(v, 'dtype', '')}"
        return type(v).__name__

    return {"kind": "pickle", "structure": describe(obj)}


def probe_npz(path: Path) -> dict[str, Any]:
    """探测 .npz 的数组清单与形状。"""
    import numpy as np

    try:
        with np.load(path, allow_pickle=True) as z:
            return {
                "kind": "npz",
                "arrays": {k: f"{z[k].shape} {z[k].dtype}" for k in z.files},
            }
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}


PROBES = {
    ".csv": probe_csv,
    ".tsv": probe_csv,
    ".xlsx": probe_excel,
    ".xls": probe_excel,
    ".json": probe_json,
    ".pkl": probe_pickle,
    ".pickle": probe_pickle,
    ".npz": probe_npz,
}


# ---------------------------------------------------------------- 主流程

def git_commit() -> str:
    import subprocess

    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def _rel_to_repo(p: Path) -> str:
    """返回相对仓库根的 POSIX 路径；若在仓库外则返回绝对路径。"""
    try:
        return p.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return p.resolve().as_posix()


def discover(root: Path, out: Path, deep: bool = True) -> dict[str, Any]:
    root = root.resolve()
    if not root.exists():
        return {
            "status": "blocked",
            "reason": f"数据目录不存在：{root}",
            "action": "请先下载竞赛官方附件到 data/raw/，再重新运行本脚本。",
        }

    # 只统计"真实数据文件"，忽略版本控制占位符与临时文件
    IGNORED_NAMES = {".gitkeep", ".gitignore", ".DS_Store", "Thumbs.db"}
    IGNORED_SUFFIXES = {".tmp", ".crdownload", ".part"}
    files = sorted(
        p
        for p in root.rglob("*")
        if p.is_file()
        and p.name not in IGNORED_NAMES
        and not p.name.startswith("~$")
        and p.suffix.lower() not in IGNORED_SUFFIXES
    )
    if not files:
        return {
            "status": "blocked",
            "root": _rel_to_repo(root),
            "reason": f"数据目录内没有任何数据文件：{_rel_to_repo(root)}",
            "action": "请先下载竞赛官方附件到 data/raw/，再重新运行本脚本。",
        }

    records: list[dict[str, Any]] = []
    for p in files:
        rel = _rel_to_repo(p)
        rec: dict[str, Any] = {
            "path": rel,
            "name": p.name,
            "suffix": p.suffix.lower(),
            "size_bytes": p.stat().st_size,
            "guessed_code": guess_code(p.name),
            "sha256": file_sha256(p) if p.stat().st_size < 50 * 1024 * 1024 else "skipped(large)",
        }
        if deep and p.suffix.lower() in PROBES:
            rec["probe"] = PROBES[p.suffix.lower()](p)
        records.append(rec)

    # 编号 → 文件 对照表
    code_map: dict[str, list[str]] = {}
    for r in records:
        if r["guessed_code"]:
            code_map.setdefault(r["guessed_code"], []).append(r["path"])

    # 题目正文声明必须存在的编号（用于完整性检查）
    expected = (
        [f"A{i}" for i in range(1, 19)]
        + [f"B{i}" for i in range(1, 13)]
        + [f"C{i}" for i in range(1, 11)]
    )
    missing = [c for c in expected if c not in code_map]
    ambiguous = {c: v for c, v in code_map.items() if len(v) > 1}

    report = {
        "status": "ok",
        "timestamp": datetime.now().astimezone().isoformat(),
        "git_commit": git_commit(),
        "root": _rel_to_repo(root),
        "n_files": len(records),
        "total_bytes": sum(r["size_bytes"] for r in records),
        "code_to_files": code_map,
        "codes_missing": missing,
        "codes_ambiguous": ambiguous,
        "credibility_levels": CREDIBILITY_LEVELS,
        "files": records,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description="F 题数据发现（P0 阻塞性前置任务）")
    ap.add_argument("--root", type=Path, default=DATA_RAW, help="原始数据根目录")
    ap.add_argument(
        "--out",
        type=Path,
        default=OUTPUTS / "data_inventory.json",
        help="清单输出路径",
    )
    ap.add_argument("--shallow", action="store_true", help="只清点文件，不解析结构")
    args = ap.parse_args()

    rep = discover(args.root, args.out, deep=not args.shallow)

    print("=" * 68)
    print("P0 数据发现")
    print("=" * 68)
    print(f"根目录   : {rep.get('root')}")
    print(f"状态     : {rep['status']}")
    print(f"文件数   : {rep.get('n_files', 0)}")
    print(f"总大小   : {rep.get('total_bytes', 0) / 1024 / 1024:.2f} MB")
    print(f"清单输出 : {args.out}")

    if rep["status"] == "blocked":
        print()
        print("⚠️  阻塞：数据目录为空或不存在。")
        print(f"   原因：{rep.get('reason', '目录内没有任何文件')}")
        print(f"   动作：{rep.get('action', '请先下载竞赛官方附件到 data/raw/。')}")
        print("   详见：docs/PROGRESS.md 的『阻塞项』")
        return 1

    print()
    print("编号 → 文件 对照：")
    for code in sorted(rep["code_to_files"], key=lambda c: (c[0], int(c[1:]))):
        for f in rep["code_to_files"][code]:
            print(f"  {code:<4} {f}")

    if rep["codes_ambiguous"]:
        print()
        print("⚠️  编号歧义（同一编号匹配到多个文件，需人工核对）：")
        for c, v in rep["codes_ambiguous"].items():
            print(f"  {c}: {v}")

    if rep["codes_missing"]:
        print()
        print(f"⚠️  题目声明但未匹配到的编号（{len(rep['codes_missing'])} 个）：")
        print("   " + " ".join(rep["codes_missing"]))
        print("   注：文件名可能不含编号，请人工核对 docs/DATA_NOTES.md")

    print()
    print("下一步：把实测字段结构回填到 docs/DATA_NOTES.md，并确认 C7 / C5 / C6 的具体内容。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
