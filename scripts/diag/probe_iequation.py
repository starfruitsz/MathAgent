"""MathType `IEquation` COM 接口（手写定义）与 OLE 对象重建。

背景
----
`docx-equation` 生成的 OLE 包装在 Word 中是"损坏"的：`OLEFormat.ProgID` 取不到、
`Activate()` 抛"此对象已损坏或不再可用"，因此**双击打不开**。
它内部的 `Equation Native` 流（MTEF 二进制）本身是有效的——所以正确做法是
**让 MathType 自己**把这段 MTEF 存成一个合法的 OLE 对象。

MathType 不提供类型库（CLSID 下无 `TypeLib` 子键），因此这里按已公开的
`IEquation` vtable 顺序手写接口定义。

`IEquation`（IID `{0002CE02-0000-0000-C000-000000000046}`）的 vtable 顺序：
    IUnknown / IDispatch 之后依次为
    GetApplication, GetEngine, SetEngine, Load, Save, SetInline, GetInline,
    SetDimension, GetDimension, SetLook, GetLook, SetColor, GetColor, Query

本模块只用其中的 `Load` / `Save` / `SetEngine`。
"""

from __future__ import annotations

import struct
import sys
from ctypes import POINTER, byref, c_int32, c_void_p
from pathlib import Path

IID_IEQUATION = "{0002CE02-0000-0000-C000-000000000046}"
CLSID_EQ = "{0002CE03-0000-0000-C000-000000000046}"

# MathType 版本 → 引擎（MTEF 版本）
MTEF_V3 = 3      # Equation Editor 3.x
MTEF_V5 = 5      # MathType 5 / 6 / 7（"DSMT4" ProgID 用 V5 引擎）


def _define_interface():
    """定义并注册 IEquation（延迟到调用时，避免无 comtypes 时导入失败）。"""
    import comtypes
    from comtypes import COMMETHOD, GUID, IUnknown, dispid

    class IEquation(IUnknown):
        _iid_ = GUID(IID_IEQUATION)
        _methods_ = [
            COMMETHOD([], HRESULT := comtypes.HRESULT, "GetApplication",
                      (["out"], POINTER(c_void_p), "app")),
            COMMETHOD([], HRESULT, "GetEngine",
                      (["out"], POINTER(c_int32), "engine")),
            COMMETHOD([], HRESULT, "SetEngine",
                      (["in"], c_int32, "engine")),
            COMMETHOD([], HRESULT, "Load",
                      (["in"], c_void_p, "stream")),
            COMMETHOD([], HRESULT, "Save",
                      (["in"], c_void_p, "stream")),
            COMMETHOD([], HRESULT, "SetInline",
                      (["in"], c_int32, "is_inline")),
            COMMETHOD([], HRESULT, "GetInline",
                      (["out"], POINTER(c_int32), "is_inline")),
            COMMETHOD([], HRESULT, "SetDimension",
                      (["in"], c_int32, "type"), (["in"], c_int32, "value")),
            COMMETHOD([], HRESULT, "GetDimension",
                      (["in"], c_int32, "type"), (["out"], POINTER(c_int32), "value")),
            COMMETHOD([], HRESULT, "SetLook",
                      (["in"], c_int32, "type"), (["in"], c_int32, "value")),
            COMMETHOD([], HRESULT, "GetLook",
                      (["in"], c_int32, "type"), (["out"], POINTER(c_int32), "value")),
            COMMETHOD([], HRESULT, "SetColor",
                      (["in"], c_int32, "type"), (["in"], c_int32, "value")),
            COMMETHOD([], HRESULT, "GetColor",
                      (["in"], c_int32, "type"), (["out"], POINTER(c_int32), "value")),
        ]

    return IEquation


def _make_stream(data: bytes):
    """把 bytes 放进一个 COM IStream。"""
    import comtypes
    from comtypes.persist import IStream  # noqa: F401  (存在性检查)

    return None


def probe_roundtrip(mtef: bytes, engine: int = MTEF_V5) -> tuple[bool, bytes, str]:
    """把 MTEF 交给 MathType 载入再存回，验证 MTEF 是否可被 MathType 解析。

    返回 (是否成功, 存回的字节, 说明)。
    """
    import comtypes
    import comtypes.client
    from comtypes import CoInitialize

    CoInitialize()
    IEquation = _define_interface()
    eq = comtypes.client.CreateObject("Equation.DSMT4", interface=IEquation)
    try:
        eq.SetEngine(engine)
    except Exception as exc:  # noqa: BLE001
        return False, b"", f"SetEngine({engine}) 失败：{exc}"

    # 用 pywin32 的 IStream（CreateStreamOnHGlobal）承载 MTEF
    import pythoncom

    stm_in = pythoncom.CreateStreamOnHGlobal()
    stm_in.Write(mtef)
    stm_in.Seek(0, 0)
    try:
        eq.Load(stm_in)
    except Exception as exc:  # noqa: BLE001
        return False, b"", f"Load 失败：{exc}"
    stm_out = pythoncom.CreateStreamOnHGlobal()
    try:
        eq.Save(stm_out)
    except Exception as exc:  # noqa: BLE001
        return False, b"", f"Save 失败：{exc}"
    stm_out.Seek(0, 0)
    out = stm_out.Read(1 << 20)
    return True, out, "OK"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root))
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from check_ole_streams import cfb_streams

    docx = root / "paper" / "山区洪涝灾害下无人机运输与通信协同优化_论文.docx"
    if not docx.exists():
        print(f"❌ 未找到 {docx}")
        return 1
    import zipfile

    with zipfile.ZipFile(docx) as z:
        name = sorted(n for n in z.namelist() if n.startswith("word/embeddings/"))[0]
        data = z.read(name)
    mtef = cfb_streams(data)["Equation Native"]
    print(f"样本 {name.rsplit('/', 1)[-1]}：Equation Native = {len(mtef)} bytes")
    print(f"  头: {mtef[:16].hex(' ')}")
    for engine in (MTEF_V5, MTEF_V3):
        ok, out, msg = probe_roundtrip(mtef, engine)
        print(f"  engine=V{engine}: ok={ok}  {msg}")
        if ok:
            print(f"    存回 {len(out)} bytes；头 {out[:16].hex(' ')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
