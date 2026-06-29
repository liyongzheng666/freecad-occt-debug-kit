"""SessionWriter 离线自测（无 pytest 依赖）：python -m agent.test_session

验证 emit_* 落出的事件①是合法 JSON、②带齐协议必填头、③op 必填字段满足
event.schema.json（note 需 level+message；run_end 需 status）、④seq 单调、
⑤append-only 不 truncate。
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from agent.contracts import CausalHypothesis, Conclusion, Review, Stage, ToolResult
from agent.session import SCHEMA_VERSION, SessionWriter

_HEADER = {"schema_version", "session_id", "run_id", "seq", "op"}


def main() -> int:
    fails = []

    def check(name, cond):
        print(("PASS " if cond else "FAIL ") + name)
        if not cond:
            fails.append(name)

    with tempfile.TemporaryDirectory() as d:
        sess = Path(d) / "sess-001"
        w = SessionWriter(sess, run_id="agent")

        e1 = w.emit_tool_result(ToolResult(
            tool="reproduce", ok=True, summary="recompute done",
            artifact_id="brep/out.brep", source="agent/tools/reproduce.py:42",
            payload={"status": "failed", "phase": "S3"},
        ))
        e2 = w.emit_tool_result(ToolResult(
            tool="check_valid", ok=False, error="OCCT import failed",
        ))
        concl = Conclusion(hypotheses=[CausalHypothesis(
            stage=Stage.S0_INPUT, cause="近切", chain=[Stage.S0_INPUT, Stage.S3_SSI],
            entities=["faceA", "faceB"], localization_depth="mechanism",
            counterfactual="heal 有效、降半径无效", confidence=0.8,
        )])
        e3 = w.emit_conclusion(concl)
        e4 = w.emit_conclusion(Conclusion(abstained=True, abstain_reason="证据不足"))
        # review 写回（A6/G10）：op=review 需 verdict，锚到 e3 这条 run_end
        e5 = w.emit_review(
            Review(reviewer="u", verdict="correct", corrected_root=Stage.S3_SSI,
                   corrected_entities=["edge#7"], note="应归 S3"),
            target_run_id=e3["run_id"], target_seq=e3["seq"],
        )

        # 协议头齐备 + schema_version 正确
        for i, e in enumerate([e1, e2, e3, e4]):
            check(f"event[{i}] header complete", _HEADER <= set(e))
            check(f"event[{i}] schema_version", e["schema_version"] == SCHEMA_VERSION)

        # op 必填字段
        check("note requires level+message", {"level", "message"} <= set(e1))
        check("tool fail → infrastructure_failure", e2["level"] == "infrastructure_failure")
        check("source parsed file:line", e1["source"] == {"file": "agent/tools/reproduce.py", "line": 42})
        check("run_end requires status", "status" in e3 and e3["status"] == "succeeded")
        check("abstain → aborted", e4["status"] == "aborted")
        check("conclusion summary carries chain", e3["summary"]["hypotheses"][0]["chain"] == ["S0", "S3"])
        check("run_end summary carries failure_class key", "failure_class" in e3["summary"]["hypotheses"][0])

        # review op：verdict 必填 + corrected_* + 锚点字段落出
        check("review op + verdict", e5["op"] == "review" and e5["verdict"] == "correct")
        check("review corrected_root value", e5["corrected_root"] == "S3")
        check("review corrected_entities", e5["corrected_entities"] == ["edge#7"])
        check("review target anchor", e5["target_run_id"] == "agent" and e5["target_seq"] == e3["seq"])

        # seq 单调 0..4
        check("seq monotonic", [e["seq"] for e in [e1, e2, e3, e4, e5]] == [0, 1, 2, 3, 4])

        # 落盘可逐行 parse + 不 truncate（5 行）
        lines = (sess / "events.ndjson").read_text(encoding="utf-8").splitlines()
        check("5 lines persisted", len(lines) == 5)
        parsed_ok = True
        for ln in lines:
            try:
                json.loads(ln)
            except Exception:
                parsed_ok = False
        check("every line valid JSON", parsed_ok)

        # 新 writer 续接 seq（不重号）
        w2 = SessionWriter(sess, run_id="agent")
        e6 = w2.emit_tool_result(ToolResult(tool="triage", ok=True))
        check("re-open continues seq", e6["seq"] == 5)

    print(f"\n{'ALL PASS' if not fails else str(len(fails)) + ' FAILED: ' + ', '.join(fails)}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
