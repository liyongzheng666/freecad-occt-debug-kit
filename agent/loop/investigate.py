"""investigate(case) — 编排 observe→定位→反事实→结论（A3 / G1 / G20，规则版 v0）。

三腿验证见 docs/root-cause-verification.md §3。本 v0 用**已落地的真工具**：
  observe   = reproduce（FreeCADCmd 真跑 recompute）
  定位/有效 = check_valid（occ-debug-mesh BRepCheck）
  反事实    = 靶向半径探测（降半径能否恢复成有效实体；判据是 S6 几何有效，**非 IsDone**）
  决策      = query_playbook（fillet-failures.json：症状→候选→判别器，取最 distal 命中者为根）
判别器里 ssi_probe 一腿需 capture 失败现场两面（A7 capture 接缝未接）→ 标 untestable，
不硬猜（root-cause §5『弃权 / 分级定位』）。

铁律落在代码里：reproduce 的 status="ok" 只表"跑完产形状"，是否成功一律由 check_valid 复判。
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from agent.contracts import (
    CausalHypothesis, Conclusion, Evidence, Stage, ToolResult,
)
from agent.tools.check_valid import check_valid
from agent.tools.playbook import query_playbook
from agent.tools.reproduce import reproduce
from agent.tools.triage_input import triage_input

_NEAR_TANGENT_EPS_DEG = 10.0

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


# ---- 决策表驱动定位（playbook：症状 → 候选 → 判别器）--------------------------

def _run_discriminator(case, radius, cand, out, sink, verbose):
    """跑一个候选的 localize 判别器，返回 (status, evidence_str)。

    status ∈ {"fired"(命中该阶段) | "ruled_out"(排除) | "untestable"(此处无法运行)}。
    """
    tool = cand.get("localize", {}).get("tool")
    if tool == "check_valid_input":                        # S0：输入几何是否本就无效
        base = reproduce(case, radius=0.0, out_dir=out)
        if not base.bad_shape:
            return "untestable", "无法导出输入几何"
        valid = _validate(base.bad_shape, sink, verbose).valid
        return ("ruled_out", "输入 check_valid 通过") if valid else ("fired", "输入 check_valid 不通过")
    if tool == "radius_probe":                             # S2：降半径能否恢复有效实体
        feas_r, infeas_floor = _probe_feasible_bound(case, radius, out, sink, verbose)
        if feas_r is not None:
            return "fired", f"降半径恢复有效实体，可行上界 ∈ [{feas_r}, {infeas_floor})"
        return "ruled_out", "降半径阶梯内无可行半径"
    if tool == "ssi_probe":                                # S3：需失败现场两面（capture 未接）
        return "untestable", "需 capture 失败现场两面（occdbg/LLDB，A7 capture 接缝未接）"
    return "untestable", f"未知判别工具 {tool}"


def _verdicts_to_evidence(node, run, radius, verdicts):
    mark = {"fired": "✓命中", "ruled_out": "✗排除", "untestable": "…未测"}
    evs = [
        Evidence(f"playbook 命中 {node['id']}：近端阶段 {node['proximate_stage']}",
                 source="agent/playbook/fillet-failures.json"),
        Evidence(f"reproduce: {run.exception} @ r={radius}", source="agent/tools/reproduce.py"),
    ]
    for cand, status, ev in verdicts:
        evs.append(Evidence(
            f"候选 {cand['stage']}（{cand.get('localize', {}).get('tool')}）{mark[status]}：{ev}",
            source="agent/loop/investigate.py"))
    return evs


def _classify_s2_failure(case, radius, node, sink, verbose):
    """S2(radius_probe 命中)失败的细分：triage_input → 三态之一。

    返回 (class_key, class_dict, why) 或 None。
    geometric_near_tangent: 支撑面近切(min_dihedral 小) → 降半径/heal。
    geometric_curvature   : r > 支撑面凹曲率半径 → 降半径/改输入。
    algorithmic_overflow  : 否则(平面非近切) → 两圆角重叠，可 SSI 互裁(几何可救)。
    """
    classes = node.get("failure_classes")
    if not classes:
        return None
    try:
        t = triage_input(case)
    except Exception as e:  # noqa: BLE001 — triage 不可用则不细分
        _log(verbose, f"  triage 跳过（{type(e).__name__}），不细分失效类别")
        return None
    sink.append(ToolResult(
        tool="triage_input", ok=True,
        summary=f"min_dihedral={t.min_dihedral_deg}deg min_curv={t.min_support_curv_radius}",
        payload={"min_dihedral_deg": t.min_dihedral_deg, "min_support_curv_radius": t.min_support_curv_radius},
        source="agent/tools/triage_input.py"))

    if 0.0 <= t.min_dihedral_deg < _NEAR_TANGENT_EPS_DEG:
        key = "geometric_near_tangent"
        why = f"支撑面近切（最小二面角 {t.min_dihedral_deg}° < {_NEAR_TANGENT_EPS_DEG}°）"
    elif t.min_support_curv_radius is not None and radius > t.min_support_curv_radius:
        key = "geometric_curvature"
        why = f"r={radius} > 支撑面凹曲率半径 {t.min_support_curv_radius}"
    else:
        key = "algorithmic_overflow"
        why = f"平面/非近切/无曲率约束（最小二面角 {t.min_dihedral_deg}°）"
    info = classes.get(key)
    if info is None:
        return None
    _log(verbose, f"  失效分类：{key} —— {why}")
    return key, info, why


def _diagnose_via_playbook(case, radius, run, out, sink, verbose) -> Conclusion:
    """按 symptom 命中 playbook 节点，逐候选跑判别器，取最 distal 命中者为根。"""
    sig = {"exception": run.exception or "", "phase": run.phase, "is_done": run.is_done}
    node = query_playbook(sig)
    if node is None:
        return Conclusion(abstained=True,
                          abstain_reason=f"无 playbook 节点匹配 symptom（exc={run.exception}, phase={run.phase}）")
    _log(verbose, f"playbook 命中 {node['id']}（近端 {node['proximate_stage']}），逐候选判别")

    verdicts = []                                          # [(cand, status, ev)]
    for cand in node["root_cause_candidates"]:
        status, ev = _run_discriminator(case, radius, cand, out, sink, verbose)
        verdicts.append((cand, status, ev))
        _log(verbose, f"  候选 {cand['stage']} [{cand.get('localize', {}).get('tool')}] → {status}: {ev}")

    fired = [(c, ev) for (c, st, ev) in verdicts if st == "fired"]
    if not fired:
        summ = "；".join(f"{c['stage']}={st}" for c, st, _ in verdicts)
        return Conclusion(abstained=True,
                          abstain_reason=f"playbook {node['id']} 候选判别均未命中（{summ}），证据不足，交人兜底。")

    cand, ev = fired[0]                                    # 候选按 distal→proximate 排，取最 distal 命中者为根
    root = Stage(cand["stage"])
    prox = Stage(node["proximate_stage"])
    chain = [root] if root == prox else [root, prox]
    evidence = _verdicts_to_evidence(node, run, radius, verdicts)

    # S2 命中 → 进一步细分失效类别（geometric 降半径 / algorithmic 可 SSI 互裁）
    cls = _classify_s2_failure(case, radius, node, sink, verbose) if cand["stage"] == "S2" else None
    if cls is not None:
        key, info, why = cls
        cause = f"{cand['cause']}。失效类别【{key}】：{info['cause']}（{why}）"
        salv = info.get("salvageable")
        counterfactual = (f"修法：{info['fix']}"
                          + ("（几何可救，非降半径）" if salv else "（降半径之外无解）"))
        evidence.append(Evidence(
            f"失效分类 {key}（salvageable={salv}）：{why} → 修法 {info['fix']}",
            source="agent/playbook/fillet-failures.json"))
        conf = 0.7
    else:
        cf = cand.get("counterfactual", {})
        cf_tail = (f"；互斥于 {cf['discriminates_from']}" if cf.get("discriminates_from")
                   else (f"；保持 {cf['must_not_change']} 不变" if cf.get("must_not_change") else ""))
        cause = cand["cause"]
        counterfactual = f"{cf.get('fix', '?')}（{ev}）{cf_tail}"
        conf = 0.6

    return Conclusion(hypotheses=[CausalHypothesis(
        stage=root, chain=chain, cause=cause,
        localization_depth="stage", confidence=conf,
        counterfactual=counterfactual,
        evidence=evidence,
    )])


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

    # —— 分支 A：算法没跑完（典型 StdFail_NotDone）→ 决策表驱动逐候选判别 ——
    if run.status != "ok" and run.phase == "fillet_notdone":
        return _diagnose_via_playbook(case, radius, run, out, sink, verbose)

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
