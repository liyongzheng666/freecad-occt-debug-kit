"""review → 标注闭环（A6 / G10，离线数据模型 + 一致率）。

把一次**人工 review（O(1) 定性）**接成**eval（O(N) 定量）**的两件产物：
  1. **GT 标注**：人工裁定落成 `GroundTruth` → 可直接喂 scorer，或沉淀成 case 喂 A1 数据集。
  2. **人-agent 一致率**：confirm/correct/reject 跨多条 review 汇总 → 进 A4 指标。

这就是 README §6 A6 的"review 不替代 eval，它是打标流水线"：一套底座同时喂 review 与 eval。
viewer 按钮接线（confirm/纠正/标根阶段 → 写回 session）留作后续；本模块是其离线数据核。
"""
from __future__ import annotations

import json
from pathlib import Path

from agent.contracts import (
    CausalHypothesis,
    Conclusion,
    GroundTruth,
    Review,
    ReviewOutcome,
    Stage,
)


def _agent_root(c: Conclusion):
    return c.hypotheses[0].stage if (not c.abstained and c.hypotheses) else None


def _agent_failure_class(c: Conclusion):
    return c.hypotheses[0].failure_class if (not c.abstained and c.hypotheses) else None


def _agent_entities(c: Conclusion) -> list[str]:
    return list(c.hypotheses[0].entities) if (not c.abstained and c.hypotheses) else []


def apply_review(conclusion: Conclusion, review: Review) -> ReviewOutcome:
    """一条结论 + 人工裁定 → 一致率（per-dim + overall）+ GT 标注。

    confirm：全维同意，标注＝agent 自己的结论（含"正确弃权"→ expected_abstain）。
    correct：纠正维 = (corrected != agent)；未给的维不纠（视为同意）。标注用纠正值兜回 agent 值。
    reject ：agent 在无缺陷输入上幻觉根因 → root 不一致、标注 expected_abstain=True（空 true_chain）。
    """
    a_root = _agent_root(conclusion)
    a_fc = _agent_failure_class(conclusion)
    a_ents = _agent_entities(conclusion)

    if review.verdict == "confirm":
        root_ok, fc_ok = True, (None if a_fc is None else True)
        annotation = GroundTruth(
            true_chain=[a_root] if a_root else [],
            entities=a_ents, expected_evidence="", aligned_fix="",
            failure_class=a_fc, expected_abstain=conclusion.abstained,
        )

    elif review.verdict == "correct":
        true_root = review.corrected_root or a_root            # 不给＝根不纠
        true_fc = review.corrected_failure_class if review.corrected_failure_class is not None else a_fc
        true_ents = review.corrected_entities or a_ents
        root_ok = (true_root == a_root)
        fc_ok = None if (a_fc is None and true_fc is None) else (true_fc == a_fc)
        annotation = GroundTruth(
            true_chain=[true_root] if true_root else [],
            entities=true_ents, expected_evidence="", aligned_fix="",
            failure_class=true_fc, expected_abstain=False,
        )

    elif review.verdict == "reject":                            # 应弃权：agent 过度承诺/幻觉
        root_ok, fc_ok = False, (None if a_fc is None else False)
        annotation = GroundTruth(
            true_chain=[], entities=[], expected_evidence="", aligned_fix="",
            failure_class=None, expected_abstain=True,
        )
    else:
        raise ValueError(f"未知 verdict={review.verdict}（confirm|correct|reject）")

    dims = [root_ok] + ([fc_ok] if fc_ok is not None else [])
    overall = all(dims) if dims else True
    return ReviewOutcome(
        verdict=review.verdict,
        agreement={"root": root_ok, "failure_class": fc_ok, "overall": overall},
        annotation=annotation,
    )


def _conclusion_from_run_end(summary: dict) -> Conclusion:
    """从 run_end 事件的 summary 重建打分所需的 Conclusion。

    apply_review 只读 top 假设的 stage / failure_class / entities + 是否弃权（见上方
    _agent_* 三函数），evidence 的 artifact 锚点与裁定无关，不重建。
    """
    hyps = [
        CausalHypothesis(
            stage=Stage(h["stage"]),
            cause=h.get("cause", ""),
            chain=[Stage(s) for s in h.get("chain", [])],
            entities=list(h.get("entities", [])),
            localization_depth=h.get("localization_depth", "stage"),
            counterfactual=h.get("counterfactual"),
            confidence=h.get("confidence", 0.0),
            failure_class=h.get("failure_class"),
        )
        for h in summary.get("hypotheses", [])
    ]
    return Conclusion(
        hypotheses=hyps,
        abstained=summary.get("abstained", False),
        abstain_reason=summary.get("abstain_reason", ""),
    )


def _review_from_event(ev: dict) -> Review:
    """`review` 事件 dict → Review 契约（corrected_root 字符串 → Stage）。"""
    cr = ev.get("corrected_root")
    return Review(
        reviewer=ev.get("reviewer", ""),
        verdict=ev["verdict"],
        target=f"{ev.get('target_run_id', '')}#{ev.get('target_seq', '')}",
        corrected_root=Stage(cr) if cr else None,
        corrected_failure_class=ev.get("corrected_failure_class"),
        corrected_entities=list(ev.get("corrected_entities", [])),
        note=ev.get("note", ""),
    )


def ingest_session_reviews(session_dir: str | Path) -> list[ReviewOutcome]:
    """读一个 session 的 events.ndjson，把每条 `review` 事件配对其 run_end 结论 →
    `apply_review` → ReviewOutcome 列表（喂 scorer / agreement_rate）。

    这是 A6 闭环的 **agent 侧消费端**（红线：Bridge 只追加协议事件、不算一致率；
    全部 agreement/标注计算留在这里离线做）。配对键：review 的 target_run_id+target_seq
    ↔ run_end 的 run_id+seq；悬空 review（无对应结论）跳过。与 live apply_review 同函数同结果。
    """
    events_path = Path(session_dir) / "events.ndjson"
    if not events_path.exists():
        return []
    run_ends: dict[tuple, dict] = {}
    review_events: list[dict] = []
    for line in events_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        ev = json.loads(line)
        op = ev.get("op")
        if op == "run_end":
            run_ends[(ev.get("run_id"), ev.get("seq"))] = ev
        elif op == "review":
            review_events.append(ev)

    outcomes: list[ReviewOutcome] = []
    for rev in review_events:
        target = run_ends.get((rev.get("target_run_id"), rev.get("target_seq")))
        if target is None:
            continue  # 悬空 review：无对应 run_end 结论
        conclusion = _conclusion_from_run_end(target.get("summary", {}))
        outcomes.append(apply_review(conclusion, _review_from_event(rev)))
    return outcomes


def agreement_rate(outcomes: list[ReviewOutcome]) -> dict:
    """跨多条 review 汇总 人-agent 一致率（集合量，喂 A4）。

    overall_rate = overall 同意数 / 总数；另报 verdict 分布（confirm/correct/reject）。
    """
    if not outcomes:
        return {"n": 0, "overall_rate": None, "root_rate": None, "verdicts": {}}
    n = len(outcomes)
    overall = sum(1 for o in outcomes if o.agreement["overall"]) / n
    root = sum(1 for o in outcomes if o.agreement["root"]) / n
    verdicts: dict[str, int] = {}
    for o in outcomes:
        verdicts[o.verdict] = verdicts.get(o.verdict, 0) + 1
    return {"n": n, "overall_rate": round(overall, 3), "root_rate": round(root, 3),
            "verdicts": verdicts}
