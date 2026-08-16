"""轨迹序列化 + 离线重放重打分自测（A6/G9，无 OCCT）：python -m agent.test_trajectory

证明"轨迹可离线重放 + 重打分"：Conclusion → dict → Conclusion 往返不丢打分字段，且重建的
结论喂 scorer 与原结论**同分**（轨迹是 record/replay 纪律的延伸）。
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from agent.contracts import CausalHypothesis, Conclusion, Evidence, GroundTruth, Stage
from agent.eval.scorer import score
from agent.trajectory import (
    TrajectoryWriter, conclusion_from_dict, conclusion_to_dict, read_trajectory, replay_conclusion,
)

S2, S3 = Stage.S2_SURFACE, Stage.S3_SSI


def _concl():
    return Conclusion(hypotheses=[CausalHypothesis(
        stage=S2, cause="半径过大", chain=[S2], entities=["edge#0"],
        localization_depth="entity", failure_class="geometric_near_tangent",
        counterfactual="lower_radius", confidence=0.7,
        evidence=[Evidence("playbook 命中"), Evidence("triage 近切")],
    )])


def main() -> int:
    fails = []

    def check(name, cond):
        print(("PASS " if cond else "FAIL ") + name)
        if not cond:
            fails.append(name)

    gt = GroundTruth(true_chain=[S2], entities=["edge#0"], expected_evidence="", aligned_fix="",
                     failure_class="geometric_near_tangent")

    # 1) 往返：打分字段不丢
    c = _concl()
    c2 = conclusion_from_dict(conclusion_to_dict(c))
    h, h2 = c.hypotheses[0], c2.hypotheses[0]
    check("roundtrip stage/chain", h2.stage == h.stage and h2.chain == h.chain)
    check("roundtrip entities/depth", h2.entities == h.entities and h2.localization_depth == h.localization_depth)
    check("roundtrip failure_class/conf", h2.failure_class == h.failure_class and h2.confidence == h.confidence)
    check("roundtrip counterfactual carried", bool(h2.counterfactual) == bool(h.counterfactual))

    # 2) 重建结论喂 scorer == 原结论同分（离线重打分核心）
    s1 = score(c, gt)
    s2 = score(c2, gt)
    check("rescore identical (localization)", s1["localization"] == s2["localization"])
    check("rescore identical (failure_class)", s1["failure_class"] == s2["failure_class"])
    check("rescore identical (mechanism/calibration)",
          s1["mechanism"] == s2["mechanism"] and s1["calibration"] == s2["calibration"])

    # 3) 弃权结论往返
    ab = Conclusion(abstained=True, abstain_reason="证据不足")
    ab2 = conclusion_from_dict(conclusion_to_dict(ab))
    check("abstain roundtrip", ab2.abstained and ab2.abstain_reason == "证据不足")

    # 4) TrajectoryWriter 落盘 → read → replay_conclusion 重建
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "run.ndjson"
        w = TrajectoryWriter(str(p))
        w.emit({"t": "observe", "case": "wedge", "radius": 1.0})
        w.emit({"t": "decide", "policy": "rule", "action": "S2"})
        w.emit({"t": "verdict", "stage": "S2", "tool": "radius_probe", "status": "fired", "evidence": "ok"})
        w.emit({"t": "conclude", "conclusion": conclusion_to_dict(c)})
        w.write()
        steps = read_trajectory(str(p))
        check("ndjson ordered steps", [s["t"] for s in steps] == ["observe", "decide", "verdict", "conclude"])
        check("steps numbered", steps[0]["step"] == 0 and steps[-1]["step"] == 3)
        replayed = replay_conclusion(str(p))
        check("replay_conclusion == live score",
              score(replayed, gt)["localization"] == s1["localization"])

    print(f"\n{'ALL PASS' if not fails else str(len(fails)) + ' FAILED'}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
