# Chamfer 适配器 —— 转移账本（P1a：证明这是 harness，不是"圆角工具"）

> 目的：把"本体（S0–S6 失效阶段 + decide 接缝 + scorer + runner）是**领域无关**的"从**断言**变成
> **实证**。做法是落第二个几何域（chamfer/倒角），复用同一套投诊/打分/跑批结构，然后**诚实列清**
> 哪些 1:1 转移、哪些域特定、哪些"崩"（不干净映射）。所有 chamfer 失效行为都用 FreeCADCmd 1.2.0
> **实测**过，不是空想。

## 一句话结论

Chamfer 走**同一个** `investigate → scorer → runner`，只经**一个 `op` 轴** + **一张新决策表**接入；
51 个参数化 chamfer case 的五维打分与其 fillet 对偶**逐层同构**（溢出/近切 → 1.00/1.00/cf 1.00；
凹壁假绿 → 0.40 症状级），false_commit=0。域特定的只有三处：几何驱动分支、chamfer 决策表、溢出阈值
语义。另有 3 处**诚实记录的不干净映射**（见下），以及一个**方向性轴**——fillet 没有、正是 C4 证伪靶。

## 接入方式：`op` 轴，不 fork

`agent_run` 加 `"op": "chamfer"`（缺省 → `"fillet"` → 全部 13 手工 case + fillet 参数化套件**逐位不变**）。
`op` 沿 `edges` 的同一条链透传：`investigate → reproduce(makeFillet/makeChamfer) + query_playbook(选
{op}-failures 表)`。判别器（triage 近切/曲率、ssi、vertex、falsegreen）**本体 op-无关、原样复用**，
只有 reproduce 调用带 op。radius 参数即倒角距离 d（不改名，避免调用方 churn）。

## 转移账本

### ✅ 1:1 转移（零改判别器本体）

| 组件 | 为什么 op-无关 |
| --- | --- |
| S0–S6 失效本体 | 阶段是几何流水线的结构，不绑 blend 类型 |
| `decide(state)` 接缝 + `decide_rule`/`decide_llm` | 对候选抽象操作，不看 op（节点 id 已在签名里） |
| scorer 五维 + 弃权四态 + 分层聚合 | 打分只看 Conclusion 结构，op-无关 |
| runner（并行/沙箱/预算/隔离/`_layer_of`） | `family` 字段天然把 chamfer 族分层，`run_case` 透传 `agent_run.op` |
| `contracts`（Stage/CausalHypothesis/GroundTruth/RunEnd） | 全 op-无关 |
| **triage 近切+曲率**（S2 四态判别） | `min_dihedral_deg`/`min_support_curv_radius` 是**输入几何**属性，与 fillet/chamfer 无关 → `geometric_near_tangent`/`geometric_curvature` 对 chamfer 逐字适用 |
| `ssi_probe`（S3）、`vertex_probe`（S4）、`falsegreen_probe` | 分别对两张面求交 / 顶点拓扑 / 结果 brep 分析，均不重跑操作 → op-无关 |
| **反事实 `lower_radius` 阶梯 →（复用为）`lower_distance`** | 意外之喜：倒角距离够像半径，互斥反事实对 `_probe_feasible_bound`/`_counterfactual_verdict`/`_CF_CLAIMED_ROOT` **逐字复用**（S2/S3 判别不变） |

### 🔶 域特定（chamfer 专属）

| 处 | fillet | chamfer | 落点 |
| --- | --- | --- | --- |
| 几何驱动 | `makeFillet(r,edges)` | `makeChamfer(d,edges)` / `makeChamfer(d1,d2,edges)` | `_fillet_harness.py` 一个 `REPRO_OP` 分支（~10 行，builder 复用） |
| 决策表 | `fillet-failures.json` | `chamfer-failures.json`（同构：同 S0–S4 候选、同 tool 名，换 cause/fix/truth_anchor） | 新文件 1 张 |
| 溢出物理 | 滚球容纳 `r>凹曲率` | 平斜面盖过面宽 `2·d>面宽` | 阈值语义（triage 复用、prose 改） |
| 溢出→假绿边界 | box `r=minEdge/2` 恰翻假绿（窄缝） | box `d≥minEdge/2` 是**宽而稳的 NotDone 带**（更干净） | gen_cases margin |

### ❌ 崩 / 不干净映射（诚实记录，不粉饰）

1. **重叠假绿翻面**：fillet 薄板重叠 → 假绿（thinplate）；chamfer 薄板重叠 → **硬 NotDone**。chamfer
   的假绿**搬到了凹/曲面支撑**（实测 pocketp 凹壁 `d∈[RC·1.1, RC·1.7]` → is_done 但无效）。假绿这个
   **阶段**转移了，但**触发它的 builder** 变了（凹壁而非薄板）。
2. **凹壁假绿定位落兜底**：chamfer 凹壁假绿的支撑是**解析圆柱**（非 B-spline），`fg_support_probe` 查
   参数面 → ruled_out；也无中段带-带自交 → `fg_selfint_mid` 不 fire → 落 `_falsegreen_fallback_hyp`
   → root **S6**（检出点），而非干净的 S3。铁律仍成立（check_valid 抓得住、绝不信 IsDone），但**根定位
   是免埋点的域特定缺口**（GT true_chain=`[S2,S6]`、定位 0.40 症状级——与 box_false_green 同款诚实下限）。
3. **双距方向性轴无 fillet 对偶**：`makeChamfer(d1,d2)` 的 d1≠d2 是 fillet 单半径没有的自由度 → 新增
   `asymmetric_distance_probe` 判别器 + 新反事实标签（`S2-directional`），fillet 的 scorer/`_CF_CLAIMED_ROOT`
   不建模它。这既是"域特定扩展"，也是 C4 证伪靶（见下）。

## 打分实证（rule 臂，chamfer 族 vs fillet 对偶）

| chamfer 族 | n | 定位 | 失效分类 | 反事实 | 弃权 | 对偶 fillet 族（同分） |
| --- | --- | --- | --- | --- | --- | --- |
| chamfer_overflow | 18 | 1.00 | 1.00 | 1.00 | ✓结论 | box overflow（S2 algorithmic_overflow） |
| chamfer_near_tangent | 15 | 1.00 | 1.00 | 1.00 | ✓结论 | geometric_near_tangent |
| chamfer_false_green | 8 | 0.40 | n/a | n/a | ✓结论 | box_false_green（症状级 0.40） |
| chamfer_clean | 10 | n/a | n/a | n/a | ✓弃权 | clean（correct_abstain，false_commit 0） |

全 166-case 套件（115 fillet + 51 chamfer）：定位 0.78 / 失效分类 1.00 / 反事实 1.00 / false_commit 0。
**chamfer 族与 fillet 对偶逐层同分**——这就是"同一套投诊/打分结构、只换 op + 一张表"的实证。

> 复现：`python -m agent.eval.runner --suite parametric`（分层报里 chamfer_* 独立成层）；
> `python -m agent.eval.test_gen_cases`（chamfer 各族第一性不变量）。

## C4 证伪实验（LLM 能不能赢**质量**，不只赢成本）

**命题**：fillet 根因 order-independent（任一 distal 候选 fired 即定根、与顺序无关）→ rule 顺序穷尽近
最优、LLM 只能赢成本（早停 -6%）。证伪靶：更大 / 非 order-independent 的决策空间。

**chamfer 的双距方向性轴正是那个空间**。实测（box 6×40×30 一条棱，两侧 6-宽 / 40-宽支撑面）：
- 对称 `d=6.0` → NotDone；`radius_probe`（对称降距）一命中即定 **S2 溢出（stage 级）**，指不出哪张面约束。
- 非对称 `d1=8,d2=3` → 恢复；`d1=3,d2=8` → 仍崩 → 约束是**进入 6-宽面的那个距离**（方向性、**entity 级**）。

**order-dependence（C4 的牙齿）**：拿到方向性根**必须多跑一步** `asymmetric_distance_probe`——固定
distal→proximate 序的 rule 臂 S2 一 fired 就早停、够不到；一个"看几何不对称 → 加跑方向探针"的推理策略
才够得到 entity 级。**这是 LLM 臂可能赢质量的窄口子。**

**诚实结论（窄证伪，非全盘推翻）**：方向性族上，推理策略可拿到 rule 拿不到的 entity 深度（质量增量）；
但其余 chamfer 族（溢出/近切/曲率）实测**仍 order-independent** → 对它们 C4 死胡同**依旧成立**。即 C4 被
**窄窄地**证伪、不是推翻——"能识别死胡同在哪、也能识别哪里能翻案"本身就是工程判断。**未做**：完整
LLM claude_cli A/B（下一步；本 demo 只证明了方向性根真实存在 + stage→entity 的定位增量机制）。

> 复现：`python -m agent.demo.chamfer_directional`（PASS = directional_root 指认约束面）。
