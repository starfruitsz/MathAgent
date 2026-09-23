"""环境自检：输出 Python 与关键库版本，写入 outputs/env_report.json。

用法：
    python scripts/check_env.py
"""

from __future__ import annotations

import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# Windows 控制台默认 GBK，中文输出会乱码 —— 强制 UTF-8
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

# OPS_SPEC 第 2.2 节列出的核心栈
REQUIRED = [
    "numpy",
    "scipy",
    "pandas",
    "pyarrow",
    "statsmodels",
    "sklearn",
    "lmfit",
    "iminuit",
    "pymoo",
    "cvxpy",
    "dowhy",
    "econml",
    "mapie",
    "powerlaw",
    "matplotlib",
    "seaborn",
    "yaml",
    "tqdm",
    "joblib",
    "pytest",
]

# 导入名与包名不一致的情况
DIST_NAME = {"sklearn": "scikit-learn", "yaml": "PyYAML"}

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_PATH = REPO_ROOT / "outputs" / "env_report.json"


def git_commit() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        return out.stdout.strip()
    except Exception:
        return "unknown"


def probe() -> tuple[dict[str, str], list[str]]:
    found: dict[str, str] = {}
    missing: list[str] = []
    for mod in REQUIRED:
        try:
            m = __import__(mod)
            found[mod] = getattr(m, "__version__", "unknown")
        except Exception:
            missing.append(DIST_NAME.get(mod, mod))
    return found, missing


def main() -> int:
    found, missing = probe()

    report = {
        "timestamp": datetime.now(timezone.utc).astimezone().isoformat(),
        "git_commit": git_commit(),
        "python": {
            "version": sys.version.split()[0],
            "implementation": platform.python_implementation(),
            "executable": sys.executable,
        },
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
        },
        "cpu_count": __import__("os").cpu_count(),
        "packages_found": found,
        "packages_missing": missing,
        "status": "ok" if not missing else "incomplete",
    }

    # 内存（可选，失败不影响）
    try:
        import psutil  # type: ignore

        report["memory_total_gb"] = round(psutil.virtual_memory().total / 1024**3, 2)
    except Exception:
        report["memory_total_gb"] = None

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"Python      : {report['python']['version']} ({report['python']['implementation']})")
    print(f"Platform    : {report['platform']['system']} {report['platform']['release']}")
    print(f"CPU cores   : {report['cpu_count']}")
    print(f"Memory (GB) : {report['memory_total_gb']}")
    print(f"Git commit  : {report['git_commit']}")
    print(f"Report      : {OUT_PATH.relative_to(REPO_ROOT)}")
    print()

    if found:
        print("已安装：")
        for k, v in sorted(found.items()):
            print(f"  [OK]   {k:<14} {v}")
    if missing:
        print("\n缺失（需 pip install）：")
        for k in missing:
            print(f"  [MISS] {k}")
        print("\n安装命令： pip install -r requirements.txt")
        print("若某库安装失败，必须在 OPS_SPEC 第 9 节登记替代方案。")
    else:
        print("\n全部核心依赖就绪。")

    return 0 if not missing else 1


if __name__ == "__main__":
    raise SystemExit(main())
