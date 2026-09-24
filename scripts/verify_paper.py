"""一键回归：构建论文 → 结构自检 → Word 页数/对象统计 → 导出 PDF。

用法：
    python scripts/verify_paper.py            # 全流程
    python scripts/verify_paper.py --no-build # 跳过构建，只做校验与导出
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
ROOT = Path(__file__).resolve().parents[1]


def run(cmd: list[str]) -> int:
    print(f"\n$ {' '.join(cmd)}")
    return subprocess.call(cmd, cwd=str(ROOT))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-build", action="store_true")
    ap.add_argument("--no-pdf", action="store_true")
    args = ap.parse_args()

    steps: list[tuple[str, list[str]]] = []
    if not args.no_build:
        steps.append(("构建论文（含 MathType 转换）",
                      [sys.executable, "-m", "src.report.build_paper"]))
    steps.append(("结构自检", [sys.executable, "scripts/check_docx_structure.py"]))
    steps.append(("页数与体量" + ("" if args.no_pdf else " + PDF 导出"),
                  [sys.executable, "scripts/check_paper.py"] + ([] if args.no_pdf else ["--pdf"])))

    codes = []
    for name, cmd in steps:
        print("=" * 70)
        print(f"▶ {name}")
        print("=" * 70)
        codes.append(run(cmd))

    print("\n" + "=" * 70)
    for (name, _), c in zip(steps, codes):
        print(f"  {'✅' if c == 0 else '❌'} {name}  (exit {c})")
    return 0 if all(c == 0 for c in codes) else 1


if __name__ == "__main__":
    raise SystemExit(main())
