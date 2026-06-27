"""score(conclusion, ground_truth) — 根因四维打分（A4 / G5）。

定位准确率 / 机制正确性 / 反事实有效性 / 校准弃权
（docs/root-cause-verification.md §6）。

诚实边界（避免"假绿"，呼应 README §7 B1）——四维里哪几维**此刻可自动判**：

  | 维度 | 现在 | 依赖 |
  | --- | --- | --- |
  | 定位 localization | ✅ 全量自动判（因果链部分得分 + 实体召回） | 仅需 GT.true_chain（已有） |
  | 机制 mechanism    | ⚠️ 仅深度代理 | 真值需 truth-run 中间态（交线条数等），A8 接 |
  | 反事实 counterfactual | ⚠️ 仅"是否携带" | 真值需执行靶向修法重跑判 S6 有效，需 OCCT |
  | 校准 calibration  | ✅ 单 case 置信-正确对齐；弃权精度是集合量，runner 汇总 | — |

定位维度对【因果链】给部分得分（GroundTruth.true_chain，缺口1）：命中根
（root_stage，distal）= 满分；链里含根但没当最远端 = 次分；只命中症状
（symptom_stage）= 部分分；全不沾 = 0。再叠实体召回。
"""
from __future__ import annotations

from agent.contracts import CausalHypothesis, Conclusion, GroundTruth, Stage

# 定位分档（stage 维）：命中根 / 含根 / 只命中症状 / miss
_HIT_ROOT_AS_ROOT = 1.0
_HIT_ROOT_IN_CHAIN = 0.7
_HIT_SYMPTOM_ONLY = 0.4
_MISS = 0.0

# 机制深度代理：定位站到多深（真机制正确性待 truth-run 中间态）
_MECH_DEPTH_PROXY = {"mechanism": 1.0, "entity": 0.5, "stage": 0.2}

_STAGE_WEIGHT = 0.7
_ENTITY_WEIGHT = 0.3


def _stage_localization(pred: CausalHypothesis, gt: GroundTruth) -> float:
    """因果链 stage 维部分得分：命中根 > 含根 > 只命中症状 > miss。"""
    chain = pred.chain or [pred.stage]
    root, symptom = gt.root_stage, gt.symptom_stage
    if chain[0] == root:
        return _HIT_ROOT_AS_ROOT
    if root in chain:
        return _HIT_ROOT_IN_CHAIN
    if symptom in chain:
        return _HIT_SYMPTOM_ONLY
    return _MISS


def _entity_recall(pred: CausalHypothesis, gt: GroundTruth) -> float | None:
    """命中实体 / GT 实体（召回）。GT 无标实体则不参与（None）。"""
    gt_ents = set(gt.entities)
    if not gt_ents:
        return None
    return len(gt_ents & set(pred.entities)) / len(gt_ents)


def score(
    conclusion: Conclusion,
    gt: GroundTruth,
    *,
    tool_calls: int | None = None,
) -> dict:
    """返回 {localization, mechanism, counterfactual, calibration, tool_calls, detail}。

    无人在环、自动判。仅评估排序后的首条假设（hypotheses[0]）；弃权单独处理。
    机制/反事实在真值（truth-run 中间态 / OCCT 执行）接入前返回代理或 None，并在
    detail.*_basis 标明依据，绝不用代理冒充真分。
    """
    gt_chain = [s.value for s in gt.true_chain]
    detail: dict = {
        "abstained": conclusion.abstained,
        "gt_root": gt.root_stage.value,
        "gt_symptom": gt.symptom_stage.value,
        "gt_chain": gt_chain,
    }

    if conclusion.abstained or not conclusion.hypotheses:
        # 没给定位 → localization 0；校准是集合量（abstention precision），单 case 不判
        detail.update(
            mechanism_basis="abstained",
            counterfactual_basis="abstained",
            calibration_basis="弃权精度为集合量，由 eval runner 汇总（abstention precision）",
        )
        return {
            "localization": _MISS,
            "mechanism": None,
            "counterfactual": None,
            "calibration": None,
            "tool_calls": tool_calls,
            "detail": detail,
        }

    top = conclusion.hypotheses[0]
    pred_chain = top.chain or [top.stage]

    # —— 定位（全量自动判）——
    stage_loc = _stage_localization(top, gt)
    entity_rec = _entity_recall(top, gt)
    if entity_rec is None:
        localization = stage_loc
    else:
        localization = _STAGE_WEIGHT * stage_loc + _ENTITY_WEIGHT * entity_rec
    gt_set = set(gt.true_chain)
    chain_coverage = len(gt_set & set(pred_chain)) / len(gt_set)

    # —— 机制（深度代理，真值待 truth-run 中间态）——
    mechanism = _MECH_DEPTH_PROXY.get(top.localization_depth, 0.0)

    # —— 反事实（仅判是否携带；S6 有效性需执行）——
    counterfactual = None if top.counterfactual else _MISS

    # —— 校准（单 case：置信度与定位正确性对齐）——
    calibration = 1.0 - abs(top.confidence - stage_loc)

    detail.update(
        predicted_root=pred_chain[0].value,
        predicted_chain=[s.value for s in pred_chain],
        stage_localization=stage_loc,
        entity_recall=entity_rec,
        chain_coverage=chain_coverage,
        exact_chain=(pred_chain == gt.true_chain),
        confidence=top.confidence,
        mechanism_basis="深度代理（localization_depth）；真机制正确性待 truth-run 中间态接入（A8）",
        counterfactual_basis=(
            "仅判是否携带靶向修法；S6 有效性 + 互斥判别需执行 reproduce+check_valid（OCCT）"
        ),
        calibration_basis="单 case 置信-正确对齐；弃权精度由 runner 汇总",
    )
    return {
        "localization": localization,
        "mechanism": mechanism,
        "counterfactual": counterfactual,
        "calibration": calibration,
        "tool_calls": tool_calls,
        "detail": detail,
    }
