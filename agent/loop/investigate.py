"""investigate(case) — 编排 observe→定位→机制→反事实→结论（A3 / G1 / G20）。

三腿验证见 docs/root-cause-verification.md §3：
  定位（靶向子复现） + 机制（中间态证据） + 反事实（互斥靶向修法判别）。
证据不足 → Conclusion.abstained=True 交人兜底。
决策 + tool-call 轨迹写 agent/trajectories/（G9）。占位：实现见 README §3 A3。
"""
from __future__ import annotations

from agent.contracts import Conclusion


def investigate(case_id: str, *, policy: str = "rule") -> Conclusion:
    """policy: "rule"(A3 规则版) | "llm"(A5)。"""
    raise NotImplementedError("A3 — 见 agent/README.md §3 A3")


if __name__ == "__main__":
    raise SystemExit("stub — A3 未实现；见 agent/README.md §5『本周可立即开工』")
