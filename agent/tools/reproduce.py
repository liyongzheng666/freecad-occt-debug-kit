"""reproduce(case) — 跑 FreeCADCmd recompute，返回结构化 RunEnd（A1 / G2 / 架构 §24）。

real 后端跑真 FreeCADCmd；replay 后端读已录制的 RunEnd fixture（G7），
让 eval 不必每次拉起重型栈。占位：实现见 README §3 A1。
"""
from __future__ import annotations

from agent.contracts import RunEnd


def reproduce(case_id: str, *, radius: float | None = None, backend: str = "real") -> RunEnd:
    """backend: "real"(FreeCADCmd) | "replay"(录制 fixture)。"""
    raise NotImplementedError("A1 — 见 agent/README.md §3 A1")
