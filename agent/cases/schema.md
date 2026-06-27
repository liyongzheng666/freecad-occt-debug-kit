# Case 定义与 Ground Truth schema

> 关联：[../README.md](../README.md) A1、[../docs/root-cause-verification.md](../docs/root-cause-verification.md) §6、[../playbook/blend-failure-ontology.md](../playbook/blend-failure-ontology.md)。

## 1. Case 输入

每个 case 一个目录 `cases/<case_id>/`：

- `input.brep`（或脚本化构造）+ `params.json`：半径、选中边、blend 类型。
- `runend.replay.json`：录制的 `RunEnd`，供 reproduce 的 replay 后端（G7）。

## 2. 难度分层标签（G21）

`labels`：凹/凸 × 单边/链/顶点 × 定/变半径 × clean/overflow。每个 case 标全四维，eval 按层分别报。

## 3. Ground Truth（四元组，G22）

`gt.json`（多由 instrumented truth run 产出；早期用"构造已知根因的合成 case"手工标）：

```json
{
  "true_chain": ["S0", "S3"],
  "entities": ["Face1", "Face2"],
  "expected_evidence": "两面二面角 < ε（S0 近切）→ SSI 得 0 条 contact 曲线（S3）",
  "aligned_fix": { "op": "heal_input", "must_not_change": "radius" }
}
```

> **因果链已转正**（缺口1）：`true_chain` 为 distal→proximate（如 S0 近切 → 诱发 S3 求交失败）；
> 单阶段则单元素 `["S3"]`。`aligned_fix` 与**根**（`true_chain[0]`）对齐。
> scorer 对链给部分得分（命中根=满分，只命中症状=部分分；见 `contracts.GroundTruth.root_stage / symptom_stage`）。

## 4. 首批 case（A1）

| case_id | 难度层 | 近端阶段 | 远端根因 |
| --- | --- | --- | --- |
| near-tangent-faces | 凹/单边/定/clean | S3 | S0 近切 → S3 |
| vertex-3corner | 凸/顶点/定/clean | S4 | S4 corner |
| short-edge | 凹/单边/定/clean | S1 | S0/S1 短边 |
| box-concave-r-large | 凹/单边/定/clean | S3 | S2 球塞不进 |
