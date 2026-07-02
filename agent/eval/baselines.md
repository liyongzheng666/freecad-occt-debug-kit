# 根因 Eval 回归基线（baselines）

> 由 `eval/eval.sh`（→ `eval/runner.py`）产出并手动登记。打分维度见
> [../docs/root-cause-verification.md](../docs/root-cause-verification.md) §6 + `eval/scorer.py` 文档。
> 复现：`bash agent/eval/eval.sh`（需 debug FreeCADCmd；缺则相关 case 标 SKIP，不假绿）。

## 规则版 policy（A3 基线）

> 跑于 2026-06-28（原始 6 case）+ **2026-06-30 更新（A7 WP3 s3-fixture，共 7 case）**。real 后端（debug OCCT 7.8.1 + FreeCADCmd）。
> 分层＝按 GT `failure_class`；clean 自成 `clean/abstain` 层、false-green 归 `其它(无三态类)`。
> 决策走 `decide(state)` 接缝（policy=rule；A5 换 decide_llm 同表对比）。
> **定位准确率只在"承诺定位"的 case 上算；弃权 case 定位记 n/a，对错归 abstention（分账不混）。**
>
> **2026-06-29 更新（A7 WP1+WP3）**：下表 tool-call/wall 已含 A7 改动——**WP1** S3 候选经 capture 桥真跑 ssi_probe（near-tangent case +1 tool、wedge wall 升到 ~7s 因 LLDB capture）；**WP3** S2 分类后真跑互斥反事实 perturb_tolerance（升序容差阶梯，+≤3 reproduce/case）。**质量维（定位/失效分类/机制*/校准/弃权）逐位不变**——A7 是把第三腿（机制 capture + 反事实互斥）做实，不动定位正确性。
>
> **2026-06-30 更新（A7 WP3 s3-fixture）**：新增第 7 个 case `s3-fixture`——合成 fixture S3 case，覆盖 `_ssi_verdict fired` 分支（真实 S3 接触退化现场两轮 7 族未获，fixture 是诚实合成替代）。`investigate()` 加 `ssi_fixture` 路径：跳过 reproduce/playbook/radius_probe，直接跑 `ssi_probe(fixture='near-tangent')` → s3_signature=true → fired → 结论 root=S3。定位/失效分类均 1.00，tool=1（单次 ssi_probe），wall<0.3s。algorithmic_overflow 层由 n=1 升至 n=2，层均定位 0.85。
>
> **2026-07-01 更新（A7 WP5 box-r5 真实 S3 env_emit capture）**：`ChFi3d_Builder_0.cxx::StripeEdgeInter` 源码插桩（`DStr` 具名化 + `OCCT_DEBUG_SSI_OUT` 门控落盘两 blend 面），`_ssi_discriminate` 加 `env_emit` 路径 → **box-r5 的 S3 判别从"untestable"（无登记现场）升到"fired"（真实 blend 面，非 fixture）**：`capture_ssi_env('box',5)` 得两同轴 R5 圆柱 → `min_dihedral=0.0° section_edges=0` → `s3_signature=true`。**这不改任何质量维分数**（机制\*仍是 localization_depth 代理、定位仍 0.70——见下逐 case），只把 box-r5 的 tool-call 从 8→**9**（S3 候选真跑 `capture_ssi_env` +1，此前 untestable 不发工具）。故 algorithmic_overflow 层均 tool 4.5→**5.0**、全集 5.71→**5.86**。**box-r5 现是 overlap 型 S3 的真实机制现场**（三腿全实：radius_probe 定 S2 + ssi_probe 证 S3 proximate + 互斥反事实判根=S2），s3-fixture 退居"接触退化型 S3"的合成替补。

| 层 | n | 定位 | 失效分类 | 机制* | 反事实* | 校准 | 平均 tool-call | 平均 wall_s |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| clean/abstain | 1 | n/a | n/a | n/a | n/a | n/a | 2.0 | ~0.3 |
| algorithmic_overflow | **2** | **0.85** | 1.00 | 0.20 | 携带 | 0.72 | **5.0** | ~1.2 |
| geometric_curvature | 1 | 1.00 | 1.00 | 0.50 | 携带 | 0.70 | 8.0 | ~1.9 |
| geometric_near_tangent | 2 | 1.00¹ | 1.00 | 0.50 | 携带 | 0.70 | 9.5 | ~4.8 |
| 其它(无三态类)·false-green | 1 | 0.40 | n/a | 0.50 | 0.00 | 0.75 | 2.0 | ~0.4 |
| **全集** | **7** | **0.82** | **1.00** | **0.38** | — | **0.72** | **5.86** | ~2.1 |

¹ near-tangent 层 n=2 但定位均值只算 1 个**承诺**case（`wedge-sliver` 1.00）；另一 `wedge-thin-abstain` 弃权 → 定位 n/a（不入均值），其对错见弃权汇总。

逐 case：`box-r5`/`pocket-blind-hole`/`wedge-sliver` 三态根 S2 全中；**`s3-fixture` fixture S3 全中**（定位 1.00、失效分类 1.00、tool=1）；`box-clean` 良性 → **正确弃权**；`thinplate-false-green` 薄板双面 fillet 自交但 IsDone=True → **抓出 false-green**（不信 IsDone），但只达症状 S3、未回溯 S2 根 → 定位 0.40（**首个触发症状-only 部分分**）；`wedge-thin-abstain` 极薄楔可行半径低于探针下限 → **过度弃权**。

**弃权/校准（集合量）**：correct_abstain=1 / wrong_abstain=1 / correct_commit=5 / **false_commit=0**；**abstention precision = 0.50**（弃权 2 次对 1 次——规则版在极薄楔上探针太粗、过度弃权，A5 可改进）。

读数说明（诚实边界）：

- **失效分类 1.00（三态全覆盖全中）**：免埋点诊断（triage_input 量近切角/凹曲率）精确区分 algorithmic / curvature / near-tangent 三态，与真值一致——A4 的核心可量化结论。
- **定位分层不均是真实信号，不是噪声**：
  - `wedge`（近切）/`pocket`（曲率）定位 **1.00**——triage 量出失效现场（近切边 `edge#0` @1.718° = LLDB 真值 1.72°；凹曲率面 `face#6` @r3），免埋点即可**实体级定位**。
  - `box`（overflow）定位 **0.70**——stage 满分但 entity 0：重叠的两 fillet 带是 S2 **中间面**，免埋点无法命名。其句柄埋在 `ChFi3d_StripeEdgeInter` 的**匿名 `DStr`**（见 `cases/box-r5.json` truth_run + 记忆 fillet-overflow-crash-site），**capture 取不到具名面 → entity 维可能止于 stage 级；0.70 是诚实下限，不保证 A7 能升到 ~1.00**——与 wedge 近切「capture 可命名 HS1/HS2」相反，overflow 的实体定位增量 capture 未必兑得了，别把这格当待兑现的支票。**WP5（2026-07-01）验证了这个预判：**源码插桩把 `DStr` 具名化后，capture **确实取到了两 blend 面**（S3 机制从 untestable→fired），但取出的是通用 `Geom_Surface`（落盘为 `blend1`/`blend2`），**匹配不上 GT 的 `stripe1/2@S2` 命名 token → entity 维仍 0、定位仍 0.70**。即"capture 救得了机制维证据、救不了 entity 维命名"——机制真实性↑与 entity 打分是两码事，0.70 落定为已验证下限（非待兑支票）。
  - `thinplate`（false-green）定位 **0.40**——**首个症状-only 部分分**：agent 抓出 IsDone=True 但自交（不信 IsDone ✅），但只达症状 S3、未回溯 S2 根（branch-B 不跑 radius_probe）。改进项：false-green 检出后也 radius_probe 回溯 S2 根。
- **弃权是一等结果，与定位分账**：clean 正确弃权（`box-clean`）、过度弃权（`wedge-thin-abstain`，可行半径 <探针下限 0.002 → 漏掉本可定位的 S2）——两者定位都记 **n/a**（不混入定位均值），对错全归 **abstention precision = 0.50**。这把"会不会幻觉/会不会过度弃权"和"定位准不准"两件事分开量——一个过度自信 LLM 会在 clean 上 false_commit、一个保守 LLM 会到处 wrong_abstain，都被抓。
- **机制\* / 反事实\***：机制仅 `localization_depth` 深度代理；反事实仅判"是否携带"（false-green 的 branch-B 未携带靶向修法 → 0.00，是诚实的待补点）。真分待 truth-run 中间态 / OCCT 执行（A8）。
- **A7 WP1（机制腿 capture）做实但未改分**：S3 候选不再永久 untestable——near-tangent 经 capture 桥抓真支撑面跑 ssi_probe 得 `ruled_out`（wedge：1.7184° + section 1 条 contact 边 → 属 S2 非 S3）。这条机制证据进了结论的 evidence，但 scorer 的"机制\*"维仍是 `localization_depth` 代理、不直接打分 capture 结果——故分值不变、tool-call/wall 上升（增量是"证据质量"非"分数"，诚实标注）。
- **A7 WP3（反事实腿互斥判别 + s3-fixture eval）做实**：两个子任务：① 反事实从"声明修法字符串"升级为**真跑两个互斥修法出判别**——降半径（radius_probe 已 fired）+ 扰容差（perturb_tolerance，不动半径）。三态 S2 case 实测 **扰容差(≤0.1)无效 → 判 [S2]，排除 S3 容差敏感**（wedge/pocket/box 均如此，与真值一致——它们确非 S3 数值病态）；scorer 的"反事实\*"维仍只判"是否携带靶向修法"，真分待 scorer 加"反事实判别 vs GT"维（A8）。② **s3-fixture case 新增**（2026-06-30）：`_ssi_verdict fired` 分支在 eval 路径正式覆盖——两轮 7 族真实 S3 现场未获（WP2 诚实负结果），以合成 near-tangent fixture 替代；investigate() 新增 `ssi_fixture` 路径直接跑 ssi_probe，跳过 reproduce/radius_probe；eval 7 case 全 OK，13 单测全 PASS。
- **A7 WP5（box-r5 真实 overlap 型 S3，源码插桩 env_emit）做实但未改分**（2026-07-01）：`ChFi3d_Builder_0.cxx::StripeEdgeInter` 把入参 `TopOpeBRepDS_DataStructure& /*DStr*/` 具名化，在 `throw` 前经 `OCCT_DEBUG_SSI_OUT` 门控 `BRepTools::Write` 落盘两 blend 面（纯加法、无环境变量时行为不变）；`_ssi_discriminate` 按 `spec["method"]` 分派 `env_emit`（免 LLDB，`reproduce` 时置环境变量→读回 brep→ssi_probe）。**box-r5 的 S3 判别从"untestable"→"fired"**（真实 blend 面：两同轴 R5 圆柱 0.0° section=0 → s3_signature=true）。与 WP1 同理——机制**证据质量**升（S3 从"没法测"到"真实 fired，非 fixture"），但 scorer 机制\*维仍是 `localization_depth` 代理、定位仍 0.70（entity 命名不受益，见上"box"逐 case），故分值不变、tool-call 8→9。这条把 box-r5 从"S3 只能 fixture 替身"升级为"overlap 型 S3 的真实机制现场"，三腿全实。
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
| algorithmic_overflow | 1 | 0.70 | 1.00 | 0.20 | 携带 | 0.70 | 8.0 | ~1.8（replay） |
| geometric_curvature | 1 | 1.00 | 1.00 | 0.50 | 携带 | 0.70 | 8.0 | ~1.8（replay） |
| geometric_near_tangent | 2 | 1.00 | 1.00 | 0.50 | 携带 | 0.70 | 9.0 | ~2.3（replay） |
| 其它(无三态类)·false-green | 1 | 0.40 | n/a | 0.50 | 0.00 | 0.75 | 2.0 | (branch B，不进 decide) |
| **全集** | **6** | **0.78** | **1.00** | **0.42** | — | **0.71** | **6.3** | ~1.5（replay；real 含决策延迟 ~26） |

> 上表 tool-call/wall 为 2026-06-29 replay 重跑（含 A7 WP1+WP3）。WP1/WP3 的 capture/perturb_tolerance 是**决策之后的确定性合成**（不在 decide 接缝），录制决策不变 → replay 照常复现。

弃权/校准：correct_abstain=1 / wrong_abstain=1 / correct_commit=4 / false_commit=0；abstention precision=0.50。

### A/B 结论（rule vs LLM）

| 维度 | rule | LLM | 差 |
| --- | --- | --- | --- |
| 定位（全集） | 0.78 | 0.78 | **0** |
| 失效分类 | 1.00 | 1.00 | 0 |
| abstention precision | 0.50 | 0.50 | 0 |
| false_commit | 0 | 0 | 0 |
| 平均 tool-call | 6.50 | 6.33 | **≈0**（±0.17＝near-tangent S3 capture 路径的条件 ToolResult，决策后合成，非决策层差） |
| 平均 wall_s | 2.4 | ~26（real）/ 1.5（replay） | LLM 决策延迟 ~17× |

> tool-call 数 2026-06-29 含 A7 WP1+WP3（4.83→~6.4）；两臂仍≈持平——A7 的增量是确定性合成（capture 机制证据 + perturb_tolerance 互斥反事实），不在决策臂，故 rule/LLM 同样上升、A/B 结论不变。

**LLM 各质量维 + tool-call 与规则版逐位持平,只慢在决策延迟。** 诚实解读:

- ✅ **印证"模型只在决策点、其余确定性"**:把决策臂从 rule 换成 LLM,正确性一字不变——质量由确定性工具 + 确定性结论合成扛住,LLM 只动"跑哪个判别器/何时收"。换 policy 不破坏任何东西,这正是分层的意义。
- LLM **独立**跑了 S0/S2/S3 全候选(录制决策含 run S0 / run S2 / run S3 / conclude),与 rule 同序穷尽 → 同 tool-call、同结论。**没找到效率增量**:3 候选决策表小、结论合成 order-independent,"跑全候选"已是最优,没有可省的判别器。
- **wedge-thin 的 wrong_abstain 两版都没救**:它是**探针分辨率极限**(可行半径 <0.002 探针下限),不是决策-policy 能解的——任何 policy 面对的都是"候选全 ruled_out"。要救得换更细的探针/领域推理工具,不是换决策臂。这是个精确的归因:**A/B 平手不代表 LLM 没用,而是这批 case 的剩余差距在工具层不在决策层。**

> 复现:`bash agent/eval/eval.sh`（rule）；`AGENT_DECIDE_BACKEND=replay AGENT_DECIDE_RECORD=agent/eval/llm_decisions bash agent/eval/eval.sh --policy llm`（LLM，离线零计费）。重录真决策:去掉 `AGENT_DECIDE_BACKEND=replay`（走 claude_cli，需 Claude Code 鉴权）。
>
> 难度分层将随 case 扩充加维（凹/凸 × 单边/链/顶点 × 定/变半径，G21）。当前按 failure_class + clean + 其它分层。

---

## 2026-07-02 更新：Parasolid 对照第一轮（P0.1/P1.1/P1.2/P2.1，11 case + 失效四态）

> 变更：① **+4 真实 STEP case**（`E2-thinbar-overlap`/`E3-thinplate-face-overflow`/`E5-boss-face-overflow`/`E4-groove-false-green`，资产 `cases/models/`，Parasolid Blending 卷例子逐一隔离实跑验证）；② **失效三态 → 四态**：新增 `face_overflow`（单边单带溢出，`_classify_s2_failure` 按 blend 边数二分——修掉"单边 case 谎称两相邻带重叠"的假机制）；③ runner 接 `agent_run.edges`（原漏传）；④ reproduce 信号退出归 `kernel_crash`（不动 eval 数字）。来源与执行细节见 `../../docs/fillet-para-study-and-agent-gap-plan.md` §5。

### rule 臂（11 case）

| 层 | n | 定位 | 失效分类 | 机制* | 反事实* | 校准 | 平均 tool-call | 平均 wall_s |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| clean/abstain | 1 | n/a | n/a | n/a | n/a | n/a | 2.0 | ~0.3 |
| algorithmic_overflow | **3** | **0.90** | 1.00 | 0.20 | 携带 | 0.72 | 6.0 | ~1.4 |
| **face_overflow（新层）** | **2** | **1.00** | **1.00** | 0.20 | 携带 | 0.70 | 8.0 | ~1.8 |
| geometric_curvature | 1 | 1.00 | 1.00 | 0.50 | 携带 | 0.70 | 8.0 | ~1.8 |
| geometric_near_tangent | 2 | 1.00¹ | 1.00 | 0.50 | 携带 | 0.70 | 9.5 | ~4.7 |
| 其它(无三态类)·false-green | **2** | **0.70²** | n/a | 0.35 | 0.00 | 0.70 | 2.0 | ~0.3 |
| **全集** | **11** | **0.90** | **1.00** | 0.30 | — | **0.71** | 6.09 | ~1.8 |

¹ 同前：均值只算承诺 case（wedge-sliver 1.00），wedge-thin-abstain 弃权分账。
² false-green 层现 n=2：**真实模型 `E4-groove-false-green` 1.00**（凹槽 r=15，IsDone=true 但 BRepCheck 1 invalid_subshape → 根 S6 全中，无需 BOP）+ 合成 `thinplate-false-green` 0.40（症状-only，未回溯 S2 根，已知未解）。

**弃权/校准（集合量）**：correct_abstain=1 / wrong_abstain=1 / correct_commit=9 / **false_commit=0**；abstention precision=0.50（同前，wedge-thin 探针分辨率极限未动）。

**回归核对**：原 7 case 各维逐位不变（box-r5 定位 0.70、s3-fixture 1.00、thinplate 0.40 …）——新增 case 纯增量，无既有 case 漂移。

### LLM replay 臂（11 case，零重录）

**质量维与 rule 逐位持平**（定位 0.90 / 失效分类 1.00 / abstention 0.50 / false_commit 0）。关键发现：**决策录制按 state 签名（playbook 节点+已跑候选裁定）键控、非按 case**——新 4 case 走相同决策轨迹（同节点、同候选序）直接命中已录签名，**零重录零计费跑通**。差异仅 wall_s（新 STEP case 读盘+冷启动略慢）与个别 tool-call ±1（capture 条件路径，决策后合成，非决策层差）。

> 复现：`bash agent/eval/eval.sh`（rule）；`AGENT_DECIDE_BACKEND=replay AGENT_DECIDE_RECORD=$PWD/agent/eval/llm_decisions bash agent/eval/eval.sh --policy llm`（LLM 离线；首跑冷启动可 >2min）。

---

## 2026-07-02② 更新：路径 A 免埋点广度收尾（P1.3 + P2.2）

> 变更：① **P1.3** triage 四字段落地（convexity 角占率探针 / short_edges / sliver_faces / tolerance_outliers）——**只报告不进判别**，判别量（min_dihedral/curv）逐位不变；② **P2.2** playbook 加 **S4 顶点候选**（`vertex_probe`，Parasolid vertex_c 构型判据）→ 每个 playbook 路径 case **tool-call +1**（S4 判别真跑，box 全边/邻边构型均 ruled_out）。

### 质量维回归（11 case，rule 臂）

**全部质量维与 2026-07-02① 逐位一致**：定位全集 0.90 / 失效分类 1.00 / abstention 0.50 / false_commit 0 / box-r5 0.70。唯一漂移是登记过的 tool-call：全集均值 6.09→**6.64**（playbook 路径 +1：E2/E3/E5/pocket 8→9、box-r5 9→10、wedge-sliver 10→11；wedge-thin 仍 9——triage harness 无 `wedge-thin` builder → vertex_probe 诚实 untestable 不发工具，预先存在的 builder 不对称，非回归）。

### S4 现场狩猎——诚实负结果（P2.2 Step3）

**8 族简单解析构型未获 S4-proximate NotDone**：box 邻边对（3 种共享面变体；r<10 全成，r≥10 死于 **S2 `StartSol` Builder_2.cxx:944**——LLDB 实测，非 corner）、cube 邻边对（≤9.5 全成）、**金字塔 apex 2-of-4（邻/对——Parasolid §77.2.1 明文禁止的 vertex_c 构型，OCCT 全部收敛！）**、L 型凹凸混合 two-corner、薄板短第三边 corner、凹 notch 2-of-3 凹边（全成）。WP2 记录的 `PerformOneCorner Builder_C1:999` anchor 未复现（确切几何失传）。**不造假 GT case**；S4 eval 层留空待真实构型。正向能力发现：OCCT 顶点收敛比 Parasolid 声明的约束更能打。详见 `loop/test_investigate_vertex.py` 文档。

### LLM replay 臂语义漂移（诚实标注，待重录）

playbook 节点加 S4 候选后，llm replay 忠实重放**旧轨迹**：录制的 conclude 决策在 3 候选后触发（state 签名按已跑裁定匹配、命中旧录制）→ **llm replay 臂不跑 S4 判别**（box-r5 llm tool=8 vs rule 10），质量维仍逐位一致（S4 本会 ruled_out，不影响结论）。**重录**（`claude_cli`，有计费）可消除该语义差；在重录前 A/B 的 tool-call 维不可比，质量维可比。

> 复现：`bash agent/eval/eval.sh`；测试 `python -m agent.loop.test_investigate_vertex`（含纯函数 + box 回归断言）。
