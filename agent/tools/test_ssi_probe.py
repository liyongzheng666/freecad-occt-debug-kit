"""ssi_probe 集成自测（真跑 FreeCADCmd 面面求交）：python -m agent.tools.test_ssi_probe

断言 S3 机制签名能把"近切退化(失效)"与"干净横切(正常)"分开。FreeCADCmd 不在 → SKIP。
"""
from __future__ import annotations

from agent.contracts import SSIReport
from agent.tools.reproduce import _resolve_freecadcmd
from agent.tools.ssi_probe import ssi_probe


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

    reports = {}
    print(f"{'fixture':14} {'ssi':>4} {'sec':>4} {'dihedral':>9} {'gap':>8} {'nearTan':>8} {'S3sig':>6}")
    print("-" * 62)
    for fx in ["transversal", "secant", "tangent", "near-tangent"]:
        r = ssi_probe(fixture=fx)
        reports[fx] = r
        print(f"{fx:14} {r.n_curves_ss:>4} {r.n_section_edges:>4} "
              f"{r.min_dihedral_deg:>9} {r.gap:>8} {str(r.near_tangent):>8} {str(r.s3_signature):>6}"
              + ("" if not r.notes.startswith("ssi_probe 失败") else "  <" + r.notes + ">"))

    t = reports["transversal"]
    check("transversal → 有界接触边 >=1", t.n_section_edges >= 1)
    check("transversal → 非近切", t.near_tangent is False)
    check("transversal → S3 签名 False", t.s3_signature is False)

    nt = reports["near-tangent"]
    check("near-tangent → 近切 True", nt.near_tangent is True)
    check("near-tangent → 期望接触却 0(退化)", nt.degenerate_contact is True)
    check("near-tangent → S3 签名 True", nt.s3_signature is True)
    check("near-tangent → 有间隙 gap>0", nt.gap > 0)

    # 判别力：S3 签名只在近切退化时点亮，干净横切时熄灭
    check("判别：transversal≠near-tangent 的 S3 签名", t.s3_signature != nt.s3_signature)
    check("返回类型 SSIReport", all(isinstance(r, SSIReport) for r in reports.values()))

    print(f"\n{'ALL PASS' if not fails else str(len(fails)) + ' FAILED: ' + ', '.join(fails)}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
