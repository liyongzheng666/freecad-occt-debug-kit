"""triage_input 集成自测（真跑 FreeCADCmd）：python -m agent.tools.test_triage_input

验证失效分类判别量：box=90°/无曲率(→overflow)、wedge=近切(→geometric近切)、
pocket=凹曲率半径3(→geometric曲率 当 r>3)。FreeCADCmd 不在 → SKIP。

P1.3 追加：输入质量四项（convexity/short_edges/sliver_faces/tolerance_outliers）——
clean 形状全空/全凸（负例），pocket 盲孔底缘=唯一凹边（凹凸判别正例），
20x20x0.005 薄片（brep: 前缀载入）触发 short+sliver（正例）。
判别量（min_dihedral/curv）不变是回归断言：P1.3 只加报告，不动判别。
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from agent.contracts import TriageReport
from agent.tools.reproduce import _resolve_freecadcmd
from agent.tools.triage_input import triage_input


def _make_sliver_brep(timeout_s: int = 60) -> str | None:
    """一次性 FreeCADCmd 造 20x20x0.005 薄片 solid → brep（short+sliver 正例 fixture）。"""
    bin_path = _resolve_freecadcmd()
    tmp = Path(tempfile.mkdtemp(prefix="triage_sliver_"))
    brep = tmp / "sliver.brep"
    sp = tmp / "make.py"
    sp.write_text(
        "import Part\n"
        "Part.makeBox(20, 20, 0.005).exportBrep(%r)\n" % str(brep),
        encoding="utf-8")
    subprocess.run([str(bin_path), str(sp)], capture_output=True, text=True, timeout=timeout_s)
    return str(brep) if brep.exists() else None


def main() -> int:
    try:
        _resolve_freecadcmd()
    except FileNotFoundError as e:
        print(f"SKIP: {e}")
        return 0

    fails = []

    def check(name, cond):
        print(("PASS " if cond else "FAIL ") + name)
        if not cond:
            fails.append(name)

    box = triage_input("box")
    check("box 是 TriageReport", isinstance(box, TriageReport))
    check("box 非近切（min_dihedral≈90）", 80.0 < box.min_dihedral_deg < 100.0)
    check("box 无曲率约束（平面）", box.min_support_curv_radius is None)
    check("box 无近切边", len(box.near_tangent_pairs) == 0)

    wedge = triage_input("wedge")
    check("wedge 近切（min_dihedral < 10）", 0.0 <= wedge.min_dihedral_deg < 10.0)
    check("wedge 有近切边", len(wedge.near_tangent_pairs) >= 1)

    pocket = triage_input("pocket")
    check("pocket 有凹曲率约束（半径≈3）", pocket.min_support_curv_radius is not None and abs(pocket.min_support_curv_radius - 3.0) < 1e-6)

    # 判别一致性：分类阈值能把三态分开
    def classify(t, r):
        if 0.0 <= t.min_dihedral_deg < 10.0:
            return "geometric_near_tangent"
        if t.min_support_curv_radius is not None and r > t.min_support_curv_radius:
            return "geometric_curvature"
        return "algorithmic_overflow"

    check("box r=1000 → algorithmic_overflow", classify(box, 1000.0) == "algorithmic_overflow")
    check("wedge r=1 → geometric_near_tangent", classify(wedge, 1.0) == "geometric_near_tangent")
    check("pocket r=4 → geometric_curvature", classify(pocket, 4.0) == "geometric_curvature")
    check("pocket r=2 → algorithmic_overflow(≤曲率)", classify(pocket, 2.0) == "algorithmic_overflow")

    # —— P1.3 输入质量四项 ——
    # 凹凸：box 全凸（12 边）；pocket 恰有凹边（盲孔底缘）；wedge 脊边凸（薄楔仍是凸边）
    check("box convexity 全凸 12 边",
          len(box.convexity) == 12 and all(v == "convex" for v in box.convexity.values()))
    check("pocket 有凹边（盲孔底缘）", "concave" in pocket.convexity.values())
    check("pocket 凹边恰 1 条", sum(1 for v in pocket.convexity.values() if v == "concave") == 1)
    check("wedge 全凸（薄脊仍凸）", all(v == "convex" for v in wedge.convexity.values()))
    # clean 形状：短边/sliver/容差离群全空（负例）
    for name, t in (("box", box), ("wedge", wedge), ("pocket", pocket)):
        check(f"{name} 无短边/sliver/容差离群",
              t.short_edges == [] and t.sliver_faces == [] and t.tolerance_outliers == [])

    # short+sliver 正例：20x20x0.005 薄片（thin_eps≈0.028 > 0.005）
    brep = _make_sliver_brep()
    if brep:
        sl = triage_input("brep:" + brep)
        check("薄片触发 short_edges（4 条 0.005 竖边）", len(sl.short_edges) == 4)
        check("薄片触发 sliver_faces（4 个侧面）", len(sl.sliver_faces) == 4)
        check("薄片判别量不受新字段影响（min_dihedral=90）", 80.0 < sl.min_dihedral_deg < 100.0)
    else:
        print("SKIP 薄片正例（fixture 未产出）")

    print(f"\n{'ALL PASS' if not fails else str(len(fails)) + ' FAILED: ' + ', '.join(fails)}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
