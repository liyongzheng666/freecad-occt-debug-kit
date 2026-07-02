# Case 定义与 Ground Truth schema

> 关联：[../README.md](../README.md) A1、[../docs/root-cause-verification.md](../docs/root-cause-verification.md) §6、[../playbook/blend-failure-ontology.md](../playbook/blend-failure-ontology.md)。

## 1. Case 输入

每个 case 一个 **JSON 文件** `cases/<case_id>.json`（当前真值 case 走脚本化构造，故单文件即可；
若改用 `input.brep` 落盘资产再升级为目录）。一个 case 文件含：

- `input`：脚本化构造参数（builder / dims / radius / edges）——人读，记录这个 case 长什么样。
- `agent_run`：**eval runner 据此驱动 investigate** —— `{ "case": <harness builder id>, "radius": <float> }`。
  注意 `case` 是 `_fillet_harness.py` 认得的 builder id（如 `box` / `wedge`），**可能 ≠ `input.builder`**
  （如 wedge-sliver 的 input.builder=`wedge_prism`，agent_run.case=`wedge`）。runner 只跑带 `agent_run` 的文件。
- `truth_run`（可选）：instrumented LLDB 真崩点，作 GT 标签来源（G22）。
- `replay` fixture：reproduce 的 replay 后端读 `<record_dir>/<case>__r<radius>.json`（G7），让 eval 离线复现不拉重型栈。

## 2. 难度分层标签（G21）

`labels`：凹/凸 × 单边/链/顶点 × 定/变半径 × clean/overflow。每个 case 标全四维，eval 按层分别报。

## 3. Ground Truth（四元组，G22）

case 文件里的 `ground_truth` 块（多由 instrumented truth run 产出；早期用"构造已知根因的合成 case"手工标）：

```json
"ground_truth": {
  "true_chain": ["S0", "S3"],
  "entities": ["Face1", "Face2"],
  "expected_evidence": "两面二面角 < ε（S0 近切）→ SSI 得 0 条 contact 曲线（S3）",
  "aligned_fix": "heal_input（容差），保持 radius 不变",
  "failure_class": "geometric_near_tangent"
}
```

> **因果链已转正**（缺口1）：`true_chain` 为 distal→proximate（如 S0 近切 → 诱发 S3 求交失败）；
> 单阶段则单元素 `["S3"]`。`aligned_fix` 与**根**（`true_chain[0]`）对齐。
> scorer 对链给部分得分（命中根=满分，只命中症状=部分分；见 `contracts.GroundTruth.root_stage / symptom_stage`）。
> **`failure_class`（A4，P2.1 起四态）**：`algorithmic_overflow`（≥2 边两带重叠，可 SSI 互裁）/ **`face_overflow`**（单边单带溢出——
> 离开支撑面/盖过 edge loop，Parasolid Ch74/loop_c，2026-07-02 新增）/ `geometric_near_tangent` / `geometric_curvature`，与 playbook
> `failure_classes` 同枚举。scorer 据此判"失效分类准确率"——免埋点诊断能跑到的最深判别（决定靶向修法是否对症）。
> GT 未标则该维不参与（None，不假绿）。真实 STEP case（E2/E3/E4/E5）的 `agent_run` 多一个 `edges` 字段（读回边号，runner 透传）。

## 4. 首批 case（A1）

| case_id | 难度层 | 近端阶段 | 远端根因 |
| --- | --- | --- | --- |
| near-tangent-faces | 凹/单边/定/clean | S3 | S0 近切 → S3 |
| vertex-3corner | 凸/顶点/定/clean | S4 | S4 corner ⚠ 未实现——P2.2（2026-07-02②）8 族构型狩猎未获 S4-proximate 现场（OCCT 顶点收敛强于 Parasolid 约束，诚实负结果，见 `loop/test_investigate_vertex.py` 文档）|
| short-edge | 凹/单边/定/clean | S1 | S0/S1 短边 |
| box-concave-r-large | 凹/单边/定/clean | S3 | S2 球塞不进 |
