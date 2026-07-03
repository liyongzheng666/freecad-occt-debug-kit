"""生成/更新 Conclusion 快照基线（C2 Phase 2 / Option A：eval 基线回归门）。

真跑 investigate（需 FreeCADCmd）冻结每 case 的 Conclusion + tool_calls，并算出期望
分层指标，落 `agent/eval/baseline_snapshot.json`。CI 的 `test_baseline.py` 离线重放：
用【当前】scorer 对冻结 Conclusion 重打分，断言分层指标 == 冻结期望——抓 scorer/聚合
逻辑的回归漂移。

诚实边界：investigate 的**输出**被冻结，故本门**不** gate investigate 逻辑漂移（那需本地
真跑全套 test_investigate_*，见 README）。它 gate 的是 scorer 打分 + runner 聚合 + GT 加载
——即"baselines 数字不漂移"的那部分，且正是 C1（scorer 反事实真分）要动的地方的安全网。

用法：
  python -m agent.eval.snapshot          # 真跑全集重新生成快照（覆盖，需 FreeCADCmd）

有意改了 scorer/聚合（如 C1）后 → 重跑本命令更新快照、复审 diff、连同改动一起提交。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from agent.eval.runner import _abstention_summary, _aggregate, _discover_cases, _load_gt
from agent.eval.scorer import score
from agent.loop.investigate import investigate
from agent.trajectory import conclusion_to_dict

_SNAP = Path(__file__).resolve().parent / "baseline_snapshot.json"
_POLICY = "rule"                                   # 规则版 = 确定性下限基线（llm replay 与之持平）
_SCORE_DIMS = ("localization", "failure_class", "mechanism", "counterfactual", "calibration")


def build_row(case_id: str, doc: dict, concl, tool_calls: int) -> dict:
    """与 runner.run_case 同构的打分行——只留聚合/断言需要的**确定性**字段（不含 wall_s）。

    快照生成与离线门都走这个函数 → 二者行结构逐位一致，杜绝漂移。
    """
    gt = _load_gt(doc)
    sc = score(concl, gt, tool_calls=tool_calls)
    return {
        "case_id": case_id,
        "status": "OK",
        "gt_failure_class": gt.failure_class,
        "expected_abstain": gt.expected_abstain,
        "scores": {d: sc[d] for d in _SCORE_DIMS},
        "abstention": sc["abstention"],
        "tool_calls": sc["tool_calls"],
        "wall_s": None,                            # 快照门不断言时间（非确定项）
    }


def strip_wall(agg: dict) -> dict:
    """从分层聚合里剔除 wall_s（非确定，不进断言）。"""
    return {layer: {k: v for k, v in m.items() if k != "wall_s"} for layer, m in agg.items()}


def generate() -> int:
    cases = _discover_cases(None)
    if not cases:
        print("无可跑 case（cases/*.json 需含 agent_run + ground_truth）", file=sys.stderr)
        return 1
    snap: dict = {"policy": _POLICY, "cases": {}}
    rows = []
    for cid, doc in cases:
        run = doc["agent_run"]
        trace: list = []
        concl = investigate(run["case"], radius=run.get("radius"), ssi_fixture=run.get("ssi_fixture"),
                            policy=_POLICY, trace=trace, edges=run.get("edges"))
        snap["cases"][cid] = {"conclusion": conclusion_to_dict(concl), "tool_calls": len(trace)}
        rows.append(build_row(cid, doc, concl, len(trace)))
        print(f"  · {cid}: tool_calls={len(trace)} root="
              f"{concl.hypotheses[0].stage.value if concl.hypotheses else '弃权'}")
    snap["expected"] = {
        "aggregate": strip_wall(_aggregate(rows)),
        "abstention": _abstention_summary(rows),
    }
    _SNAP.write_text(json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[快照 → {_SNAP}]  {len(rows)} case，policy={_POLICY}")
    return 0


def main() -> int:
    try:
        return generate()
    except FileNotFoundError as e:                 # 无 FreeCADCmd/occ-debug-mesh → 生成不了（不假绿）
        print(f"无法生成快照（需 debug FreeCADCmd + occ-debug-mesh）：{e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
