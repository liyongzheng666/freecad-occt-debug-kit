"""决策空间② 自测：python -m agent.loop.test_investigate_falsegreen

假绿（IsDone=true 但 invalid）此前是分支 B 的**零决策**硬启发式（self-int→S3 否则 S6）；
现走 playbook `fillet-falsegreen-invalid` 三候选判别（与 NotDone 签名共用 decide 接缝）：
  S2  fg_support_probe   支撑面含参数面（BSpline/Bezier/回转/拉伸）→ bsurf 族
  S3  fg_selfint_mid     存在**非端局部**自交（带-带中段交叠）
  S4  fg_endcap_probe    有自由端 且 缺陷面端局部（d_end≤0.1 且 <d_mid）→ 端盖构造
全排除/probe 失败 → 兜底 = 原启发式**逐位一致**（thinplate/E4 回归保护）。

三层验证：① 纯裁定函数（无 FreeCAD）② 四锚点端到端（E7→S4 / E8→S2 /
thinplate→S3 / E4→S6 兜底）③ 回归量（conf=0.65 / depth / chain 含 GT symptom）。
实证锚点（2026-07-02 locality 实测）：E7 d_end=0.000 / E4 F11 d_end=14.0 / E8 d_end≈1.9。
"""
from __future__ import annotations


def main() -> int:
    from agent.loop.investigate import (
        _fg_end_local, _fg_endcap_verdict, _fg_selfint_verdict, _fg_support_verdict,
    )

    fails = []

    def check(name, cond):
        print(("PASS " if cond else "FAIL ") + name)
        if not cond:
            fails.append(name)

    # —— ① 纯裁定（无需 FreeCAD）——
    check("support: BSpline → fired",
          _fg_support_verdict({"support_types": ["BSplineSurface", "Plane"]})[0] == "fired")
    check("support: 全解析 → ruled_out",
          _fg_support_verdict({"support_types": ["Plane", "Cylinder"]})[0] == "ruled_out")

    loc_end = {"fid": "F5", "d_end": 0.0, "d_mid": 7.0}
    loc_far = {"fid": "F11", "d_end": 14.0, "d_mid": 17.2}
    loc_none = {"fid": "F1", "d_end": None, "d_mid": 3.0}
    check("end_local: d_end=0 → True", _fg_end_local(loc_end))
    check("end_local: d_end=14 → False", not _fg_end_local(loc_far))
    check("end_local: 无自由端(d_end=None) → False", not _fg_end_local(loc_none))

    check("endcap: 无自由端 → ruled_out",
          _fg_endcap_verdict({"free_ends": [], "defect_locality": [loc_end]})[0] == "ruled_out")
    check("endcap: 自由端+端局部缺陷 → fired",
          _fg_endcap_verdict({"free_ends": [[0, 0, 0]], "defect_locality": [loc_end]})[0] == "fired")
    check("endcap: 自由端+远缺陷 → ruled_out",
          _fg_endcap_verdict({"free_ends": [[0, 0, 0]], "defect_locality": [loc_far]})[0] == "ruled_out")

    fg_mid = {"free_ends": [], "defect_locality": [loc_none]}
    check("selfint: 无自交 fid → ruled_out", _fg_selfint_verdict(fg_mid, [])[0] == "ruled_out")
    check("selfint: 非端局部自交 → fired", _fg_selfint_verdict(fg_mid, ["F1"])[0] == "fired")
    check("selfint: 全端局部自交 → ruled_out（归端盖）",
          _fg_selfint_verdict({"free_ends": [[0, 0, 0]], "defect_locality": [loc_end]}, ["F5"])[0] == "ruled_out")

    # —— ② 四锚点端到端（缺 FreeCADCmd → SKIP）——
    from agent.tools.reproduce import _resolve_freecadcmd
    try:
        _resolve_freecadcmd()
    except FileNotFoundError as e:
        print(f"\nSKIP 端到端段: {e}")
        print("\n" + ("ALL PASS" if not fails else f"{len(fails)} FAIL: {fails}"))
        return 1 if fails else 0

    from agent.loop.investigate import investigate

    def run(case, r, e):
        c = investigate(case, radius=r, edges=e, policy="rule")
        return c.hypotheses[0]

    h7 = run("step:agent/cases/models/E7_cylboss_endcorner.step", 4.0, "6")
    check("E7 → root S4（端盖构造）", h7.stage.value == "S4")
    check("E7 chain=[S4,S6]", [s.value for s in h7.chain] == ["S4", "S6"])
    check("E7 conf=0.65（与兜底同构）", h7.confidence == 0.65)

    h8 = run("step:agent/cases/models/E8_loft_bspline.step", 3.0, "3")
    check("E8 → root S2（bsurf 支撑）", h8.stage.value == "S2")
    check("E8 chain=[S2,S6]", [s.value for s in h8.chain] == ["S2", "S6"])

    hthin = run("box-flat", 1.5, None)
    check("thinplate → root S3（中段自交，回归）", hthin.stage.value == "S3")
    check("thinplate conf=0.65 depth=entity（回归）",
          hthin.confidence == 0.65 and hthin.localization_depth == "entity")
    check("thinplate chain 含 S3（scorer symptom 命中不变）", "S3" in [s.value for s in hthin.chain])

    h4 = run("step:agent/cases/models/E4_concave_groove_r8.step", 15.0, "8")
    check("E4 → root S6（全候选排除 → 兜底，回归）", h4.stage.value == "S6")
    check("E4 chain=[S6]（兜底逐位一致）", [s.value for s in h4.chain] == ["S6"])

    print("\n" + ("ALL PASS" if not fails else f"{len(fails)} FAIL: {fails}"))
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
