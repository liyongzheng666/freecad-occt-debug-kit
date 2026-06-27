"""investigate(case) — 编排 observe→定位→反事实→结论（A3 / G1 / G20，规则版 v0）。

三腿验证见 docs/root-cause-verification.md §3。本 v0 只用**已落地的真工具**：
  observe   = reproduce（FreeCADCmd 真跑 recompute）
  定位/有效 = check_valid（occ-debug-mesh BRepCheck）
  反事实    = 靶向半径探测（降半径能否恢复成有效实体；判据是 S6 几何有效，**非 IsDone**）
还没接的（playbook 决策表 / SSI surfdata 深探针）留作 A7/A8——本 v0 **诚实定位到能站住
的那一层并标出未解的更深机制**，不硬猜（root-cause §5『弃权 / 分级定位』）。

铁律落在代码里：reproduce 的 status="ok" 只表"跑完产形状"，是否成功一律由 check_valid 复判。
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from agent.contracts import (
    CausalHypothesis, Conclusion, Evidence, Stage, ToolResult,
)
from agent.tools.check_valid import check_valid
from agent.tools.reproduce import reproduce

# 反事实半径阶梯（requested 的降序倍数）；停在首个"可行"半径即得可行上界
_CF_FRACTIONS = [0.5, 0.2, 0.1, 0.05, 0.02, 0.005, 0.002]


def _log(verbose, msg):
    if verbose:
        print("  · " + msg)


def _observe(case, r, out_dir, sink, verbose):
    """reproduce + 记一条 ToolResult。"""
    run = reproduce(case, radius=r, out_dir=out_dir)
    sink.append(ToolResult(
        tool="reproduce", ok=(run.status == "ok"),
        summary=f"r={r}: status={run.status} is_done={run.is_done}"
                + (f" exc={run.exception}" if run.exception else ""),
        payload={"radius": r, "status": run.status, "phase": run.phase},
        artifact_id=run.bad_shape, source="agent/tools/reproduce.py",
        error=run.exception if run.status != "ok" else None,
    ))
    _log(verbose, f"reproduce r={r} → status={run.status} is_done={run.is_done}"
                  + (f" [{run.exception}]" if run.exception else ""))
    return run


def _validate(brep, sink, verbose):
    v = check_valid(brep)
    sink.append(ToolResult(
        tool="check_valid", ok=True, summary=f"valid={v.valid} ({v.notes.split(' | ')[-1][:48]})",
        payload={"valid": v.valid, "n_errors": len(v.invalid_subshapes),
                 "n_self_intersection": len(v.self_intersections)},
        artifact_id=brep, source="agent/tools/check_valid.py",
    ))
    _log(verbose, f"check_valid({Path(brep).name}) → valid={v.valid}"
                  f" errors={len(v.invalid_subshapes)} selfX={len(v.self_intersections)}")
    return v


def _is_feasible(case, r, out_dir, sink, verbose):
    """可行 = reproduce 跑完产形状 且 check_valid 判有效（S6，非 IsDone）。"""
    run = _observe(case, r, out_dir, sink, verbose)
    if run.status != "ok" or not run.is_done or not run.bad_shape:
        return False
    return _validate(run.bad_shape, sink, verbose).valid


def _probe_feasible_bound(case, requested, out_dir, sink, verbose):
    """降序探阶梯，返回 (首个可行半径 or None, 其上方最小不可行半径)。"""
    prev_infeasible = requested  # requested 已知不可行
    for f in _CF_FRACTIONS:
        r = round(requested * f, 4)
        if _is_feasible(case, r, out_dir, sink, verbose):
            return r, prev_infeasible
        prev_infeasible = r
    return None, prev_infeasible


def investigate(
    case_id: str,
    *,
    radius: float | None = None,
    policy: str = "rule",
    out_dir: str | None = None,
    session_dir: str | None = None,
    verbose: bool = False,
) -> Conclusion:
    """policy: "rule"(A3 规则版) | "llm"(A5，未实现)。返回分级因果结论。"""
    if policy != "rule":
        raise NotImplementedError(f"policy={policy} 未实现（LLM 版见 A5）")
    if radius is None:
        raise ValueError("rule policy 需要 radius")

    out = out_dir or tempfile.mkdtemp(prefix="investigate_")
    sink: list[ToolResult] = []
    conclusion = _rule_investigate(case_id, float(radius), out, sink, verbose)

    if session_dir:
        from agent.session import SessionWriter
        w = SessionWriter(session_dir, run_id="agent")
        for tr in sink:
            w.emit_tool_result(tr)
        w.emit_conclusion(conclusion)
    return conclusion


def _rule_investigate(case, radius, out, sink, verbose) -> Conclusion:
    _log(verbose, f"observe: reproduce {case} @ r={radius}")
    run = _observe(case, radius, out, sink, verbose)

    # —— 分支 A：算法没跑完（典型 StdFail_NotDone）——
    if run.status != "ok" and run.phase == "fillet_notdone":
        _log(verbose, "定位: 排除 S0（查输入几何有效性）")
        base = reproduce(case, radius=0.0, out_dir=out)             # 导出基础几何
        input_valid = bool(base.bad_shape) and _validate(base.bad_shape, sink, verbose).valid

        _log(verbose, "反事实: 降半径探可行上界")
        feas_r, infeas_floor = _probe_feasible_bound(case, radius, out, sink, verbose)

        if feas_r is not None and input_valid:
            hyp = CausalHypothesis(
                stage=Stage.S2_SURFACE,
                chain=[Stage.S2_SURFACE],
                cause=(f"圆角半径 {radius} 相对几何过大：ChFi3d 无法完成（StdFail_NotDone）。"
                       f"可行半径上界 ∈ [{feas_r}, {infeas_floor})——半径 ≤ ~{feas_r} 能生成"
                       f"有效实体，≥ ~{infeas_floor} 即失败。输入几何本身有效，S0 已排除。"),
                entities=[],
                localization_depth="stage",
                evidence=[
                    Evidence(f"reproduce: StdFail_NotDone @ r={radius}（{run.phase}）",
                             artifact_id=None, source="agent/tools/reproduce.py"),
                    Evidence("输入几何 check_valid 通过 → S0 输入质量排除",
                             source="agent/tools/check_valid.py"),
                    Evidence(f"反事实半径探测：可行上界 ∈ [{feas_r}, {infeas_floor})",
                             source="agent/loop/investigate.py"),
                    Evidence("⚠ 最深子阶段未细分：r≫可行上界，最可能 S2 滚球容纳不下；"
                             "若仅临界 overflow，失败可能后移到 S3 面面求交 / S5 缝合"
                             "（『半径过大→无法缝合』是此候选）。区分需 surfdata/SSI 探针（A7/A8）。"),
                ],
                counterfactual=(f"互斥判别：降半径(→{feas_r}) 重跑→有效实体 ✅；输入未改仍失败 → "
                                f"因落在【半径 × 几何容纳】，非输入质量(S0)。"),
                confidence=0.6,
            )
            return Conclusion(hypotheses=[hyp])

        if not input_valid:
            hyp = CausalHypothesis(
                stage=Stage.S0_INPUT, chain=[Stage.S0_INPUT],
                cause="输入几何 check_valid 即判无效 → 失败根在 S0 输入质量，先 heal 输入。",
                localization_depth="stage", confidence=0.55,
                evidence=[Evidence("base shape check_valid 不通过", source="agent/tools/check_valid.py")],
            )
            return Conclusion(hypotheses=[hyp])

        # 输入有效但任何更小半径也复现不出可行 → 站不住，弃权交人
        return Conclusion(
            abstained=True,
            abstain_reason=f"r={radius} 失败但降半径阶梯内未找到可行半径，仅靠 reproduce+check_valid "
                           f"无法定位（需 SSI/surfdata 深探针）。",
        )

    # —— 分支 B：跑完产出形状 → 复判有效性 ——
    if run.status == "ok" and run.bad_shape:
        v = _validate(run.bad_shape, sink, verbose)
        if v.valid:
            return Conclusion(
                abstained=True,
                abstain_reason=f"r={radius} 未复现失败：reproduce 跑完且 check_valid 判有效，无缺陷可归因。",
            )
        # 假绿：IsDone=true 但几何无效
        cats = sorted({d.get("category", "?") for d in v.invalid_subshapes})
        self_x = len(v.self_intersections)
        stage = Stage.S3_SSI if self_x else Stage.S6_VALID
        hyp = CausalHypothesis(
            stage=stage, chain=[stage],
            cause=(f"代理奖励陷阱：fillet『完成』(is_done=True) 但 check_valid 判无效——"
                   f"缺陷类别 {cats}，自交 {self_x} 处。裸 IsDone 会把它误判为成功。"),
            entities=[d.get("ref", {}).get("face_id") or d.get("ref", {}).get("edge_id")
                      for d in v.invalid_subshapes if d.get("ref")],
            localization_depth="entity" if self_x else "stage",
            evidence=[Evidence(f"check_valid: invalid（{cats}, selfX={self_x}）",
                               artifact_id=run.bad_shape, source="agent/tools/check_valid.py")],
            confidence=0.65,
        )
        return Conclusion(hypotheses=[hyp])

    # —— 分支 C：基础设施/harness 级失败 ——
    return Conclusion(
        abstained=True,
        abstain_reason=f"reproduce 非算法失败（{run.phase}）：{run.exception}",
    )


# ---- 结论渲染（人读，给 review）-------------------------------------------------

def format_conclusion(c: Conclusion, case: str, radius: float) -> str:
    L = [f"═══ 根因结论  [case={case}  r={radius}] ═══"]
    if c.abstained:
        L.append(f"判定：弃权 / 无根因")
        L.append(f"原因：{c.abstain_reason}")
        return "\n".join(L)
    for i, h in enumerate(c.hypotheses, 1):
        L.append(f"假设#{i}  置信={h.confidence:.2f}  定位深度={h.localization_depth}")
        L.append(f"  阶段链：{' → '.join(s.value for s in h.chain)}（根={h.stage.value}）")
        L.append(f"  根因：{h.cause}")
        if h.entities:
            L.append(f"  涉及实体：{[e for e in h.entities if e]}")
        if h.counterfactual:
            L.append(f"  反事实：{h.counterfactual}")
        if h.evidence:
            L.append("  证据：")
            for e in h.evidence:
                src = f"  [{e.source}]" if e.source else ""
                L.append(f"    - {e.summary}{src}")
    return "\n".join(L)


if __name__ == "__main__":
    import sys
    case = sys.argv[1] if len(sys.argv) > 1 else "box"
    radius = float(sys.argv[2]) if len(sys.argv) > 2 else 1000.0
    print(f"[investigate] case={case} radius={radius} —— 真跑 FreeCADCmd + occ-debug-mesh\n")
    c = investigate(case, radius=radius, policy="rule", verbose=True)
    print()
    print(format_conclusion(c, case, radius))
