"""query_playbook 单测（纯逻辑，无 FreeCAD）：python -m agent.tools.test_playbook

测匹配语义 + 决策表 schema 完整性（守住 stage 合法性 → 防 investigate 里 Stage() 炸）。
"""
from __future__ import annotations

from agent.contracts import Stage
from agent.tools.playbook import _load_nodes, query_playbook

_NOTDONE = "OCCError: 15StdFail_NotDone BRep_API: command not done"


def main() -> int:
    fails = []

    def check(name, cond):
        print(("PASS " if cond else "FAIL ") + name)
        if not cond:
            fails.append(name)

    # —— 匹配 ——
    n = query_playbook({"exception": _NOTDONE, "phase": "fillet_notdone"})
    check("命中 overflow 节点", n is not None and n["id"] == "fillet-notdone-overflow")
    check("近端阶段 S2", n["proximate_stage"] == "S2")
    check("候选按 distal->proximate = [S0,S2,S3,S4]（P2.2 加 S4 顶点候选）",
          [c["stage"] for c in n["root_cause_candidates"]] == ["S0", "S2", "S3", "S4"])
    check("exception_contains 子串匹配（非全等）", n is not None)  # _NOTDONE 含 StdFail_NotDone

    # —— 不匹配 ——
    check("无 NotDone -> None", query_playbook({"exception": "boom else", "phase": "fillet_notdone"}) is None)
    check("phase 不符 -> None", query_playbook({"exception": _NOTDONE, "phase": "harness"}) is None)
    check("exception 缺失 -> None（不崩）", query_playbook({"phase": "fillet_notdone"}) is None)
    check("空 signature -> None", query_playbook({}) is None)

    # —— schema 完整性 ——
    valid_stages = {s.value for s in Stage}
    nodes = _load_nodes()
    check("决策表非空", len(nodes) >= 1)
    for node in nodes:
        nid = node.get("id", "?")
        for key in ("id", "symptom", "proximate_stage", "root_cause_candidates"):
            check(f"{nid} 有 {key}", key in node)
        check(f"{nid} proximate_stage 合法", node.get("proximate_stage") in valid_stages)
        for c in node.get("root_cause_candidates", []):
            sid = c.get("stage", "?")
            check(f"{nid}/{sid} stage 合法", c.get("stage") in valid_stages)
            check(f"{nid}/{sid} 有 cause", bool(c.get("cause")))
            check(f"{nid}/{sid} 有 localize.tool", bool(c.get("localize", {}).get("tool")))

    print(f"\n{'ALL PASS' if not fails else str(len(fails)) + ' FAILED: ' + ', '.join(fails)}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
