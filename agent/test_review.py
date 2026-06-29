"""review→标注 + 一致率自测（A6/G10，无 OCCT）：python -m agent.test_review

验证 apply_review 把人工裁定接成 (一致率 + GT 标注)：confirm/correct/reject 三态语义、
per-dim 一致、标注可直接喂 scorer，以及跨多条 review 的 agreement_rate 汇总。
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from agent.contracts import CausalHypothesis, Conclusion, Review, Stage
from agent.review import agreement_rate, apply_review, ingest_session_reviews
from agent.session import SessionWriter

S2, S3 = Stage.S2_SURFACE, Stage.S3_SSI


def _concl(stage=S2, fc="geometric_near_tangent", entities=("edge#0",)):
    return Conclusion(hypotheses=[CausalHypothesis(
        stage=stage, cause="t", chain=[stage], entities=list(entities), failure_class=fc, confidence=0.7)])


def main() -> int:
    fails = []

    def check(name, cond):
        print(("PASS " if cond else "FAIL ") + name)
        if not cond:
            fails.append(name)

    c = _concl()  # agent: 根 S2 / geometric_near_tangent / edge#0

    # 1) confirm：全维同意，标注＝agent 自己的结论
    o = apply_review(c, Review(reviewer="me", verdict="confirm"))
    check("confirm → overall agree", o.agreement["overall"] is True)
    check("confirm → root agree", o.agreement["root"] is True)
    check("confirm → annotation true_chain=[S2]", o.annotation.true_chain == [S2])
    check("confirm → annotation failure_class", o.annotation.failure_class == "geometric_near_tangent")

    # 2) correct 根错：root 不一致，标注用纠正根
    o = apply_review(c, Review(reviewer="me", verdict="correct", corrected_root=S3))
    check("correct root → root disagree", o.agreement["root"] is False)
    check("correct root → overall disagree", o.agreement["overall"] is False)
    check("correct root → annotation root=S3", o.annotation.true_chain == [S3])

    # 3) correct 仅失效类错：root 仍一致、failure_class 不一致
    o = apply_review(c, Review(reviewer="me", verdict="correct", corrected_failure_class="geometric_curvature"))
    check("correct fc only → root agree", o.agreement["root"] is True)
    check("correct fc only → fc disagree", o.agreement["failure_class"] is False)
    check("correct fc only → overall disagree", o.agreement["overall"] is False)
    check("correct fc only → annotation fc", o.annotation.failure_class == "geometric_curvature")

    # 4) reject：agent 幻觉根因 → root 不一致、标注应弃权
    o = apply_review(c, Review(reviewer="me", verdict="reject"))
    check("reject → root disagree", o.agreement["root"] is False)
    check("reject → annotation expected_abstain", o.annotation.expected_abstain is True)
    check("reject → annotation empty chain", o.annotation.true_chain == [])

    # 5) 弃权结论被 confirm（正确弃权）：标注 expected_abstain
    ab = Conclusion(abstained=True, abstain_reason="无缺陷")
    o = apply_review(ab, Review(reviewer="me", verdict="confirm"))
    check("confirm abstain → expected_abstain annotation", o.annotation.expected_abstain is True)
    check("confirm abstain → overall agree", o.agreement["overall"] is True)

    # 6) agreement_rate 汇总
    outs = [
        apply_review(c, Review(reviewer="a", verdict="confirm")),
        apply_review(c, Review(reviewer="a", verdict="confirm")),
        apply_review(c, Review(reviewer="a", verdict="correct", corrected_root=S3)),
        apply_review(c, Review(reviewer="a", verdict="reject")),
    ]
    r = agreement_rate(outs)
    check("agreement_rate n=4", r["n"] == 4)
    check("agreement_rate overall=0.5", r["overall_rate"] == 0.5)            # 2/4 confirm 同意
    check("agreement_rate verdicts", r["verdicts"] == {"confirm": 2, "correct": 1, "reject": 1})
    check("agreement_rate empty → None", agreement_rate([])["overall_rate"] is None)

    # 7) 写回 session → 离线 ingest 重打分（A6 闭环 agent 侧）：emit_conclusion + emit_review
    #    → ingest_session_reviews 配对 run_end → apply_review，与 live apply_review 同 outcome。
    with tempfile.TemporaryDirectory() as d:
        w = SessionWriter(d, run_id="agent")
        run_end = w.emit_conclusion(c)                       # 被裁定的结论事件
        rid, rseq = run_end["run_id"], run_end["seq"]
        # 一条 confirm、一条 correct(根 S3) —— 都锚到上面的 run_end
        w.emit_review(Review(reviewer="u", verdict="confirm"),
                      target_run_id=rid, target_seq=rseq)
        w.emit_review(Review(reviewer="u", verdict="correct", corrected_root=S3,
                             corrected_entities=["edge#7"]),
                      target_run_id=rid, target_seq=rseq)
        # 一条悬空 review（无对应 run_end）→ 应被跳过
        w.emit_review(Review(reviewer="u", verdict="reject"),
                      target_run_id="ghost", target_seq=999)

        outs = ingest_session_reviews(d)
        check("ingest → 2 outcomes（悬空被跳过）", len(outs) == 2)
        # 与 live apply_review 逐位一致
        live_confirm = apply_review(c, Review(reviewer="u", verdict="confirm"))
        live_correct = apply_review(c, Review(reviewer="u", verdict="correct",
                                              corrected_root=S3, corrected_entities=["edge#7"]))
        check("ingest confirm == live", outs[0].agreement == live_confirm.agreement
              and outs[0].annotation.true_chain == live_confirm.annotation.true_chain)
        check("ingest correct root == live S3", outs[1].agreement == live_correct.agreement
              and outs[1].annotation.true_chain == [S3])
        check("ingest correct entities written back", outs[1].annotation.entities == ["edge#7"])
        # review 事件确实落进 events.ndjson 且 op=review
        text = (Path(d) / "events.ndjson").read_text(encoding="utf-8")
        check("events.ndjson 含 op=review 行", '"op": "review"' in text)

    print(f"\n{'ALL PASS' if not fails else str(len(fails)) + ' FAILED'}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
