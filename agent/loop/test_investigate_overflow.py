"""P2.1 自测：python -m agent.loop.test_investigate_overflow

overflow 二分（G1/G2，Parasolid Ch74 + §77.3.4 loop_c）：单条 blend 边不存在"相邻带"，
不可能是 band-band 重叠，故 _classify_s2_failure 的 else 分支须按 blend 边数二分——
  单边(count==1)  → face_overflow      （单带 overflow：blend 离开面/伸出 loop）
  多边(count>=2)  → algorithmic_overflow（两带重叠：StripeEdgeInter 'too big radiuses'）

判别本身走 investigate() 真跑（需 FreeCADCmd + occ-debug-mesh）；缺前置 → SKIP（不假绿）。
fixture = agent/cases/models/E{2,3,5,6}_*.step（gen_final.py 生成，manifest 记录 verified_fillet）。
"""
from __future__ import annotations

from pathlib import Path

_MODELS = Path(__file__).resolve().parents[1] / "cases" / "models"

# (step 文件, radius, edges, 期望 failure_class)
_CASES = [
    ("E2_thinbar_overlap_r3", 3.0, "1,3,5,7", "algorithmic_overflow"),  # 4 边 → 两带重叠
    ("E3_thinplate_loop_overflow_r5", 5.0, "1", "face_overflow"),       # 单边 → 单带 overflow
    ("E5_overflow_boss_r20", 20.0, "6", "face_overflow"),               # 单边 → 单带 overflow
    ("E6_wedge_thin_r5", 5.0, "11", "face_overflow"),                   # 单边 → 单带 overflow
]


def main() -> int:
    from agent.loop.investigate import investigate

    fails = []

    def check(name, cond):
        print(("PASS " if cond else "FAIL ") + name)
        if not cond:
            fails.append(name)

    # box-r5 回归：全 12 边 → 必须仍是 algorithmic_overflow（改动不得回归旗舰 case）
    try:
        c = investigate("box", radius=5.0, policy="rule")
    except FileNotFoundError as e:
        print("SKIP （缺 FreeCADCmd/occ-debug-mesh）：" + str(e)[:70])
        return 0
    check("box-r5(全边) → algorithmic_overflow（回归）",
          c.hypotheses and c.hypotheses[0].failure_class == "algorithmic_overflow")

    for stem, r, edges, want in _CASES:
        step = _MODELS / f"{stem}.step"
        if not step.exists():
            print(f"SKIP {stem}（无 step 资产）")
            continue
        c = investigate(f"step:{step}", radius=r, edges=edges, policy="rule")
        got = c.hypotheses[0].failure_class if c.hypotheses else None
        check(f"{stem}(edges={edges}) → {want}", got == want)
        # 单带 case 额外断言：cause 不再谎称"两相邻圆角面重叠"
        if want == "face_overflow" and c.hypotheses:
            check(f"{stem} cause 不含'两相邻...重叠'（假机制已去）",
                  "两相邻" not in c.hypotheses[0].cause)

    print("\n" + ("ALL PASS" if not fails else f"{len(fails)} FAIL: {fails}"))
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
