"""规则版 policy（A3 / G1）—— eval 下限基线 + A/B 的 rule 臂。

`decide(state)` 是 investigate 回路的**唯一决策接缝**：给"到目前为止的结构化证据 + 命中的
playbook 节点"，选"下一个动作（跑哪个候选判别器）或下结论"。模型只在这个点出现——A5 的
`decide_llm` 同签名(state)->action 直接替换；其余（observe / 判别器执行 / 结论合成）一律
确定性。这正是 README『模型只在决策点、其余确定性』的落点，也是 rule-vs-LLM A/B 的接缝。

规则臂策略：按 playbook 候选的 distal→proximate 顺序逐个跑判别器，全跑完即下结论。
（结论合成——取最 distal 命中者为根 + 失效三态细分——是决策之后的确定性后处理，不在本函数。）
"""
from __future__ import annotations


def decide_rule(state: dict) -> dict:
    """state：{"node": 命中的 playbook 节点, "verdicts": [(cand, status, ev)…], "run_end": RunEnd}。

    返回 {"run": candidate_dict}（还有没跑的候选 → 跑下一个）
       或 {"conclude": True}（候选已穷尽 → 交给确定性结论合成）。

    rule 臂 = 顺序穷尽：已跑 len(verdicts) 个，就跑第 len(verdicts) 个；越界即下结论。
    """
    cands = state["node"]["root_cause_candidates"]
    idx = len(state["verdicts"])
    if idx < len(cands):
        return {"run": cands[idx]}
    return {"conclude": True}
