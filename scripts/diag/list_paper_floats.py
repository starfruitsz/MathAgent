"""列出论文里所有 TABLE/FIGURE 调用的编号与资源名，检查编号是否连续、有无重号。

用法：
    python scripts/diag/list_paper_floats.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

SRC = Path("src/report/build_paper.py")


def main() -> int:
    s = SRC.read_text(encoding="utf-8")
    pat = re.compile(r'(TABLE|FIGURE)\(doc,\s*"([^"]+)"\s*,\s*"([^"]+)"')
    rows = []
    for m in pat.finditer(s):
        kind, name, cap = m.groups()
        num = re.search(r"(表|图)\s*(\d+)", cap)
        rows.append((kind, name, num.group(2) if num else "?", cap.strip()))

    print(f"{'类型':<8}{'编号':>5}  {'资源名':<28} 题注")
    print("-" * 100)
    for kind, name, num, cap in rows:
        print(f"{kind:<8}{num:>5}  {name:<28} {cap}")

    for kind, label in (("TABLE", "表"), ("FIGURE", "图")):
        nums = [int(n) for k, _, n, _ in rows if k == kind and n.isdigit()]
        dup = sorted({n for n in nums if nums.count(n) > 1})
        missing = sorted(set(range(1, max(nums) + 1)) - set(nums)) if nums else []
        print(f"\n{label}：{len(nums)} 个，范围 {min(nums)}~{max(nums)}" if nums else f"\n{label}：无")
        if dup:
            print(f"  ❌ 重号：{dup}")
        if missing:
            print(f"  ⚠️  缺号：{missing}")
        if not dup and not missing:
            print("  ✅ 编号连续且无重号")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
