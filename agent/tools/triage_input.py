"""triage_input(shape) — S0 输入预检，agent 首发诊断（A2 / G18）。

沿 spine 凹/凸分类、量二面角、查短边/sliver、容差一致性、输入 BRepCheck
（playbook/blend-failure-ontology.md S0）。大量"blend bug"其实是 input bug，
所以这是最便宜、命中率最高的第一动作。占位：实现见 README §3 A2。
"""
from __future__ import annotations

from agent.contracts import TriageReport


def triage_input(brep_path: str, *, edges: list[str] | None = None) -> TriageReport:
    raise NotImplementedError("A2 — 见 agent/README.md §3 A2")
