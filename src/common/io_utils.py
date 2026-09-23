"""统一 IO 工具。

规范：
    - 所有结果写入必须经过本模块，保证编码、缩进、时间戳格式一致
    - 每次写入同时记录 git commit 与随机种子（OPS_SPEC 第 7.2 节）
"""

from __future__ import annotations

import json
import logging
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from src.common.config import REPO_ROOT, SEED


# ---------------------------------------------------------------- git / 时间

def git_commit() -> str:
    """返回当前 HEAD 的 commit hash；不在仓库内时返回 'unknown'。"""
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


def now_iso() -> str:
    return datetime.now().astimezone().isoformat()


def provenance(extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """生成结果文件的标准溯源头（OPS_SPEC 第 7.2 节）。"""
    head = {"git_commit": git_commit(), "timestamp": now_iso(), "seed": SEED}
    if extra:
        head.update(extra)
    return head


# ---------------------------------------------------------------- 读写

def save_json(obj: Any, path: str | Path, indent: int = 2) -> Path:
    """保存 JSON（UTF-8、不转义中文、自动建目录）。"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(obj, ensure_ascii=False, indent=indent, default=_json_default),
        encoding="utf-8",
    )
    return p


def load_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _json_default(o: Any) -> Any:
    """让 numpy / pandas 对象可被 json 序列化。

    注意顺序：必须先判 `tolist`，再判 `item`。
    因为 `ndarray.item()` 只对**单元素**数组有效，对多元素数组会抛
    `ValueError: can only convert an array of size 1 to a Python scalar`。
    """
    if isinstance(o, Path):
        return str(o)
    if hasattr(o, "tolist"):  # ndarray / pandas Series / Index
        return o.tolist()
    if hasattr(o, "item"):  # numpy 标量（np.float64 等）
        return o.item()
    if isinstance(o, (set, frozenset)):
        return sorted(o)
    raise TypeError(f"无法序列化的类型: {type(o)}")


def save_table(df: pd.DataFrame, path: str | Path, index: bool = False) -> Path:
    """保存论文用表格（UTF-8-BOM，便于 Excel 直接打开中文）。"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(p, index=index, encoding="utf-8-sig")
    return p


def load_table(path: str | Path, **kwargs: Any) -> pd.DataFrame:
    return pd.read_csv(path, **kwargs)


def save_metrics(
    question: str,
    metrics: dict[str, Any],
    params: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> tuple[Path, Path]:
    """保存某问的标准结果文件（OPS_SPEC 第 7.2 节）。

    返回 (metrics_path, params_path)。
    """
    from src.common.config import outputs_dir

    out = outputs_dir(question)
    head = provenance(extra)
    m = {"question": question, **head, "metrics": metrics}
    p = {"question": question, **head, "params": params or {}}
    return save_json(m, out / "metrics.json"), save_json(p, out / "params.json")


# ---------------------------------------------------------------- 日志

def get_logger(question: str, level: int = logging.INFO) -> logging.Logger:
    """获取同时输出到控制台与 outputs/<question>/run.log 的 logger。"""
    import sys

    from src.common.config import outputs_dir

    logger = logging.getLogger(question)
    logger.setLevel(level)
    logger.handlers.clear()

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S")

    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    logger.addHandler(sh)

    fh = logging.FileHandler(outputs_dir(question) / "run.log", encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    return logger
