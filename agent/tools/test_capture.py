"""capture 桥集成自测（真跑 lldb，~5s）：python -m agent.tools.test_capture

在已确认命中的 BRepFilletAPI_MakeFillet::Add 断点抓被 fillet 的边 → 真 BREP。
前置缺失（无 debug FreeCAD/OCCT/occ_capture）→ SKIP 退 0。
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from agent.tools.capture import _resolve, capture

_FAIL_FILLET = """import Part
box = Part.makeBox(10, 20, 30)
try:
    box.makeFillet(5.0, box.Edges)
except Exception as e:
    print("FILLET_EXC", type(e).__name__)
"""


def main() -> int:
    try:
        _resolve()
    except FileNotFoundError as e:
        print(f"SKIP: {e}")
        return 0

    fails = []

    def check(name, cond):
        print(("PASS " if cond else "FAIL ") + name)
        if not cond:
            fails.append(name)

    with tempfile.TemporaryDirectory(prefix="cap_test_") as d:
        script = Path(d) / "fail_fillet.py"
        script.write_text(_FAIL_FILLET, encoding="utf-8")
        got = capture(str(script), "BRepFilletAPI_MakeFillet.cxx:106", [("capdemo/edgeE", "E")])
        check("capture 返回 edgeE", "capdemo/edgeE" in got)
        if "capdemo/edgeE" in got:
            p = Path(got["capdemo/edgeE"])
            check("BREP 落盘非空", p.exists() and p.stat().st_size > 0)
            check("是合法 OCCT BREP", p.read_text(errors="replace").startswith("DBRep_DrawableShape"))

    print(f"\n{'ALL PASS' if not fails else str(len(fails)) + ' FAILED: ' + ', '.join(fails)}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
