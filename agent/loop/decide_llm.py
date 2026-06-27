"""LLM 版 policy（A5 / G8）。

prompt 只含：角色 + 当前结构化证据 + 命中 playbook 节点 + 可用工具 + "选动作或下结论"。
不含算法细节 / 算术 / 几何提取逻辑。temperature=0 + 固定 seed + 记录工具输出（G7）。
占位：实现见 README §3 A5。
"""
from __future__ import annotations

from agent.contracts import RunEnd


def decide_llm(run_end: RunEnd, playbook_node: dict | None, evidence: list) -> dict:
    """与 decide_rule 同签名，便于 A/B 直接替换。"""
    raise NotImplementedError("A5 — 见 agent/README.md §3 A5")
