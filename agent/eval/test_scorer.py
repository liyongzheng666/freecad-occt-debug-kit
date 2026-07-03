"""scorer 离线自测（无 pytest 依赖）：python -m agent.eval.test_scorer

验证因果链部分得分（缺口1）：命中根 > 含根 > 只命中症状 > miss，叠实体召回，
以及弃权路径。check_valid「必须配自己的测试集」的同款纪律——reward signal 不能
悄悄判错。
"""
from __future__ import annotations

from agent.contracts import CausalHypothesis, Conclusion, GroundTruth, Stage
from agent.eval.scorer import score

S0, S2, S3, S5 = Stage.S0_INPUT, Stage.S2_SURFACE, Stage.S3_SSI, Stage.S5_SEW


def _gt(failure_class=None) -> GroundTruth:
    # 真因果链 S0 近切 → 诱发 S3 求交失败；涉及两张面
    return GroundTruth(
        true_chain=[S0, S3],
        entities=["faceA", "faceB"],
        expected_evidence="期望 1 条 contact 曲线，实得 0",
        aligned_fix="heal 输入（容差），非降半径",
        failure_class=failure_class,
    )


def _concl(stage, chain, *, entities=(), depth="stage", conf=0.5, cf=None, cf_verdict=None,
           fc=None, abstain=False):
    if abstain:
        return Conclusion(abstained=True, abstain_reason="证据不足")
    h = CausalHypothesis(
        stage=stage, cause="t", chain=list(chain), entities=list(entities),
        localization_depth=depth, counterfactual=cf, counterfactual_verdict=cf_verdict,
        confidence=conf, failure_class=fc,
    )
    return Conclusion(hypotheses=[h])


def _approx(a, b, eps=1e-9):
    return abs(a - b) <= eps


def main() -> int:
    gt = _gt()
    fails = []

    def check(name, cond):
        print(("PASS " if cond else "FAIL ") + name)
        if not cond:
            fails.append(name)

    # 1) 命中根（S0 作 distal 根）+ 实体全中 → stage 1.0, entity 1.0 → 1.0
    r = score(_concl(S0, [S0, S3], entities=["faceA", "faceB"]), gt)
    check("root-as-root + full entities → 1.0", _approx(r["localization"], 1.0))
    check("exact_chain flagged", r["detail"]["exact_chain"] is True)

    # 2) 含根但顺序反（根不在最远端）+ 实体全中 → 0.7*0.7 + 0.3*1.0 = 0.79
    r = score(_concl(S3, [S3, S0], entities=["faceA", "faceB"]), gt)
    check("root-in-chain (not distal) → 0.79", _approx(r["localization"], 0.79))

    # 3) 只命中症状 S3 + 实体半中 → 0.7*0.4 + 0.3*0.5 = 0.43
    r = score(_concl(S3, [S3], entities=["faceA"]), gt)
    check("symptom-only + half entities → 0.43", _approx(r["localization"], 0.43))

    # 4) 全不沾 → 0
    r = score(_concl(S5, [S5], entities=["faceZ"]), gt)
    check("miss → 0.0", _approx(r["localization"], 0.0))

    # 5) 部分得分单调：root > root-in-chain > symptom > miss（仅 stage 维）
    s_root = score(_concl(S0, [S0, S3]), gt)["detail"]["stage_localization"]
    s_in = score(_concl(S3, [S3, S0]), gt)["detail"]["stage_localization"]
    s_sym = score(_concl(S3, [S3]), gt)["detail"]["stage_localization"]
    s_miss = score(_concl(S5, [S5]), gt)["detail"]["stage_localization"]
    check("monotone root>in>symptom>miss", s_root > s_in > s_sym > s_miss)

    # 6) 机制深度代理：mechanism 深 > stage 浅
    deep = score(_concl(S0, [S0, S3], depth="mechanism"), gt)["mechanism"]
    shallow = score(_concl(S0, [S0, S3], depth="stage"), gt)["mechanism"]
    check("mechanism depth proxy deep>shallow", deep > shallow)

    # 7) 校准：置信度=正确性 → 1.0；过度自信 → 掉分
    aligned = score(_concl(S0, [S0, S3], conf=1.0), gt)["calibration"]  # stage_loc=1.0
    overconf = score(_concl(S5, [S5], conf=1.0), gt)["calibration"]     # stage_loc=0.0
    check("calibration aligned → 1.0", _approx(aligned, 1.0))
    check("calibration overconfident-wrong → 0.0", _approx(overconf, 0.0))

    # 8) 反事实真分（C1）：互斥判别 verdict vs GT 根。gt_s2 根=S2、症状=S3。
    gt_s2 = GroundTruth(true_chain=[S2, S3], entities=[], expected_evidence="",
                        aligned_fix="", failure_class="algorithmic_overflow")
    check("cf verdict==root(S2) → 1.0", _approx(score(_concl(S2, [S2, S3], cf_verdict="S2"), gt_s2)["counterfactual"], 1.0))
    check("cf verdict S2->S3 (distal=root S2) → 1.0", _approx(score(_concl(S2, [S2, S3], cf_verdict="S2->S3"), gt_s2)["counterfactual"], 1.0))
    check("cf verdict 命中症状(S3,非根) → 0.4", _approx(score(_concl(S2, [S2, S3], cf_verdict="S3"), gt_s2)["counterfactual"], 0.4))
    gt_s5 = GroundTruth(true_chain=[S5], entities=[], expected_evidence="", aligned_fix="")
    check("cf verdict 与链无交(claimed S2 ∉ [S5]) → 0.0", _approx(score(_concl(S5, [S5], cf_verdict="S2"), gt_s5)["counterfactual"], 0.0))
    check("cf inconclusive → None", score(_concl(S2, [S2, S3], cf_verdict="inconclusive"), gt_s2)["counterfactual"] is None)
    check("cf 未执行该腿(verdict None) → None", score(_concl(S2, [S2, S3], cf="prose only"), gt_s2)["counterfactual"] is None)

    # 9) 缺陷却弃权（wrong_abstain）：定位 n/a（不混入定位准确率，惩罚归 abstention），其余维 None
    r = score(_concl(None, None, abstain=True), gt)
    check("defect+abstain → localization n/a(None)", r["localization"] is None)
    check("defect+abstain → wrong_abstain", r["abstention"] == "wrong_abstain")
    check("abstain → mechanism/calibration None", r["mechanism"] is None and r["calibration"] is None)
    check("abstain → failure_class None", r["failure_class"] is None)

    # 10) 失效分类：GT 标了类别时——精确命中 1.0 / 判错 0.0 / 预测未给 None
    gt_fc = _gt(failure_class="algorithmic_overflow")
    hit = score(_concl(S0, [S0, S3], fc="algorithmic_overflow"), gt_fc)["failure_class"]
    wrong = score(_concl(S0, [S0, S3], fc="geometric_near_tangent"), gt_fc)["failure_class"]
    none_pred = score(_concl(S0, [S0, S3], fc=None), gt_fc)["failure_class"]
    check("failure_class hit → 1.0", _approx(hit, 1.0))
    check("failure_class wrong → 0.0 (不洗白判错)", _approx(wrong, 0.0))
    check("failure_class pred-missing → None", none_pred is None)
    # GT 未标 failure_class（如 box 只标了链）→ 即便预测给了也不参与（None）
    check("failure_class gt-unlabeled → None",
          score(_concl(S0, [S0, S3], fc="algorithmic_overflow"), gt)["failure_class"] is None)

    # 11) 弃权四态（abstention，区分度 case 的核心判别）
    clean = GroundTruth(true_chain=[], entities=[], expected_evidence="无缺陷",
                        aligned_fix="无", expected_abstain=True)
    # clean + 弃权 = correct_abstain；定位 n/a（不罚），其余维 None
    r = score(_concl(None, None, abstain=True), clean)
    check("clean+abstain → correct_abstain", r["abstention"] == "correct_abstain")
    check("clean+abstain → localization n/a(None)", r["localization"] is None)
    # clean + 下结论 = false_commit（幻觉根因）→ 定位 0 罚
    r = score(_concl(S2, [S2]), clean)
    check("clean+commit → false_commit", r["abstention"] == "false_commit")
    check("clean+commit → localization 0(罚)", _approx(r["localization"], 0.0))
    # 缺陷 case + 弃权 = wrong_abstain（漏检）；缺陷 + 下结论 = correct_commit
    check("defect+abstain → wrong_abstain",
          score(_concl(None, None, abstain=True), gt)["abstention"] == "wrong_abstain")
    check("defect+commit → correct_commit",
          score(_concl(S0, [S0, S3]), gt)["abstention"] == "correct_commit")

    print(f"\n{'ALL PASS' if not fails else str(len(fails)) + ' FAILED: ' + ', '.join(fails)}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
