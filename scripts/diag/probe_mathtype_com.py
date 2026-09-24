"""诊断：用 MathType 的 COM 服务器尝试实例化 OLE 对象（验证"双击能否打开"）。

`Equation.DSMT4` 的 CLSID 为 {0002CE03-0000-0000-C000-000000000046}，
COM 接口 `IEquation` 的关键方法：
    SetEngine / GetEngine
    Load(stream)   —— 载入 `Equation Native` 流（MTEF）
    Save(stream)
    SetInline / GetInline
    Query 辅助方法

本脚本仅做"能否 CoCreate + Load"的探测，不修改文档。

用法：
    python scripts/diag/probe_mathtype_com.py
"""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

ROOT = Path(__file__).resolve().parents[2]
DOCX = ROOT / "paper" / "山区洪涝灾害下无人机运输与通信协同优化_论文.docx"
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "src"))

from check_ole_streams import cfb_streams  # noqa: E402  (同目录脚本)

CLSID = "{0002CE03-0000-0000-C000-000000000046}"


def main() -> int:
    import win32com.client as win32

    with zipfile.ZipFile(DOCX) as z:
        names = sorted(n for n in z.namelist() if n.startswith("word/embeddings/"))
        data = z.read(names[0])
    streams = cfb_streams(data)
    mtef = streams.get("Equation Native", b"")
    print(f"样本：{names[0].rsplit('/', 1)[-1]}  Equation Native = {len(mtef)} bytes")
    print(f"  MTEF 头: {mtef[:16].hex(' ')}")

    print("\n=== 尝试 CoCreateInstance ===")
    try:
        app = win32.Dispatch(f"Equation.DSMT4")
        print(f"  ✅ Dispatch('Equation.DSMT4') 成功 → {app}")
    except Exception as exc:  # noqa: BLE001
        print(f"  ❌ Dispatch 失败：{type(exc).__name__}: {exc}")
        return 1

    print("\n=== 尝试把 MTEF 载入并再取出（往返测试） ===")
    import pythoncom
    from win32com.client import gencache

    try:
        mod = gencache.EnsureModule(CLSID, 0, 1, 0)
        print(f"  typelib 模块：{mod}")
    except Exception as exc:  # noqa: BLE001
        print(f"  （无类型库，退化为 IDispatch 调用）：{str(exc)[:120]}")

    try:
        # IEquation 的 Load/Save 以 IStream 为参数；
        # 用 pywin32 的 COM 流封装尝试
        import win32com
        from win32com import storagecon  # noqa: F401

        stm = pythoncom.CreateStreamOnHGlobal()
        stm.Write(mtef)
        stm.Seek(0, 0)
        app.Load(stm)
        stm2 = pythoncom.CreateStreamOnHGlobal()
        app.Save(stm2)
        stm2.Seek(0, 0)
        back = stm2.Read(1 << 20)
        print(f"  ✅ Load/Save 往返成功：写回 {len(back)} bytes"
              f"（一致={back[:len(mtef)] == mtef[:len(back)]}）")
    except Exception as exc:  # noqa: BLE001
        print(f"  ❌ Load/Save 失败：{type(exc).__name__}: {str(exc)[:220]}")
        print("     （如果只是脚本调用方式问题，不代表双击打不开）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
