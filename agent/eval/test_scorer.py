"""scorer 离线自测（无 pytest 依赖）：python -m agent.eval.test_scorer

验证因果链部分得分（缺口1）：命中根 > 含根 > 只命中症状 > miss，叠实体召回，
以及弃权路径。check_valid「必须配自己的测试集」的同款纪律——reward signal 不能
悄悄判错。
"""
from __future__ import annotations

from agent.contracts import CausalHypothesis, Conclusion, GroundTruth, Stage
from agent.eval.scorer import score

S0, S2, S3, S5 = Stage.S0_INPUT, Stage.S2_SURFACE, Stage.S3_SSI, Stage.S5_SEW


def _gt() -> GroundTruth:
    # 真因果链 S0 近切 → 诱发 S3 求交失败；涉及两张面
    return GroundTruth(
        true_chain=[S0, S3],
        entities=["faceA", "faceB"],
        expected_evidence="期望 1 条 contact 曲线，实得 0",
        aligned_fix="heal 输入（容差），非降半径",
    )


def _concl(stage, chain, *, entities=(), depth="stage", conf=0.5, cf=None, abstain=False):
    if abstain:
        return Conclusion(abstained=True, abstain_reason="证据不足")
    h = CausalHypothesis(
        stage=stage, cause="t", chain=list(chain), entities=list(entities),
        localization_depth=depth, counterfactual=cf, confidence=conf,
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

    # 8) 反事实：携带 → 非 miss(None)；不携带 → 0.0
    check("counterfactual carried → None", score(_concl(S0, [S0, S3], cf="heal"), gt)["counterfactual"] is None)
    check("counterfactual absent → 0.0", _approx(score(_concl(S0, [S0, S3]), gt)["counterfactual"], 0.0))

    # 9) 弃权：localization 0、机制/反事实/校准 None
    r = score(_concl(None, None, abstain=True), gt)
    check("abstain → localization 0", _approx(r["localization"], 0.0))
    check("abstain → mechanism/calibration None", r["mechanism"] is None and r["calibration"] is None)

    print(f"\n{'ALL PASS' if not fails else str(len(fails)) + ' FAILED: ' + ', '.join(fails)}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
