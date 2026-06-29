"""A7 WP1 自测：python -m agent.loop.test_investigate_ssi

纯逻辑（无需 LLDB/FreeCAD）：
  _ssi_verdict —— SSIReport → S3 候选裁定（fired/ruled_out/untestable）的映射；
  _ssi_discriminate —— 无登记现场 / 缺前置时照实 untestable（不伪绿、不崩）。
"""
from __future__ import annotations

from agent.contracts import SSIReport
from agent.loop.investigate import _ssi_discriminate, _ssi_verdict
from agent.tools.capture import prereqs_ok


def _rep(**kw) -> SSIReport:
    base = dict(n_curves_ss=1, n_section_edges=1, min_dihedral_deg=30.0, gap=0.0,
                near_tangent=False, degenerate_contact=False, s3_signature=False, notes="")
    base.update(kw)
    return SSIReport(**base)


def main() -> int:
    fails = []

    def check(name, cond):
        print(("PASS " if cond else "FAIL ") + name)
        if not cond:
            fails.append(name)

    # s3_signature → fired
    st, _ = _ssi_verdict(_rep(near_tangent=True, n_section_edges=0,
                              degenerate_contact=True, s3_signature=True, min_dihedral_deg=1.7))
    check("s3_signature → fired", st == "fired")

    # 近切但 section 有 contact 边 → ruled_out（实属 S2 StartSol，正是 wedge 真值）
    st, ev = _ssi_verdict(_rep(near_tangent=True, n_section_edges=1, min_dihedral_deg=1.72))
    check("近切+有 contact → ruled_out", st == "ruled_out")
    check("ruled_out 证据点名 S2", "S2" in ev)

    # clean 横切 → ruled_out（归 S2/S5）
    st, _ = _ssi_verdict(_rep(near_tangent=False, n_section_edges=2, min_dihedral_deg=45.0))
    check("clean 横切 → ruled_out", st == "ruled_out")

    # 探针失败哨兵 → untestable（不把工具失败误判成 S3 排除）
    st, _ = _ssi_verdict(_rep(n_curves_ss=-1, n_section_edges=-1, min_dihedral_deg=-1.0,
                              notes="ssi_probe 失败：…"))
    check("探针哨兵 → untestable", st == "untestable")

    # _ssi_discriminate：无登记现场（box overflow，匿名 DStr）→ untestable，不崩
    st, ev = _ssi_discriminate("box", 1000.0, [], False)
    check("box 无现场 → untestable", st == "untestable")

    # _ssi_discriminate：wedge 有现场——缺 LLDB 前置时照实 untestable（不伪绿、不抛）；
    # 有前置则真跑（~5s）归 tools.test_capture 集成，纯测里跳过避免拉 LLDB。
    if prereqs_ok():
        print("SKIP wedge _ssi_discriminate 真跑（本机有 LLDB 前置，见 tools.test_capture）")
    else:
        st, _ = _ssi_discriminate("wedge", 1.0, [], False)
        check("wedge 缺前置 → untestable（非 S3 排除）", st == "untestable")

    print(f"\n{'ALL PASS' if not fails else str(len(fails)) + ' FAILED: ' + ', '.join(fails)}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
