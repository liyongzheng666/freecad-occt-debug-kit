"""query_playbook(signature) — 检索决策表节点（A2 / G4 / G19）。

读 playbook/fillet-failures.yaml；节点 schema 见
playbook/blend-failure-ontology.md §5。占位：实现见 README §3 A2。
"""
from __future__ import annotations


def query_playbook(signature: dict) -> dict | None:
    """signature: {exception, phase}。返回命中的 playbook 节点或 None。"""
    raise NotImplementedError("A2 — 见 agent/README.md §3 A2")
