"""刷新 otheragent/ 论文工程的**数据快照**，并报告哪些文件语义上真的变了。

背景：`otheragent/`（第三方 agent 的 LaTeX 论文工程）内嵌了自己的一份
`tables/` 与 `data/` 快照。本仓库的求解结果更新后，需要把快照同步过去，
再重跑它的制表/绘图脚本。

用法：
    python scripts/tools/refresh_otheragent.py            # 只报告差异
    python scripts/tools/refresh_otheragent.py --apply    # 实际复制
"""

from __future__ import annotations

import argparse
import filecmp
import shutil
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

ROOT = Path(__file__).resolve().parents[2]
OT = ROOT / "otheragent"


def _same_text(a: Path, b: Path) -> bool:
    """按**去 BOM / 统一换行**后比较文本，避免行尾差异造成假阳性。"""
    try:
        ta = a.read_text(encoding="utf-8-sig", errors="ignore").replace("\r\n", "\n")
        tb = b.read_text(encoding="utf-8-sig", errors="ignore").replace("\r\n", "\n")
        return ta == tb
    except Exception:  # noqa: BLE001
        return filecmp.cmp(a, b, shallow=False)


def build_pairs() -> list[tuple[Path, Path, str]]:
    """(源文件, 目标文件, 类别)。"""
    out: list[tuple[Path, Path, str]] = []
    for f in sorted((ROOT / "paper" / "tables").iterdir()):
        if f.is_file():
            out.append((f, OT / "tables" / f.name, "表"))
    for q in ("q1", "q2", "q3", "q4"):
        d = ROOT / "outputs" / q / "tables"
        if d.exists():
            for f in sorted(d.iterdir()):
                if f.is_file():
                    out.append((f, OT / "tables" / f.name, "表"))
    for q in ("q1", "q2", "q3", "q4"):
        for nm, dst in (("metrics.json", f"{q}_metrics.json"),
                        ("params.json", f"{q}_params.json"),
                        ("feasibility.json", f"{q}_feasibility.json")):
            s = ROOT / "outputs" / q / nm
            if s.exists():
                out.append((s, OT / "data" / dst, "指标"))
    for d in (ROOT / "paper" / "data",
              ROOT / "paper" / "by_question" / "common" / "data"):
        if d.exists():
            for f in sorted(d.iterdir()):
                if f.is_file():
                    out.append((f, OT / "data" / f.name, "数据"))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="实际复制（默认只报告）")
    args = ap.parse_args()

    if not OT.exists():
        print(f"❌ 未找到 {OT}（请先取出 otheragent/ 目录）")
        return 1

    pairs = build_pairs()
    changed: list[tuple[Path, Path, str]] = []
    missing: list[Path] = []
    for s, d, kind in pairs:
        if not d.exists():
            missing.append(d)
            continue
        if not _same_text(s, d):
            changed.append((s, d, kind))

    print(f"比对 {len(pairs)} 个文件：语义有差异 {len(changed)} 个；目标缺失 {len(missing)} 个")
    for s, d, kind in changed:
        print(f"  [{kind}] {d.relative_to(ROOT)}")
    for d in missing:
        print(f"  [缺失] {d.relative_to(ROOT)}")

    if not args.apply:
        print("\n（未做修改；加 --apply 执行复制）")
        return 0

    n = 0
    for s, d, _ in changed:
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(s, d)
        n += 1
    for d in missing:
        # 缺失的按源文件名在 tables/ 或 data/ 里找同名源
        cand = [s for s, dd, _ in pairs if dd == d]
        if cand:
            d.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(cand[0], d)
            n += 1
    print(f"\n✅ 已刷新 {n} 个快照文件")
    print("接下来需要重跑 otheragent 的制表与绘图脚本：")
    print("  python otheragent/code/make_tables.py")
    print("  python otheragent/code/fig_common.py  # 及 fig_q1..q4, fig_check")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
