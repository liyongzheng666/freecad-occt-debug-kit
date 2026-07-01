"""A7 WP1+WP5 自测：python -m agent.loop.test_investigate_ssi

纯逻辑（无需 LLDB/FreeCAD）：
  _ssi_verdict —— SSIReport → S3 候选裁定（fired/ruled_out/untestable）的映射；
  _ssi_discriminate —— 无登记现场（spec=None）照实 untestable（不伪绿、不崩、不碰 FreeCAD）。
集成（需前置，缺则 SKIP）：
  _ssi_discriminate box —— env_emit 路径（WP5，需 FreeCADCmd + 改造后 debug OCCT）→ fired；
  _ssi_discriminate wedge —— lldb 路径（WP1，需 LLDB 前置）→ 真跑归 tools.test_capture。
"""
from __future__ import annotations

from agent.contracts import SSIReport
from agent.loop.investigate import _ssi_discriminate, _ssi_verdict
from agent.tools.capture import prereqs_ok
from agent.tools.reproduce import _resolve_freecadcmd


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

    # _ssi_discriminate：无登记现场（pocket 未登记 SSI 现场，spec=None）→ untestable，
    # 纯逻辑（spec is None 即返回，不碰 capture/FreeCAD）。注意 box 自 WP5 起已登记
    # env_emit 现场（不再是"无现场"），box 的真跑归下方集成段。
    st, ev = _ssi_discriminate("pocket", 1.0, [], False)
    check("pocket 无现场 → untestable", st == "untestable")
    check("untestable 证据点名'无已登记'（非 S3 排除）", "无已登记" in ev)

    # _ssi_discriminate box：WP5 env_emit 路径——需 FreeCADCmd + 改造后 debug OCCT
    # （StripeEdgeInter 落盘两 blend 面）。缺 FreeCADCmd → SKIP（不伪绿）。
    try:
        _resolve_freecadcmd()
    except FileNotFoundError as e:
        print(f"SKIP box env_emit 集成: {e}")
    else:
        sink = []
        st, ev = _ssi_discriminate("box", 5.0, sink, False)
        check("box env_emit → fired（真实 overlap 型 S3，非 fixture）", st == "fired")
        check("box fired 证据点名 S3 签名", "S3" in ev)
        check("box 发 capture_ssi_env 工具调用", any(t.tool == "capture_ssi_env" for t in sink))

    # _ssi_discriminate：wedge 有现场（lldb 路径）——缺 LLDB 前置时照实 untestable（不伪绿、不抛）；
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
