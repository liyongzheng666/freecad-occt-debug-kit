"""机制维真分离线自测（纯 Python，无 FreeCAD）：python -m agent.eval.test_mechanism_score

守住 P1b 机制维的**诚实纪律**：真分只在有 mechanism_truth 的 case 上打（匹配 1.0 / 不匹配 0.0），
其余一律 None（不冒充 0/1）。同 check_valid「reward signal 不能悄悄判错」——错机制必须记 0，
无真值/未声明必须记 None，两者绝不混淆。
"""
from __future__ import annotations

from agent.contracts import CausalHypothesis, Conclusion, GroundTruth, Stage
from agent.eval.scorer import _mechanism, score

S2, S3 = Stage.S2_SURFACE, Stage.S3_SSI


def _gt(sig=None, fc="geometric_curvature"):
    mt = None if sig is None else {"signature": sig, "observable": {}, "basis": "test", "stage_reached": "S2"}
    return GroundTruth(true_chain=[S2], entities=[], expected_evidence="", aligned_fix="",
                       failure_class=fc, mechanism_truth=mt)


def _pred(sig=None, fc="geometric_curvature"):
    return CausalHypothesis(stage=S2, cause="t", chain=[S2], failure_class=fc,
                            mechanism_signature=sig, confidence=0.6)


def main() -> int:
    fails = []

    def check(name, cond):
        print(("PASS " if cond else "FAIL ") + name)
        if not cond:
            fails.append(name)

    # 1) 签名匹配 → 1.0（真分，非代理）
    check("match → 1.0",
          _mechanism(_pred("s2_rolling_ball_infeasible"), _gt("s2_rolling_ball_infeasible")) == 1.0)
    # 2) 签名不匹配 → 0.0（错机制是真 miss，不洗白成 None）
    check("mismatch → 0.0（真 miss，不冒充 None）",
          _mechanism(_pred("s3_degenerate_contact"), _gt("s2_rolling_ball_infeasible")) == 0.0)
    # 3) case 无 mechanism_truth → None（诚实不打分）
    check("无 mechanism_truth → None", _mechanism(_pred("s2_rolling_ball_infeasible"), _gt(None)) is None)
    # 4) pred 未声明机制签名（上游 throw / 弃权 / overflow 无机制观测）→ None
    check("pred 无机制签名 → None（含上游 throw）",
          _mechanism(_pred(None), _gt("s2_rolling_ball_infeasible")) is None)
    # 5) 两个真实签名互斥可判（覆盖 s3 分支）
    check("s3 match → 1.0",
          _mechanism(_pred("s3_degenerate_contact"), _gt("s3_degenerate_contact")) == 1.0)

    # 6) 端到端 score()：有真值 → 机制真分进结果；无真值 → 机制 None
    r_match = score(_concl("s2_rolling_ball_infeasible"), _gt("s2_rolling_ball_infeasible"))
    check("score() 机制真分 1.0（有真值+匹配）", r_match["mechanism"] == 1.0)
    check("score() 机制 basis 标注真分（非深度代理）",
          "真分" in r_match["detail"]["mechanism_basis"] and "代理" not in r_match["detail"]["mechanism_basis"])
    r_notruth = score(_concl("s2_rolling_ball_infeasible"), _gt(None))
    check("score() 无真值 → 机制 None（不计入均值）", r_notruth["mechanism"] is None)

    # 7) 弃权 case：机制必 None（不在弃权上编机制分）
    ab = score(Conclusion(abstained=True, abstain_reason="x"),
               GroundTruth(true_chain=[], entities=[], expected_evidence="", aligned_fix="",
                           expected_abstain=True, mechanism_truth={"signature": "s2_rolling_ball_infeasible"}))
    check("弃权 → 机制 None", ab["mechanism"] is None)

    print("全部通过" if not fails else f"有 {len(fails)} 项失败")
    return 1 if fails else 0


def _concl(sig):
    return Conclusion(hypotheses=[_pred(sig)])


if __name__ == "__main__":
    raise SystemExit(main())
