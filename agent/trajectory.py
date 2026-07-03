"""Agent 运行轨迹（A6 / G9）：决策 + tool-call + 结论 的有序 append-only 记录。

轨迹 = 一次 investigate run 的有序步骤：
  observe(reproduce) → [decide→action → 判别裁定]* → conclude
每步一行 ndjson。用途（呼应 README §6 A6）：
  - **离线重放 + 重打分**：`replay_conclusion(path)` 不拉 OCCT 直接重建结论 → 喂 scorer
    （证明"轨迹可离线评分/重放"，与 reproduce/decide_llm 的 record/replay 同纪律）。
  - **人工 review 的对象**：reviewer 读一条轨迹/结论 → 出 Review（见 agent/review.py，G10）。

只序列化打分需要的字段（top 假设的 stage/chain/entities/depth/failure_class/confidence/
是否携带反事实 + 是否弃权）；证据摘要保留人读，evidence 的 artifact 锚点不进轨迹（轨迹是
决策记录，不是几何资产）。
"""
from __future__ import annotations

import json
from pathlib import Path

from agent.contracts import CausalHypothesis, Conclusion, Evidence, Stage


def conclusion_to_dict(c: Conclusion) -> dict:
    """Conclusion → 可序列化 dict（打分字段齐备，可被 conclusion_from_dict 逆回）。"""
    return {
        "abstained": c.abstained,
        "abstain_reason": c.abstain_reason,
        "hypotheses": [{
            "stage": h.stage.value,
            "chain": [s.value for s in h.chain],
            "entities": list(h.entities),
            "localization_depth": h.localization_depth,
            "failure_class": h.failure_class,
            "confidence": h.confidence,
            "counterfactual": h.counterfactual,
            "counterfactual_verdict": h.counterfactual_verdict,
            "cause": h.cause,
            "evidence": [e.summary for e in h.evidence],
        } for h in c.hypotheses],
    }


def conclusion_from_dict(d: dict) -> Conclusion:
    """dict → Conclusion（重建后喂 scorer 与 live 同分）。"""
    return Conclusion(
        abstained=d.get("abstained", False),
        abstain_reason=d.get("abstain_reason", ""),
        hypotheses=[CausalHypothesis(
            stage=Stage(h["stage"]),
            cause=h.get("cause", ""),
            chain=[Stage(s) for s in h.get("chain", [])],
            entities=list(h.get("entities", [])),
            localization_depth=h.get("localization_depth", "stage"),
            evidence=[Evidence(summary=s) for s in h.get("evidence", [])],
            counterfactual=h.get("counterfactual"),
            counterfactual_verdict=h.get("counterfactual_verdict"),
            confidence=h.get("confidence", 0.0),
            failure_class=h.get("failure_class"),
        ) for h in d.get("hypotheses", [])],
    )


class TrajectoryWriter:
    """收集有序步骤 → append-only ndjson（trajectories/<run>.ndjson，G9，gitignore）。

    investigate 把 traj 列表传进来逐步 append；run 末 flush 到磁盘。也可只在内存收集
    （传 list 给 investigate(trajectory=...)）再手动 write。
    """

    def __init__(self, path: str | None = None):
        self.path = Path(path) if path else None
        self.steps: list[dict] = []

    def emit(self, step: dict) -> None:
        self.steps.append(step)

    def write(self) -> None:
        if self.path is None:
            raise ValueError("TrajectoryWriter 无 path，无法落盘（仅内存收集）")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as f:
            for i, s in enumerate(self.steps):
                f.write(json.dumps({"step": i, **s}, ensure_ascii=False) + "\n")


def read_trajectory(path: str) -> list[dict]:
    """读回有序步骤。"""
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def replay_conclusion(path: str) -> Conclusion:
    """从轨迹的 conclude 步重建结论（离线，不拉 OCCT）。供重打分。"""
    for s in reversed(read_trajectory(path)):
        if s.get("t") == "conclude":
            return conclusion_from_dict(s["conclusion"])
    raise ValueError(f"轨迹无 conclude 步：{path}")
