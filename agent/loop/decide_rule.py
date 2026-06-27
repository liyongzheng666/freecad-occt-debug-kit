"""规则版 policy（A3 / G1）—— eval 下限基线，也是回路 smoke test。

输入结构化证据 + 命中的 playbook 节点，输出"下一个动作或下结论"。
占位：实现见 README §3 A3。
"""
from __future__ import annotations

from agent.contracts import RunEnd


def decide_rule(run_end: RunEnd, playbook_node: dict | None, evidence: list) -> dict:
    """返回 {"action": {tool, args}} 或 {"conclude": True}。"""
    raise NotImplementedError("A3 — 见 agent/README.md §3 A3")
