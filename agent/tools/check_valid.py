"""check_valid(shape) — 几何有效性判据，替代 IsDone()（A2 / G17）。

成功判据 = BRepCheck_Analyzer + 自交（BOPAlgo_CheckerSI）+ G1/切向 + 拓扑增量合理
（docs/root-cause-verification.md §2）。全项目以此为成功判据；裸 IsDone() 仅作诊断信号。

⚠️ 这是【一等几何交付物 + 整个 eval 的 reward signal】，不是 wrapper：完整自交
（BOPAlgo_CheckerSI）与全形状 G1 检测在 OCCT 里都是实打实的几何活；它一旦悄悄判错，
整个 eval 跟着腐坏。必须配自己的测试集（已知有效 / 已知自交 / 已知丢 G1 各若干）。
占位：实现见 README §3 A2。
"""
from __future__ import annotations

from agent.contracts import ValidityReport


def check_valid(brep_path: str) -> ValidityReport:
    raise NotImplementedError("A2 — 见 agent/README.md §3 A2")
