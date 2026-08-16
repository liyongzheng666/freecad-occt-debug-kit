"""chamfer 方向性根因 demo —— C4「让 LLM 显质量价值」的证伪实验（P1a / B6）。

**C4 命题（INTERVIEW-PREP Q21/Q28）**：fillet 根因是 order-independent 的（任一 distal 候选命中即
定根、与探针顺序无关），故 rule 顺序穷尽已近最优、LLM 臂只能赢成本不赢质量。证伪靶（Q27/Part6）：
一个**决策空间更大、非 order-independent** 的域。

**chamfer 提供了那个轴——双距 d1/d2 的方向性**（fillet 单半径没有的自由度）：当对称 d 溢出、但
**非对称** d1/d2 能恢复时，"哪个方向的距离必须减小"精确指认**哪张支撑面是约束**。这是一个
fillet 无法表达的、实体级的**方向性根因**。

实测锚点（box 6×40×30 的一条棱，两侧支撑面 6-宽 / 40-宽）：
  对称 d=6.0 → NotDone（radius_probe 只能说"S2 溢出"，stage 级）
  非对称 d1=8,d2=3 → OK ；d1=3,d2=8 → NotDone  → 约束在"进入 6-宽面的那个距离"（方向性、entity 级）

**order-dependence（C4 的牙齿）**：radius_probe（对称降距）一命中就定 S2、**stage 级**收；要拿到
方向性根（哪张面约束）**必须**多跑一步 asymmetric_distance_probe——rule 臂固定 distal→proximate 序、
S2 一 fired 就早停，够不到这步；一个会"看几何不对称→加跑方向探针"的**推理策略**才够得到 entity 级。
这正是 LLM 臂**可能赢质量**的地方。

**诚实边界**：本 demo 证明了①方向性根因真实存在、②它比对称 radius_probe 深一级（stage→directional-
entity 的定位增量）。它**没有**跑完整 LLM claude_cli A/B（那是下一步）；其它 chamfer 族（溢出/近切/
曲率）实测仍 order-independent → 对它们 C4 死胡同**依旧成立**。即：C4 的证伪是**窄**的、只在方向性族
翻案，不是全盘推翻——诚实结论比硬造一个"LLM 全面赢"更可信。

用法：python -m agent.demo.chamfer_directional   （缺 FreeCADCmd → SKIP）
"""
from __future__ import annotations

from agent.tools.reproduce import reproduce


def _feasible(case, d, edges, *, dist2=None) -> bool:
    """chamfer 是否跑完产形状（这里只关心 NotDone/produced，不复判有效性——溢出是硬 NotDone）。"""
    run = reproduce(case, radius=d, edges=edges, op="chamfer", dist2=dist2)
    return run.status == "ok" and run.is_done


def directional_root(case: str, edges: str, sym_d: float, *, hi: float, lo: float) -> dict:
    """对一条对称溢出的 chamfer 棱，用非对称双距指认**约束方向**（哪张支撑面是约束）。

    返回 {symmetric_overflow, constraining_side, evidence}：
      constraining_side ∈ {"face_A"(d1，第一支撑面) | "face_B"(d2，第二支撑面) | "both/none"}。
    机制：把大距放在非约束面、小距放在约束面即可恢复 → 谁减小谁恢复，谁就是约束。
    """
    sym = _feasible(case, sym_d, edges)                       # 对称基线：应溢出（NotDone）
    a_ok = _feasible(case, hi, edges, dist2=lo)               # d1=hi(非约束), d2=lo(约束) → 恢复?
    b_ok = _feasible(case, lo, edges, dist2=hi)               # d1=lo, d2=hi → 恢复?
    if not sym and a_ok and not b_ok:
        side, why = "face_B(d2)", f"d1={hi},d2={lo} 恢复 / d1={lo},d2={hi} 仍崩 → 进入第二支撑面的距离(d2)是约束"
    elif not sym and b_ok and not a_ok:
        side, why = "face_A(d1)", f"d1={lo},d2={hi} 恢复 / d1={hi},d2={lo} 仍崩 → 进入第一支撑面的距离(d1)是约束"
    elif not sym and (a_ok or b_ok):
        side, why = "both/either", "两向非对称都能恢复 → 非单面约束（对称过大）"
    else:
        side, why = "inconclusive", f"对称 d={sym_d} 未溢出或非对称均不恢复 → 无方向性信号"
    return {"symmetric_overflow": not sym, "constraining_side": side, "evidence": why}


def main() -> int:
    try:
        from agent.tools.reproduce import _resolve_freecadcmd
        _resolve_freecadcmd()
    except FileNotFoundError as e:
        print(f"SKIP: {e}")
        return 0
    case, edges, sym_d = "boxp:6,40,30", "1", 6.0
    print(f"== chamfer 方向性根因 demo：{case} edge#{edges} 对称 d={sym_d} ==\n")
    # 对称视角：radius_probe 能说到的极限 = stage 级"S2 溢出"
    print(f"[对称 radius_probe 视角] d={sym_d} → NotDone；降对称 d 能恢复 → 定位 = 'S2 溢出'（stage 级，"
          "指不出哪张面约束）")
    # 方向性视角：asymmetric_distance_probe → entity 级
    r = directional_root(case, edges, sym_d, hi=8.0, lo=3.0)
    print(f"[非对称 directional_probe 视角] 约束方向 = {r['constraining_side']}")
    print(f"   证据：{r['evidence']}")
    print(f"\n结论（C4）：chamfer 的方向性根（{r['constraining_side']}）比对称 radius_probe 的 'S2 溢出' 深一级"
          "（stage→directional-entity）。取到它需**多跑一步方向探针**——固定序的 rule 臂 S2 早停够不到，"
          "会'看几何不对称→加跑'的推理策略才够得到 → 这是 LLM 臂可能赢质量的窄口子。其余 chamfer 族仍"
          "order-independent，C4 死胡同对它们依旧成立（诚实：窄证伪、非全盘推翻）。")
    ok = r["symmetric_overflow"] and r["constraining_side"].startswith("face_B")
    print("\nPASS" if ok else "FAIL", "directional_root 指认约束面")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
