# 根因 Eval 回归基线（baselines）

> 由 `eval/eval.sh`（→ `eval/runner.py`）产出并手动登记。打分维度见
> [../docs/root-cause-verification.md](../docs/root-cause-verification.md) §6 + `eval/scorer.py` 文档。
> 复现：`bash agent/eval/eval.sh`（需 debug FreeCADCmd；缺则相关 case 标 SKIP，不假绿）。

## 规则版 policy（A3 基线）

> 跑于 2026-06-28，real 后端（debug OCCT 7.8.1 + FreeCADCmd），6 个 case（**失效三态各 1 + clean 弃权 + false-green + 过度弃权**）。
> 分层＝按 GT `failure_class`；clean 自成 `clean/abstain` 层、false-green 归 `其它(无三态类)`。
> 决策走 `decide(state)` 接缝（policy=rule；A5 换 decide_llm 同表对比）。
> **定位准确率只在"承诺定位"的 case 上算；弃权 case 定位记 n/a，对错归 abstention（分账不混）。**

| 层 | n | 定位 | 失效分类 | 机制* | 反事实* | 校准 | 平均 tool-call | 平均 wall_s |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| clean/abstain | 1 | n/a | n/a | n/a | n/a | n/a | 2.0 | ~0.3 |
| algorithmic_overflow | 1 | 0.70 | 1.00 | 0.20 | 携带 | 0.70 | 5.0 | ~1.0 |
| geometric_curvature | 1 | 1.00 | 1.00 | 0.50 | 携带 | 0.70 | 5.0 | ~1.1 |
| geometric_near_tangent | 2 | 1.00¹ | 1.00 | 0.50 | 携带 | 0.70 | 7.5 | ~2.0 |
| 其它(无三态类)·false-green | 1 | 0.40 | n/a | 0.50 | 0.00 | 0.75 | 2.0 | ~0.4 |
| **全集** | **6** | **0.78** | **1.00** | **0.42** | — | **0.71** | **4.8** | ~1.1 |

¹ near-tangent 层 n=2 但定位均值只算 1 个**承诺**case（`wedge-sliver` 1.00）；另一 `wedge-thin-abstain` 弃权 → 定位 n/a（不入均值），其对错见弃权汇总。

逐 case：`box-r5`/`pocket-blind-hole`/`wedge-sliver` 三态根 S2 全中；`box-clean` 良性 → **正确弃权**；`thinplate-false-green` 薄板双面 fillet 自交但 IsDone=True → **抓出 false-green**（不信 IsDone），但只达症状 S3、未回溯 S2 根 → 定位 0.40（**首个触发症状-only 部分分**）；`wedge-thin-abstain` 极薄楔可行半径低于探针下限 → **过度弃权**。

**弃权/校准（集合量）**：correct_abstain=1 / wrong_abstain=1 / correct_commit=4 / **false_commit=0**；**abstention precision = 0.50**（弃权 2 次对 1 次——规则版在极薄楔上探针太粗、过度弃权，A5 可改进）。

读数说明（诚实边界）：

- **失效分类 1.00（三态全覆盖全中）**：免埋点诊断（triage_input 量近切角/凹曲率）精确区分 algorithmic / curvature / near-tangent 三态，与真值一致——A4 的核心可量化结论。
- **定位分层不均是真实信号，不是噪声**：
  - `wedge`（近切）/`pocket`（曲率）定位 **1.00**——triage 量出失效现场（近切边 `edge#0` @1.718° = LLDB 真值 1.72°；凹曲率面 `face#6` @r3），免埋点即可**实体级定位**。
  - `box`（overflow）定位 **0.70**——stage 满分但 entity 0：重叠的两 fillet 带是 S2 **中间面**，免埋点无法命名，需 **A7 capture**。这道 0↔1 差正是 capture 相对免埋点的实体定位增量。
  - `thinplate`（false-green）定位 **0.40**——**首个症状-only 部分分**：agent 抓出 IsDone=True 但自交（不信 IsDone ✅），但只达症状 S3、未回溯 S2 根（branch-B 不跑 radius_probe）。改进项：false-green 检出后也 radius_probe 回溯 S2 根。
- **弃权是一等结果，与定位分账**：clean 正确弃权（`box-clean`）、过度弃权（`wedge-thin-abstain`，可行半径 <探针下限 0.002 → 漏掉本可定位的 S2）——两者定位都记 **n/a**（不混入定位均值），对错全归 **abstention precision = 0.50**。这把"会不会幻觉/会不会过度弃权"和"定位准不准"两件事分开量——一个过度自信 LLM 会在 clean 上 false_commit、一个保守 LLM 会到处 wrong_abstain，都被抓。
- **机制\* / 反事实\***：机制仅 `localization_depth` 深度代理；反事实仅判"是否携带"（false-green 的 branch-B 未携带靶向修法 → 0.00，是诚实的待补点）。真分待 truth-run 中间态 / OCCT 执行（A8）。
- **校准 0.70~0.75**：置信与 stage 定位正确性之差。

> GT 基线说明：`box-r5`/`wedge-sliver` 是 LLDB 埋点真值；`pocket-blind-hole` 是**几何第一性真值**（r>凹曲率半径 ⟹ 滚球无解，几何必然，不依赖算法实现）+ radius_probe 边界证据（可行/不可行界恰落在曲率半径 3 上）+ triage 独立佐证 face#6 r3——honest 区分两类 GT 来源。
>
> **区分度（为 A5 A/B 铺路）**：纯 S2-fired case 单看 rule-vs-LLM 会双双顶天花板，证明不了 policy 好坏。已补 3 个能拉开区分度的 case：① `box-clean`（**clean 弃权**）测不幻觉——过度自信 LLM 会 false_commit。② `thinplate-false-green`（**false-green / 代理奖励陷阱**）测铁律——信 IsDone 的 policy 漏检，且触发症状-only 部分分（0.40）。③ `wedge-thin-abstain`（**loop 内过度弃权**）——可行半径低于探针下限，规则版 wrong_abstain，abstention precision 因此从 1.00 掉到 0.50（真实弱点，A5 可用自适应探针改进）。⏳ 仍缺：S0→S3 链（触发因果链部分得分，待 A7 capture 才能离线立真值）。

\* 机制=深度代理、反事实=仅判携带；真分待 truth-run 中间态 / OCCT 执行接入（A8）。

## LLM 版 policy（A5）

> 跑于 2026-06-28，`decide_llm` claude_cli 后端（本地 `claude -p`，`claude-opus-4-8`，复用 Claude Code 鉴权）。
> 决策已录制 `eval/llm_decisions/`（4 条唯一决策）；replay 后端离线确定复现本表、零计费、可进 CI。
> 同一 case 集、同一组确定性工具、同一 `decide(state)` 接缝——**只换决策臂**。

| 层 | n | 定位 | 失效分类 | 机制* | 反事实* | 校准 | 平均 tool-call | 平均 wall_s |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| clean/abstain | 1 | n/a | n/a | n/a | n/a | n/a | 2.0 | (branch B，不进 decide) |
| algorithmic_overflow | 1 | 0.70 | 1.00 | 0.20 | 携带 | 0.70 | 5.0 | ~39 |
| geometric_curvature | 1 | 1.00 | 1.00 | 0.50 | 携带 | 0.70 | 5.0 | ~34 |
| geometric_near_tangent | 2 | 1.00 | 1.00 | 0.50 | 携带 | 0.70 | 7.5 | ~41 |
| 其它(无三态类)·false-green | 1 | 0.40 | n/a | 0.50 | 0.00 | 0.75 | 2.0 | (branch B，不进 decide) |
| **全集** | **6** | **0.78** | **1.00** | **0.42** | — | **0.71** | **4.8** | ~26（决策延迟，replay 后 ~1.1） |

弃权/校准：correct_abstain=1 / wrong_abstain=1 / correct_commit=4 / false_commit=0；abstention precision=0.50。

### A/B 结论（rule vs LLM）

| 维度 | rule | LLM | 差 |
| --- | --- | --- | --- |
| 定位（全集） | 0.78 | 0.78 | **0** |
| 失效分类 | 1.00 | 1.00 | 0 |
| abstention precision | 0.50 | 0.50 | 0 |
| false_commit | 0 | 0 | 0 |
| 平均 tool-call | 4.83 | 4.83 | **0** |
| 平均 wall_s | 1.1 | ~26（real）/ 1.1（replay） | LLM 决策延迟 23× |

**LLM 各质量维 + tool-call 与规则版逐位持平,只慢在决策延迟。** 诚实解读:

- ✅ **印证"模型只在决策点、其余确定性"**:把决策臂从 rule 换成 LLM,正确性一字不变——质量由确定性工具 + 确定性结论合成扛住,LLM 只动"跑哪个判别器/何时收"。换 policy 不破坏任何东西,这正是分层的意义。
- LLM **独立**跑了 S0/S2/S3 全候选(录制决策含 run S0 / run S2 / run S3 / conclude),与 rule 同序穷尽 → 同 tool-call、同结论。**没找到效率增量**:3 候选决策表小、结论合成 order-independent,"跑全候选"已是最优,没有可省的判别器。
- **wedge-thin 的 wrong_abstain 两版都没救**:它是**探针分辨率极限**(可行半径 <0.002 探针下限),不是决策-policy 能解的——任何 policy 面对的都是"候选全 ruled_out"。要救得换更细的探针/领域推理工具,不是换决策臂。这是个精确的归因:**A/B 平手不代表 LLM 没用,而是这批 case 的剩余差距在工具层不在决策层。**

> 复现:`bash agent/eval/eval.sh`（rule）；`AGENT_DECIDE_BACKEND=replay AGENT_DECIDE_RECORD=agent/eval/llm_decisions bash agent/eval/eval.sh --policy llm`（LLM，离线零计费）。重录真决策:去掉 `AGENT_DECIDE_BACKEND=replay`（走 claude_cli，需 Claude Code 鉴权）。
>
> 难度分层将随 case 扩充加维（凹/凸 × 单边/链/顶点 × 定/变半径，G21）。当前按 failure_class + clean + 其它分层。
