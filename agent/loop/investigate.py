"""investigate(case) — 编排 observe→定位→反事实→结论（A3 / G1 / G20，规则版 v0）。

三腿验证见 docs/root-cause-verification.md §3。本 v0 用**已落地的真工具**：
  observe   = reproduce（FreeCADCmd 真跑 recompute）
  定位/有效 = check_valid（occ-debug-mesh BRepCheck）
  反事实    = 靶向半径探测（降半径能否恢复成有效实体；判据是 S6 几何有效，**非 IsDone**）
  决策      = query_playbook（fillet-failures.json：症状→候选→判别器，取最 distal 命中者为根）
判别器里 ssi_probe 一腿（S3）经 capture 桥抓失败现场两面跑面面求交（A7 WP1）：有登记现场
+ LLDB/debug-OCCT 前置则真跑得 fired/ruled_out；缺现场或缺前置照实 untestable，不硬猜
（root-cause §5『弃权 / 分级定位』）。

铁律落在代码里：reproduce 的 status="ok" 只表"跑完产形状"，是否成功一律由 check_valid 复判。
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from agent.contracts import (
    CausalHypothesis, Conclusion, Evidence, Stage, ToolResult,
)
from agent.loop.decide_llm import decide_llm
from agent.loop.decide_rule import decide_rule
from agent.tools.check_valid import check_valid
from agent.tools.playbook import query_playbook
from agent.tools.reproduce import reproduce
from agent.tools.triage_input import triage_input

# policy 接缝（A3 rule 下限基线 / A5 LLM）——decide(state)->action，同签名可 A/B 直换
_POLICIES = {"rule": decide_rule, "llm": decide_llm}

_NEAR_TANGENT_EPS_DEG = 10.0

# 反事实半径阶梯（requested 的降序倍数）；停在首个"可行"半径即得可行上界
_CF_FRACTIONS = [0.5, 0.2, 0.1, 0.05, 0.02, 0.005, 0.002]


def _log(verbose, msg):
    if verbose:
        print("  · " + msg)


def _observe(case, r, out_dir, sink, verbose, tolerance=None):
    """reproduce + 记一条 ToolResult。tolerance：WP3 互斥反事实，只动容差不动半径（None=不动）。"""
    run = reproduce(case, radius=r, tolerance=tolerance, out_dir=out_dir)
    tag = f"r={r}" + (f" tol={tolerance}" if tolerance is not None else "")
    sink.append(ToolResult(
        tool="reproduce", ok=(run.status == "ok"),
        summary=f"{tag}: status={run.status} is_done={run.is_done}"
                + (f" exc={run.exception}" if run.exception else ""),
        payload={"radius": r, "tolerance": tolerance, "status": run.status, "phase": run.phase},
        artifact_id=run.bad_shape, source="agent/tools/reproduce.py",
        error=run.exception if run.status != "ok" else None,
    ))
    _log(verbose, f"reproduce {tag} → status={run.status} is_done={run.is_done}"
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


def _is_feasible(case, r, out_dir, sink, verbose, tolerance=None):
    """可行 = reproduce 跑完产形状 且 check_valid 判有效（S6，非 IsDone）。tolerance 见 _observe。"""
    run = _observe(case, r, out_dir, sink, verbose, tolerance=tolerance)
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


# WP3 互斥反事实：只动容差不动半径的升序阶梯（恢复有效实体即"容差敏感"→ S3 数值病态）
_CF_TOLERANCES = [0.001, 0.01, 0.1]


def _probe_tolerance_fix(case, requested, out_dir, sink, verbose):
    """同半径只扰容差（升序阶梯）→ 首个能恢复有效实体(S6)的容差 or None（None=容差修法无效）。"""
    for tol in _CF_TOLERANCES:
        if _is_feasible(case, requested, out_dir, sink, verbose, tolerance=tol):
            return tol
    return None


def _counterfactual_verdict(lower_radius_ok: bool, tol_fix):
    """互斥靶向修法组合 → S2/S3 判别（root-cause-verification.md §4 腿3，纯函数）。

    tol_fix：生效容差 or None。只动这两个互斥修法（降半径 / 扰容差，均不动对方）的成功组合
    把根因对齐到 S2(几何/半径相关) / S3(容差敏感数值病态) / "S2 诱发 S3"。
    """
    tol_ok = tol_fix is not None
    if lower_radius_ok and not tol_ok:
        return "S2", "降半径有效、扰容差(≤0.1)无效 → 失败半径/几何相关(S2)，排除 S3 容差敏感(数值病态)"
    if tol_ok and not lower_radius_ok:
        return "S3", f"仅扰容差(={tol_fix})有效、降半径无效 → S3 数值病态(容差敏感、半径无关)"
    if tol_ok and lower_radius_ok:
        return "S2->S3", f"降半径 + 扰容差(={tol_fix})均有效 → S2 诱发 S3(半径偏大致近切 + 数值病态)"
    return "inconclusive", "降半径与扰容差均无效 → 互斥反事实未区分 S2/S3"


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
    if tool == "ssi_probe":                                # S3：capture 失败现场两面 → 面面求交（A7 WP1）
        return _ssi_discriminate(case, radius, sink, verbose)
    return "untestable", f"未知判别工具 {tool}"


def _ssi_verdict(report) -> tuple[str, str]:
    """SSIReport → S3 候选裁定（纯函数，不依赖 LLDB，可单测）。

    s3_signature → fired(S3 求交退化)；近切但 section 有 contact 边 → ruled_out(实属 S2 StartSol
    滚球塞不进，非 S3)；clean 横切 → ruled_out(归 S2/S5)；探针自身失败(哨兵 n_curves_ss=-1) →
    untestable（不把工具失败误判成 S3 排除）。
    """
    if report.n_curves_ss == -1:                           # ssi_probe/_to_report 的"未测出"哨兵
        return "untestable", f"ssi_probe 未测出：{report.notes}"
    if report.s3_signature:
        return "fired", (f"面面求交退化：期望 contact 实得 section={report.n_section_edges}，"
                         f"两面近切 {report.min_dihedral_deg}° → S3 签名")
    if report.near_tangent and report.n_section_edges > 0:
        return "ruled_out", (f"近切 {report.min_dihedral_deg}° 但 section 有 {report.n_section_edges} 条 "
                             f"contact 边 → 失败属 S2(StartSol 滚球塞不进)非 S3 求交退化")
    return "ruled_out", (f"clean 求交（section={report.n_section_edges}，夹角 {report.min_dihedral_deg}°）"
                         f"→ S3 排除，失败应归 S2/S5")


def _ssi_discriminate(case, radius, sink, verbose):
    """capture 失败现场两面跑 ssi_probe → S3 裁定。无登记现场 / 缺 LLDB 前置 → untestable（不伪绿）。"""
    from agent.tools.capture import (
        capture_spec_for, capture_ssi, make_fail_script, prereqs_ok,
    )
    spec = capture_spec_for(case)
    if spec is None:
        return "untestable", "无已登记 SSI capture 现场（断点+两面表达式），免埋点无法取失败现场两面"
    if not prereqs_ok():
        return "untestable", "缺 LLDB/debug-OCCT capture 前置（CI 环境照实弃权，非 S3 排除）"
    try:
        fail_script = make_fail_script(case, radius)
        report = capture_ssi(fail_script, spec["breakpoint"],
                             spec["face_a_expr"], spec["face_b_expr"],
                             tangent_eps_deg=_NEAR_TANGENT_EPS_DEG)
    except Exception as e:                                 # noqa: BLE001 — capture/lldb 失败不静默判 S3
        return "untestable", f"capture_ssi 失败：{type(e).__name__}: {e}"
    sink.append(ToolResult(
        tool="capture_ssi", ok=True,
        summary=(f"s3_sig={report.s3_signature} near_tangent={report.near_tangent} "
                 f"dihedral={report.min_dihedral_deg}° section={report.n_section_edges}"),
        payload={"s3_signature": report.s3_signature, "near_tangent": report.near_tangent,
                 "min_dihedral_deg": report.min_dihedral_deg,
                 "n_section_edges": report.n_section_edges},
        source="agent/tools/capture.py"))
    status, ev = _ssi_verdict(report)
    _log(verbose, f"  ssi_probe(capture {spec['breakpoint']}) → {status}: {ev}")
    return status, ev


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

    返回 (class_key, class_dict, why, entities) 或 None。entities 是免埋点能诚实定位到的
    实体（canonical token，供 eval entity 召回）：
    geometric_near_tangent: triage 量出的近切边 `edge#<i>` —— 与 LLDB 真值同一处（实体级定位）。
    geometric_curvature   : 凹曲率面，triage 暂未回面 id → []（待 A7 capture 回面）。
    algorithmic_overflow  : 重叠的两 fillet 带是 S2 中间面，免埋点无法命名 → []；其句柄埋在
                            StripeEdgeInter 匿名 DStr（见 cases/box-r5.json truth_run），capture
                            未必救得了 → entity 维可能止于 stage（非待兑现的 ~1.00）。
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

    entities: list[str] = []
    if 0.0 <= t.min_dihedral_deg < _NEAR_TANGENT_EPS_DEG:
        key = "geometric_near_tangent"
        # triage 量出的近切边即失效现场（与 LLDB 真值同一处）→ 实体级定位
        entities = [f"edge#{i}" for (i, _deg) in t.near_tangent_pairs]
        why = (f"支撑面近切（最小二面角 {t.min_dihedral_deg}° < {_NEAR_TANGENT_EPS_DEG}°"
               + (f"，近切边 {', '.join(entities)}" if entities else "") + "）")
    elif t.min_support_curv_radius is not None and radius > t.min_support_curv_radius:
        key = "geometric_curvature"
        # triage 量出的最小凹曲率支撑面即失效现场 → 实体级定位（与近切边对称）
        if t.min_support_curv_face is not None:
            entities = [f"face#{t.min_support_curv_face}"]
        why = (f"r={radius} > 支撑面凹曲率半径 {t.min_support_curv_radius}"
               + (f"（凹曲率面 {', '.join(entities)}）" if entities else ""))
    else:
        key = "algorithmic_overflow"
        why = f"平面/非近切/无曲率约束（最小二面角 {t.min_dihedral_deg}°）"
    info = classes.get(key)
    if info is None:
        return None
    _log(verbose, f"  失效分类：{key} —— {why}")
    return key, info, why, entities


def _diagnose_via_playbook(case, radius, run, out, sink, verbose, policy="rule", traj=None) -> Conclusion:
    """按 symptom 命中 playbook 节点 → policy.decide 选判别器逐个跑 → 确定性合成结论。

    决策（跑哪个候选 / 何时收）走 `decide(state)` 接缝（policy=rule|llm）；结论合成（取最
    distal 命中者为根 + 失效三态细分）是决策之后的确定性后处理。rule 臂 = 顺序穷尽候选，
    与改造前 for-loop 等价（eval 数字不变即回归通过）。
    """
    sig = {"exception": run.exception or "", "phase": run.phase, "is_done": run.is_done}
    node = query_playbook(sig)
    if node is None:
        return Conclusion(abstained=True,
                          abstain_reason=f"无 playbook 节点匹配 symptom（exc={run.exception}, phase={run.phase}）")
    _log(verbose, f"playbook 命中 {node['id']}（近端 {node['proximate_stage']}），policy={policy} 逐候选判别")

    decide = _POLICIES[policy]
    verdicts = []                                          # [(cand, status, ev)]
    state = {"node": node, "verdicts": verdicts, "run_end": run}
    while True:
        action = decide(state)                            # 决策接缝：选下一个候选 or 下结论
        if traj is not None:
            traj.append({"t": "decide", "policy": policy,
                         "action": "conclude" if action.get("conclude") else action["run"]["stage"]})
        if action.get("conclude"):
            break
        cand = action["run"]
        status, ev = _run_discriminator(case, radius, cand, out, sink, verbose)
        verdicts.append((cand, status, ev))
        if traj is not None:
            traj.append({"t": "verdict", "stage": cand["stage"],
                         "tool": cand.get("localize", {}).get("tool"), "status": status, "evidence": ev})
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
    failure_class = None
    entities: list[str] = []
    if cls is not None:
        key, info, why, entities = cls
        failure_class = key
        cause = f"{cand['cause']}。失效类别【{key}】：{info['cause']}（{why}）"
        salv = info.get("salvageable")
        # WP3 第三腿：互斥反事实。radius_probe 已 fired → 降半径有效；再跑 perturb_tolerance
        # （不动半径），两修法成功组合判别 S2 / S3 / S2→S3（root-cause §4 腿3）。
        tol_fix = _probe_tolerance_fix(case, radius, out, sink, verbose)
        cf_label, cf_why = _counterfactual_verdict(True, tol_fix)
        _log(verbose, f"  互斥反事实 [{cf_label}]：{cf_why}")
        counterfactual = (f"修法：{info['fix']}"
                          + ("（几何可救，非降半径）" if salv else "（降半径之外无解）")
                          + f"｜互斥反事实[{cf_label}]：{cf_why}")
        evidence.append(Evidence(
            f"失效分类 {key}（salvageable={salv}）：{why} → 修法 {info['fix']}",
            source="agent/playbook/fillet-failures.json"))
        evidence.append(Evidence(
            f"互斥反事实 [{cf_label}]：{cf_why}",
            source="agent/loop/investigate.py"))
        if entities:
            evidence.append(Evidence(
                f"实体级定位：失效现场 {', '.join(entities)}（triage 近切边/凹曲率面，免埋点可命名）",
                source="agent/tools/triage_input.py"))
        conf = 0.7
    else:
        cf = cand.get("counterfactual", {})
        cf_tail = (f"；互斥于 {cf['discriminates_from']}" if cf.get("discriminates_from")
                   else (f"；保持 {cf['must_not_change']} 不变" if cf.get("must_not_change") else ""))
        cause = cand["cause"]
        counterfactual = f"{cf.get('fix', '?')}（{ev}）{cf_tail}"
        conf = 0.6

    # 命名到具体实体 → 定位深度记 entity；否则止于 stage（如 box overflow：句柄埋匿名 DStr，
    # capture 未必救得了，可能永久止于 stage——非待兑现的 ~1.00，见 README WP4②）
    depth = "entity" if entities else "stage"
    return Conclusion(hypotheses=[CausalHypothesis(
        stage=root, chain=chain, cause=cause,
        entities=entities,
        localization_depth=depth, confidence=conf,
        counterfactual=counterfactual,
        evidence=evidence,
        failure_class=failure_class,
    )])


def investigate(
    case_id: str,
    *,
    radius: float | None = None,
    policy: str = "rule",
    out_dir: str | None = None,
    session_dir: str | None = None,
    trace: list[ToolResult] | None = None,
    trajectory: list | None = None,
    verbose: bool = False,
) -> Conclusion:
    """policy: "rule"(A3 规则版下限基线) | "llm"(A5)。返回分级因果结论。

    决策走 `decide(state)` 接缝（loop/decide_rule|decide_llm，同签名可 A/B）；observe / 判别器
    执行 / 结论合成一律确定性。trace：调用方传入的列表则把每次工具调用的 ToolResult 追加进去
    （eval runner 据此数 tool-call 成本，G11）。trajectory：传入则收集有序轨迹步（observe / decide
    /verdict / conclude，A6/G9），可经 `agent.trajectory.TrajectoryWriter` 落盘 → 离线重放重打分。
    """
    if policy not in _POLICIES:
        raise ValueError(f"未知 policy={policy}（可选 {list(_POLICIES)}）")
    if radius is None:
        raise ValueError("decide policy 需要 radius")

    out = out_dir or tempfile.mkdtemp(prefix="investigate_")
    sink: list[ToolResult] = trace if trace is not None else []
    conclusion = _investigate_loop(case_id, float(radius), out, sink, verbose, policy, trajectory)

    if trajectory is not None:                            # 末步：结论（供离线重放重打分）
        from agent.trajectory import conclusion_to_dict
        trajectory.append({"t": "conclude", "conclusion": conclusion_to_dict(conclusion)})
    if session_dir:
        from agent.session import SessionWriter
        w = SessionWriter(session_dir, run_id="agent")
        for tr in sink:
            w.emit_tool_result(tr)
        w.emit_conclusion(conclusion)
    return conclusion


def _investigate_loop(case, radius, out, sink, verbose, policy="rule", traj=None) -> Conclusion:
    _log(verbose, f"observe: reproduce {case} @ r={radius}")
    run = _observe(case, radius, out, sink, verbose)
    if traj is not None:
        traj.append({"t": "observe", "case": case, "radius": radius, "policy": policy,
                     "run_end": {"status": run.status, "exception": run.exception,
                                 "phase": run.phase, "is_done": run.is_done}})

    # —— 分支 A：算法没跑完（典型 StdFail_NotDone）→ policy.decide 驱动逐候选判别 ——
    if run.status != "ok" and run.phase == "fillet_notdone":
        return _diagnose_via_playbook(case, radius, run, out, sink, verbose, policy, traj)

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
