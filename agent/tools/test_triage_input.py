"""triage_input 集成自测（真跑 FreeCADCmd）：python -m agent.tools.test_triage_input

验证失效分类判别量：box=90°/无曲率(→overflow)、wedge=近切(→geometric近切)、
pocket=凹曲率半径3(→geometric曲率 当 r>3)。FreeCADCmd 不在 → SKIP。
"""
from __future__ import annotations

from agent.contracts import TriageReport
from agent.tools.reproduce import _resolve_freecadcmd
from agent.tools.triage_input import triage_input


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

    print(f"\n{'ALL PASS' if not fails else str(len(fails)) + ' FAILED: ' + ', '.join(fails)}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
