"""一次性维护脚本：把论文里 Q2 的 5 张表各减 1，使全表编号 1..26 连续。

背景：§5.4 新增了“问题二四目标权衡”表，插在 Q2 表格末尾，
导致原 表19(t_q3_diagnosis) 与新表重号、且 表14 缺号。
用法：python scripts/diag/renumber_q2_tables.py
"""

from __future__ import annotations

import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

P = pathlib.Path("src/report/build_paper.py")

SUBS = [
    ("表 15  问题二运输架次明细", "表 14  问题二运输架次明细"),
    ("表 16  实体无人机使用统计", "表 15  实体无人机使用统计"),
    ("表 17  共享电池使用次数", "表 16  共享电池使用次数"),
    ("表 18  逐箱时限达成明细", "表 17  逐箱时限达成明细"),
    ("表 19  问题二四目标权衡", "表 18  问题二四目标权衡"),
    ("四目标之间的权衡关系见表 19：", "四目标之间的权衡关系见表 18："),
    ("结果见表 13、表 14 与图 12。", "结果见表 13 与图 12。"),
]


def main() -> int:
    s = P.read_text(encoding="utf-8")
    for a, b in SUBS:
        n = s.count(a)
        print(f"{'OK ' if n == 1 else f'x{n} '} {a[:52]}")
        s = s.replace(a, b)
    P.write_text(s, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
