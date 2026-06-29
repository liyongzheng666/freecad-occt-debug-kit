"""capture 桥自测：python -m agent.tools.test_capture

两段：
1) 纯逻辑（始终跑，无需 LLDB）——capture_spec_for / make_fail_script。
2) 真跑 lldb（~5s，缺 debug FreeCAD/OCCT/occ_capture → SKIP 退 0）——边 capture +
   wedge 近切现场 capture_ssi（StartSol HS1/HS2，见记忆 fillet-startsol-capture-point）。
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from agent.tools.capture import (
    _resolve, capture, capture_spec_for, capture_ssi, make_fail_script,
)

_FAIL_FILLET = """import Part
box = Part.makeBox(10, 20, 30)
try:
    box.makeFillet(5.0, box.Edges)
except Exception as e:
    print("FILLET_EXC", type(e).__name__)
"""


def main() -> int:
    fails = []

    def check(name, cond):
        print(("PASS " if cond else "FAIL ") + name)
        if not cond:
            fails.append(name)

    # —— 1) 纯逻辑（无需 LLDB）——
    spec = capture_spec_for("wedge")
    check("wedge 有登记 capture 现场", spec is not None)
    check("wedge 断点 = StartSol", spec and spec["breakpoint"] == "ChFi3d_Builder_2.cxx:944")
    check("wedge 两面表达式具名", spec and spec["face_a_expr"] == "HS1->Face()"
          and spec["face_b_expr"] == "HS2->Face()")
    check("box overflow 无登记现场（匿名 DStr）", capture_spec_for("box") is None)

    with tempfile.TemporaryDirectory(prefix="failscript_") as d:
        sp = Path(make_fail_script("wedge", 1.0, out_dir=d))
        body = sp.read_text(encoding="utf-8")
        check("fail_script 落盘", sp.exists())
        check("fail_script 复用 build_shape", "from _fillet_harness import build_shape" in body)
        check("fail_script 调 makeFillet(r)", "shape.makeFillet(1.0" in body)
        check("fail_script 锁定 case", 'build_shape(\'wedge\')' in body or 'build_shape("wedge")' in body)

    # —— 2) 真跑 lldb（缺前置 → SKIP，不算失败）——
    try:
        _resolve()
    except FileNotFoundError as e:
        print(f"\nSKIP lldb 集成: {e}")
        print(f"\n{'ALL PASS' if not fails else str(len(fails)) + ' FAILED: ' + ', '.join(fails)}")
        return 1 if fails else 0

    with tempfile.TemporaryDirectory(prefix="cap_test_") as d:
        script = Path(d) / "fail_fillet.py"
        script.write_text(_FAIL_FILLET, encoding="utf-8")
        got = capture(str(script), "BRepFilletAPI_MakeFillet.cxx:106", [("capdemo/edgeE", "E")])
        check("capture 返回 edgeE", "capdemo/edgeE" in got)
        if "capdemo/edgeE" in got:
            p = Path(got["capdemo/edgeE"])
            check("BREP 落盘非空", p.exists() and p.stat().st_size > 0)
            check("是合法 OCCT BREP", p.read_text(errors="replace").startswith("DBRep_DrawableShape"))

        # wedge 近切现场 capture_ssi → 真支撑面跑 ssi_probe（truth_run：1.72° near_tangent）
        spec = capture_spec_for("wedge")
        fail_wedge = make_fail_script("wedge", 1.0, out_dir=d)
        rep = capture_ssi(fail_wedge, spec["breakpoint"], spec["face_a_expr"], spec["face_b_expr"],
                          tangent_eps_deg=10.0)
        check("wedge capture_ssi 近切命中", rep.near_tangent and 0.0 < rep.min_dihedral_deg < 10.0)
        check("wedge 非 S3（section 有 contact 边）", not rep.s3_signature and rep.n_section_edges >= 1)

    print(f"\n{'ALL PASS' if not fails else str(len(fails)) + ' FAILED: ' + ', '.join(fails)}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
