"""decide_llm 纯函数离线自测（不碰网络/不调 claude）：python -m agent.loop.test_decide_llm

只验证 prompt 构造 + action 解析 + 录制回放映射——LLM 决策接缝里**唯一确定性**的部分。
实跑 claude_cli 后端的真 A/B 由 eval runner 录制（需鉴权，不在单测里）。
"""
from __future__ import annotations

from agent.contracts import RunEnd
from agent.loop.decide_llm import (
    _action_from_raw, _build_user_prompt, _parse_action, _unrun_candidates,
)

_NODE = {
    "id": "fillet-notdone-overflow",
    "root_cause_candidates": [
        {"stage": "S0", "cause": "输入近切", "localize": {"tool": "check_valid_input"}},
        {"stage": "S2", "cause": "半径过大", "localize": {"tool": "radius_probe"}},
        {"stage": "S3", "cause": "面面求交退化", "localize": {"tool": "ssi_probe"}},
    ],
}


def _state(verdicts):
    run = RunEnd(status="failed", exception="StdFail_NotDone", phase="fillet_notdone", is_done=False)
    return {"node": _NODE, "verdicts": verdicts, "run_end": run}


def main() -> int:
    fails = []

    def check(name, cond):
        print(("PASS " if cond else "FAIL ") + name)
        if not cond:
            fails.append(name)

    s0 = _NODE["root_cause_candidates"][0]

    # 1) unrun：已跑 S0 → 只剩 S2/S3
    unrun = _unrun_candidates(_state([(s0, "ruled_out", "ok")]))
    check("unrun excludes run stage", [c["stage"] for c in unrun] == ["S2", "S3"])

    # 2) prompt 只含证据/候选/节点，不泄露算法（应是合法 JSON，含 candidates_unrun）
    import json
    p = json.loads(_build_user_prompt(_state([])))
    check("prompt has node id", p["playbook_node"] == "fillet-notdone-overflow")
    check("prompt lists 3 unrun", len(p["candidates_unrun"]) == 3)
    check("prompt carries discriminator names",
          p["candidates_unrun"][1]["discriminator"] == "radius_probe")

    full_unrun = _NODE["root_cause_candidates"]
    # 3) 解析 run → 命中 unrun 候选
    a = _parse_action('{"action":"run","stage":"S2"}', full_unrun)
    check("parse run S2 → cand", a.get("run", {}).get("stage") == "S2")
    # 4) 解析 conclude
    check("parse conclude", _parse_action('{"action":"conclude"}', full_unrun) == {"conclude": True})
    # 5) 去 markdown 围栏
    a = _parse_action('```json\n{"action":"run","stage":"S3"}\n```', full_unrun)
    check("parse strips md fence", a.get("run", {}).get("stage") == "S3")
    # 6) 选了不在 unrun 的 stage → 安全收结论（回路有界）
    check("parse invalid stage → conclude",
          _parse_action('{"action":"run","stage":"S9"}', full_unrun) == {"conclude": True})
    # 7) 垃圾文本 → 安全收结论
    check("parse garbage → conclude", _parse_action("hmm not json", full_unrun) == {"conclude": True})
    # 8) 录制回放映射
    check("replay run_stage → cand",
          _action_from_raw({"run_stage": "S2"}, full_unrun).get("run", {}).get("stage") == "S2")
    check("replay conclude", _action_from_raw({"conclude": True}, full_unrun) == {"conclude": True})

    # 9) replay miss 抛 DecisionNotRecorded（非 FileNotFoundError）→ runner 归 ERROR 不是 SKIP（Part 7 修）
    import tempfile
    from agent.loop.decide_llm import _replay, DecisionNotRecorded
    check("DecisionNotRecorded 不是 FileNotFoundError 子类（否则被 runner 当 SKIP 吞掉）",
          not issubclass(DecisionNotRecorded, FileNotFoundError))
    with tempfile.TemporaryDirectory() as d:
        raised = "none"
        try:
            _replay("nosuchsig", d)
        except DecisionNotRecorded:
            raised = "DecisionNotRecorded"
        except FileNotFoundError:
            raised = "FileNotFoundError"
        check("replay miss → DecisionNotRecorded（响亮 ERROR，非静默 SKIP）", raised == "DecisionNotRecorded")

    print(f"\n{'ALL PASS' if not fails else str(len(fails)) + ' FAILED'}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
