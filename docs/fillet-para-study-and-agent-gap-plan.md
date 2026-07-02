# 圆角研究（Parasolid 参考手册）→ STEP 示例 → 问题分类 → Agent 补足计划

> 来源文档：`occt/OCCT/docs/reference/para.pdf`（**Parasolid** 内核《Functional Description》参考手册，1992 页；放在 OCCT 目录下，内容为 Parasolid）。<br>
> 圆角部分主体在 **Volume 11「Blending」（p.1241–1462）**，另有实操示例 §10.4.5（p.137）。<br>
> 关联：[occ-fillet-debug-agent-architecture.md](occ-fillet-debug-agent-architecture.md)、[../agent/playbook/blend-failure-ontology.md](../agent/playbook/blend-failure-ontology.md)、[../agent/cases/models/manifest.json](../agent/cases/models/manifest.json)。<br>
> 状态：研究基线 + 可执行 STEP 资产 + 补足路线（2026-07）。

本文回答 goal 的四问：**① 整理文档圆角内容；② 按例子生成对应 STEP；③ 圆角可能遇到的问题；④ 研判 agent 不足并写补足计划。**

关键立场：**para.pdf 是 Parasolid 的手册，不是 OCCT 的。** 但圆角几何在内核间高度同构（滚球容纳、偏移面求脊、面面求交、顶点收敛），Parasolid 的失效分类学（Ch77/78 约 25 个 fault token）是目前能拿到的**最完整的圆角失效真理表**，正好用来审计 agent 那套只有 3 类的分类学缺什么。因此本文把 Parasolid 的模型逐条映射到 OCCT `ChFi3d` 与 agent 的 S0–S6 本体，而非照搬 API。

---

## 第一部分 · 文档圆角内容整理

### 1.1 三种 blend 与两个阶段

Parasolid 把圆角叫 **blend**，分三形态（§72.1）：

| 形态 | OCCT 对应 | 说明 |
|---|---|---|
| **Edge blending**（边圆角） | `BRepFilletAPI_MakeFillet` / `ChFi3d` | 沿一条/一串边加面，通常与相邻面切连续 |
| **Face-face blending**（两面之间） | OCCT 无直接等价（需手工 offset+intersect） | 在两组面之间生成 blend，不依赖已有边 |
| **Three-face blending**（三面之间） | 同上 | face-face 的特例，三组面收敛 |

Edge blend 走**两段式**（§72.2）：先 **set**（`PK_EDGE_set_blend_*` 把 blend 属性挂到边上，"unfixed"）再 **fix**（`PK_BODY_fix_blends` 真正换成面）。**OCCT 是单段**——`MakeFillet::Add(r, edge)` + `Build()` 一步到位，没有独立的"设/固"分离。这个差异在补足计划里有用（Parasolid 能在 fix 前查询/回退，OCCT 只能事后从异常回溯）。

### 1.2 边圆角的三种类型 × 横截面形状

**类型**（§72.3）：

- **Rolling-ball（滚球，等半径）** — `PK_EDGE_set_blend_constant`；一个球沿两面滚，半径即球半径。**这是 OCCT `MakeFillet` 默认、也是 agent 唯一覆盖的类型。**
- **Chamfer（倒角，线性截面）** — `PK_EDGE_set_blend_chamfer/chain`；分 face-offset 与 apex-range 两法。OCCT 是独立算法 `BRepFilletAPI_MakeChamfer`（`ChFi3d` 共享底座）。
- **Variable rolling-ball（变半径滚球）** — `PK_EDGE_set_blend_chain`；半径沿边链变化，可圆/锥/曲率连续截面。OCCT 支持 `MakeFillet::Add(r1,r2,edge)` 与 law。

**横截面**（§73.2.1.1）：`conic`（默认，rho 控制饱满度）、`g2`（曲率连续/G2）、`chamfer`（线性）。**rho 过大**会让截面相对底面太平 → `rho_too_large`（见 §77.3.7）。

### 1.3 核心几何理论（这段最重要，直接映射 OCCT 失效）

> **滚球 blend 面 = 一个圆沿脊线（spine curve）扫掠。脊线 = 两个相邻面各自按半径 r 偏移后的偏移面的交线。**（§77.3.1）

由此推出全部主要失效根源——**这正是 OCCT `PerformSurf`/`StripeEdgeInter` 崩溃的第一性原因**：

1. **两偏移面不相交，或交出的脊线太短** → 无法定义 blend 面（`bsurf_c` / `face_c`）。
2. **参数面（B-surface）的偏移天然有界** → 偏移面可能压根不相交或脊线不够长（`bsurf_c`）。**纯解析面（平面/圆柱）不受此限——agent 目前只测解析面，恰好回避了这一整类。**
3. **滚球半径 > 它要滚过的面的曲率半径** → 球"卡住"塞不进（`face_c`，Fig77-7）。= agent 的 `geometric_curvature`。
4. **偏移面自交** → blend 面自交（`self_int_c`）。
5. **blend 溢出到相邻面**（overflow，见 §1.4）→ 必须被约束/裁剪，否则失败。
6. **顶点太复杂** → 4+ 边且 ≥2 边要圆角，收敛不了（`vertex_c`）。

### 1.4 Overflow（溢出）——一整个 OCCT/agent 都没有显式建模的概念（Ch74）

**当 blend 按其半径定义会离开相邻面的边界时，就发生 overflow。** 这不是错误，是需要处理的构型。分内部/外部（internal/external），处理策略四选一，Parasolid 按优先级 **smooth → cliff → notch** 自动尝试：

| overflow 类型 | 含义 |
|---|---|
| **smooth** | 溢出区用相邻面上的等效 blend 替换（全部 overflow bound/edge 都光滑时）|
| **cliff / cliff-end** | 溢出区用一串 cliff-edge blend 环绕 |
| **notch** | blend 面不变，靠延伸/裁剪相邻面在凹槽处修边 |

**当没有任何被允许的 overflow 类型能成立 → blend 失败。** OCCT 的 `ChFi3d` 内部其实**有** overflow 处理逻辑（下面 E5 实测：boss 上的溢出被 OCCT 处理到 r≤~15 才失败），但 agent 的本体（S0–S6）里**完全没有 overflow 这个维度**——它把所有"离开面/撞邻面"都塞进 S3 overlap 或笼统 NotDone。这是最大的概念缺口。

### 1.5 限制与规则（§72.5–72.6）

- 4 边顶点上圆两条边：只有当另两条边光滑、或两条边不共面且同凸性时才行。
- 三边顶点圆两条：任两条同凸性可圆；一条异凸时那条必须等半径；**异凸边不能用 chamfer**。
- 三边顶点全圆：会加一张额外面抹平顶点。
- **可行性非单调**：小半径也会因容差/退化失败；不要假设"半径越小越容易"。（agent 的 ontology 已明确记这条 ✅）
- Facet（网格）体：edge blend 部分支持；face-face/three-face 不支持。

---

## 第二部分 · 按文档例子生成的 STEP（已逐一实跑验证）

产物目录：**`agent/cases/models/`**，含 6 个 STEP + `manifest.json`。全部由本地 **FreeCADCmd（OCCT 7.8.1，debug）** 构造并 `exportStep`，且**每个都实际跑了一次 `Part.makeFillet`**，把成功/失败结果写进 manifest 的 `verified_fillet`——即"这个 STEP 确实复现了它声称的行为"。`target_edges_1based` = FreeCAD GUI 里的 `EdgeN`，可直接喂给 agent 的 `--edges N`（G26 已支持 `step:` 前缀）。

| STEP | Parasolid 出处 | 目标边·半径 | 实跑结果 | 复现的失效 / 用途 |
|---|---|---|---|---|
| **E1_swept_block_r5** | §10.4.5 实操例（拉伸块+单边定值圆角）| 1 竖边 · r=5 | ✅ SUCCESS(7面) | 单边成功 sanity（agent 应正确 abstain）|
| **E2_thinbar_overlap_r3** | §77.4 Overlapping blends | 4 长边 · r=3 | ❌ NotDone | **algorithmic_overflow**：相邻带重叠（=OCCT `StripeEdgeInter` "too big radiuses"）；比 box-r5 更小的最小复现 |
| **E3_thinplate_loop_overflow_r5** | §77.3.4 Blend overlaps edge loop | 1 竖边 · r=5 | ❌ NotDone | **NEW**：blend 大到伸出实体（loop 溢出）——agent 本体无此类 |
| **E4_concave_groove_r8** | §77.3.6 / Fig77-7 滚球卡住 | 凹 R6 槽边(#8) · r=8 | ✅ SUCCESS；**r=15/20 → 假绿(IsDone 但 invalid)；r≥30 → NotDone** | **P1.2 假绿**：真实模型上 reproduce=ok 但 check_valid=invalid（见下方修正）|
| **E5_overflow_boss_r20** | Ch74 / Fig74-9 溢出到 boss | 顶边(#6) · r=20 | ❌ NotDone（但 r≤~15 被 OCCT 处理成功）| **NEW**：overflow 到邻面（smooth/cliff/notch 现象）——agent 本体无此维 |
| **E6_wedge_thin_r5** | §72.5 非正交面 spine 限制 | 楔脊边 · r=5 | ❌ NotDone | 楔体（非正交）overflow 变体。**诚实标注**：taper 0.2 vs 0.05 结果相同 → 由 4mm 厚度主导，**不是**干净的 near-tangent |

**诚实备注（本项目"绝不假绿"准则）**：
- E4/E5/E6 的初始半径（第一次生成时的 r=9/r=6/r=3）**没有**触发预期失败，是经过半径扫描才定到真正触发失败的值——过程与阴性结果都记在 manifest。
- **⚠ E4"崩溃"是假象，已诚实修正（推进阶段发现）**：exit-139 段错误只在**同一进程连续跑多个半径累积**时出现；**隔离进程**（agent 实际路径 `Part.Shape().read()`+`makeFillet`）里 E4 边#8 **r=15/20 = 假绿（IsDone=true 但 isValid()=False）、r≥30 = 干净 NotDone**，不崩溃。故 E4 从"崩溃鲁棒性 fixture"改判为 **P1.2 假绿 fixture**（更有价值：真实模型上验证"禁用裸 IsDone"）。P1.1 崩溃兜底仍做了（reproduce 归 `kernel_crash`），但用**合成信号退出**验收，不再依赖 E4 自然崩溃（诚实负结果）。
- **⚠ 边号修正**：STEP 导出+重读后边号会变（`Part.Shape().read()` 重新编号）——E4 目标边 7→**8**、E5 7→**6**。manifest 的 `target_edges_1based` 已用**读回后**的边号（agent `--edges` 取这个）。
- **E6 不是 near-tangent**：改 taper 不改阈值，证明是厚度（4mm）主导的溢出，与 E3 同类。真正的 near-tangent 复现见 agent 已有的 `wedge-sliver`（1.72° 二面角，LLDB 实证）。
- 真正的 **geometric_curvature / geometric_near_tangent** 干净复现分别已由 agent 现有 case `pocket-blind-hole`、`wedge-sliver` 覆盖，故本批不重复造，而是补 agent **没有**的类型（overlap 最小化、loop 溢出、邻面 overflow、崩溃鲁棒性）。

跑法（示例）：
```bash
python -m agent.loop.investigate "step:agent/cases/models/E2_thinbar_overlap_r3.step" 3.0 --edges 1,3,5,7 --policy rule
python -m agent.loop.investigate "step:agent/cases/models/E3_thinplate_loop_overflow_r5.step" 5.0 --edges 1
```

---

## 第三部分 · 圆角可能遇到的问题（失效分类，Parasolid → OCCT → agent 阶段）

下表把 Parasolid 边圆角错误码（§77）与 face-face 码（§78）逐条落到 **OCCT 症状** 和 **agent S0–S6 阶段**。**加粗行 = agent 当前本体/case/probe 未覆盖的缺口。**

### 3.1 严重错误（该边永不可圆）

| Parasolid fault | 含义 | OCCT 症状 | agent 阶段 | 覆盖? |
|---|---|---|---|---|
| `vertex_c` | 顶点太复杂（4+ 边，≥2 边圆角）| `PerformThreeCorner`/`MoreThreeCorner` 失败 | **S4** | **无 case/probe** |
| `unknown_c` | 内部数值算法意外失败，无法分类 | 笼统 `StdFail_NotDone` | 未知 | 部分（触发调研，但无深探）|

### 3.2 一般构型错误（改半径/改邻边/去邻边可救）

| Parasolid fault | 含义 | OCCT 症状 | agent 阶段 | 覆盖? |
|---|---|---|---|---|
| `bsurf_c` | 需延伸 B-surface 终结 blend，或**参数面偏移有界→脊线不够长/不相交** | `PerformSurf` 求交失败 | **S2/S3** | **无（agent 只测解析面）** |
| `range_c` | 某边 range 与相邻已圆边不一致（如相切第三边）| 多边不同半径交互失败 | **S1/S3** | **无（case 都是单半径）** |
| `edge_c` | 三边顶点圆两条时构型非法（异凸+变半径）| corner 失败 | **S4** | **无** |
| `loop_c` | **blend 完全盖过 edge loop / 伸出实体** | NotDone（见 E3）| **S3?/新维** | **无（本体无 loop 溢出）** |
| `overlap_edge_c` | blend 溢出一条未圆的边，邻面无法延伸去接 | NotDone | **overflow 维** | **无** |
| `face_c` | range 太大找不到边终结边界；或**滚球半径>面曲率半径→卡住** | NotDone / `StartSol` echec | **S2** | ✅ `geometric_curvature`（`radius_probe`）|
| `rho_too_large_c` | conic rho 太大，截面相对底面太平 | 变半径/conic 路径 | **S2** | **无（只做等半径）** |
| `other_edge_c` | 同面另一条边的非法 blend 使本边检查无法完成 | 多边批量失败 | 跨边 | **无（多为单边诊断）** |

### 3.3 重叠 blend（overlapping，可换选项或分次 fix 救）

| Parasolid fault | 含义 | OCCT 症状 | agent 阶段 | 覆盖? |
|---|---|---|---|---|
| `overlap_c` / `overlap_end_c` / `end_c` | 两条非相邻 blend 链重叠，一次 fix 合并不了 | **`StripeEdgeInter` "too big radiuses"** | **S3** | ✅ **旗舰**（`ssi_probe`，box-r5/E2）|
| `edge_intsec_c` | blend 末端边界撞上未圆的边 | corner/端部失败 | **S3/S4** | 部分 |

### 3.4 fix 阶段（默认关，需显式开检查）

| Parasolid fault | 含义 | OCCT 对应 | agent 阶段 | 覆盖? |
|---|---|---|---|---|
| `face_face_c` | blend 造成面面不一致 | 结果 `BRepCheck`/BOP self-int | **S6** | 部分（`check_valid` 有 BRepCheck，缺 BOP self-int）|
| `self_int_c` | blend 面自交 | `BOPAlgo_CheckerSI` | **S6** | **缺 self-int 检测** |

### 3.5 Face-face / Three-face 专有（§78，OCCT 无直接等价，agent 全无）

`curved_c`（面太弯 blend 塞不下）、`small_c`/`large_c`（range 太小/大，**且给出建议值**）、`sheet_clash_c`/`wall_clash_c`（blend sheet/wall 相撞）、`bad_spine_c`、`asymmetric_c`、`plane_insuff_c`（裁剪面不足）……**这一整卷 agent 没有对应**，因为 OCCT 本身无 face-face blend；属于长期非目标。

### 3.6 OCCT 特有、Parasolid 表里没有的失效（本批实测新增）

- **进程硬崩溃 / 段错误（exit 139）**：OCCT debug 在极端半径下**可能**崩溃，但（推进阶段实测）**非隔离可复现**——只在同进程连续多半径累积时出现，agent 的隔离子进程路径里不复现。仍加了兜底：`reproduce` 把信号退出归 `kernel_crash`（P1.1，合成信号验收）。
- **`IsDone()=true` 但几何非法（假绿）**：架构 §24 + agent `thinplate-false-green` 已覆盖；本次再加**真实模型** fixture `E4-groove-false-green`（r=15，check_valid 拦住）✅——这是 Parasolid 用"默认关检查"回避、而 OCCT 会静默产出的最危险类。

---

## 第四部分 · 研判 Agent 不足 + 补足计划

### 4.1 Agent 现状（据 `agent/` 实读）

- **本体**：S0–S6 阶段（内核无关，设计良好）。
- **可执行分类**：只有 **1 条 playbook 签名**（`fillet-notdone-overflow`）+ **3 个 failure_class**（`geometric_near_tangent` / `geometric_curvature` / `algorithmic_overflow`）。
- **case**：7 个，全为 box/wedge/pocket/thinplate 图元，**全部等半径滚球、单边或全边**。
- **probe**：`triage_input`(二面角)、`radius_probe`、`ssi_probe`、`capture`(lldb / env_emit)。
- **三腿验证**：localize → mechanism → counterfactual（互斥靶向修法判别根因），设计扎实。
- **诚实机制**：`untestable` / `abstain` / 无假绿——非常好，是核心资产，不能为覆盖率牺牲。

### 4.2 核心研判：**本体够宽，可执行覆盖太窄**

拿 Parasolid ~25 fault token 对照，agent 的 3 类分类学只覆盖了**「等半径滚球单/多边、正交解析面、overlap/curvature/near-tangent」这一小格**。缺口按重要性：

| # | 缺口 | 证据 | 影响 |
|---|---|---|---|
| **G1** | **Overflow 维完全缺失**（smooth/cliff/notch，Ch74）| 本体 S0–S6 无 overflow；E5 实测 OCCT 有 overflow 处理 | 大量真实 blend 失败是溢出到邻面，agent 会误归 S3/笼统 NotDone |
| **G2** | **loop 溢出**（blend 伸出实体，`loop_c`）未建模 | E3 实测 NotDone | 误分类 |
| **G3** | **S4 顶点复杂度**无 case/probe（`vertex_c`/`edge_c`）| 本体有 S4 但无落地 | corner 类失败无法定位 |
| **G4** | **只测解析面**，B-surface 偏移有界一类（`bsurf_c`）完全没碰 | 所有 case 平面/圆柱 | 真实 CAD 大量含 B-spline 面，agent 盲区 |
| **G5** | **只做等半径滚球**：chamfer / 变半径 / conic-rho / G2 全无 | case 全等半径 | 类型覆盖 <20% |
| **G6** | **崩溃鲁棒性**：OCCT 段错误(exit139) 是否被 reproduce 当失效捕获，未验证 | E4 r≥15 | 可能挂起/漏报 |
| **G7** | **`check_valid` 缺 BOP self-int**（`self_int_c`/`face_face_c`）| 报告自述缺 BOPAlgo_CheckerSI | 假绿漏检 |
| **G8** | ~~WP5 的 OCCT 埋点是未提交工作树改动~~ ✅ 已解决（2026-07-02 核实：`c07ae703b7` 已在 fork `v7_8_1-fillet-debug` 且已推送） | 占位保留编号 | 无（bootstrap 可再生） |

### 4.3 补足计划（按性价比排序，小步可验证）

沿用架构文档"从两头往中间推 + 免埋点优先"的成本模型。每步给**可验证产物**。

#### P0（立即，纯配置/资产，本次已完成或半天内）
- **P0.1 落地本批 6 个 STEP 为回归 case** ✅（已生成，`agent/cases/models/`）。下一步：给 E2/E3/E5/E6 各写 `cases/*.json`（含 `agent_run` + `ground_truth`），进 eval 矩阵。
- **P0.2 固化 WP5 埋点（G8）** ✅ **已解决（2026-07-02 核实）**：`ChFi3d_Builder_0.cxx` 的 DStr 具名化 + `OCCT_DEBUG_SSI_OUT` 改动已提交并推送 fork `v7_8_1-fillet-debug`（`c07ae703b7 feat(ChFi3d): env-gated blend-face dump at StripeEdgeInter for SSI capture`），`occt/` 工作树干净——bootstrap 全新克隆即含埋点，box S3 复现可再生。

#### P1（免埋点，最高命中率——先把"输入/输出/崩溃"三头做厚）
- **P1.1 崩溃当失效（G6）**：确认 `reproduce` 用子进程隔离运行 FreeCADCmd，把 **退出码 139 / 信号** 归为 `infrastructure_failure` 或新 `S6/kernel_crash`，而不是挂起或误报 ok。用 **E4 r=15** 做验收 fixture。
- **P1.2 `check_valid` 补 BOP self-int（G7）**：接 `BOPAlgo_CheckerSI` + G1/切向检查，堵住 `IsDone=true` 假绿。用 `thinplate-false-green` + 一个自交 blend 验收。
- **P1.3 `triage_input` 补齐（承接报告 TODO）**：凹/凸分类、短边/sliver、容差分布、输入 `BRepCheck`——全部免埋点。

#### P2（新增失效维——把本体从 6 阶段扩成"阶段 × 现象"）
- **P2.1 Overflow 维（G1，最大缺口）**：在 ontology 增加 **overflow 现象轴**（smooth/cliff/notch/loop），新增 probe `overflow_probe`——免埋点判据：blend 目标边的 range 是否超出相邻面参数域 / 伸出实体包围盒。case：**E5、E3**。这是把 agent 从"OCCT-only 3 类"推向"Parasolid 级现象学"的关键一步。
- **P2.2 S4 顶点复杂度（G3）**：造 4 边顶点 / 三边异凸 case（可用 boolean 拼两块），新增 `vertex_probe`（数顶点边数 + 凸性混合），接 `PerformThreeCorner` 症状。
- **P2.3 loop 溢出分类（G2）**：`overflow_probe` 的子判据（blend 伸出实体）。case E3。

#### P3（扩类型 & 深埋点——长杆，依赖 occdbg/LLDB 前半管线）
- **P3.1 B-surface 支撑面（G4）**：造含 B-spline 面的 case（GUI 里 loft/填充导出 STEP），验证 `bsurf_c` 类"偏移有界脊线不足"。免埋点先判"支撑面是否参数面"。
- **P3.2 类型扩展（G5）**：chamfer（`MakeChamfer`）、变半径（`Add(r1,r2,e)`）各造 1 case，ontology 标 xs_shape/law 维。
- **P3.3 深埋点（承接 A8 / WP2 长杆）**：`SurfData`/`CommonPoint`/corner 级采集，攻 S2/S4 的 entity 级定位（当前 box S3 entity 召回止于 0，见 box-r5 备注）。

#### 验收锚点（每步都有真值 fixture）
| 步 | 验收 fixture | 判据 |
|---|---|---|
| P1.1 | E4 r=15 | 归 kernel_crash，不挂起 |
| P1.2 | thinplate-false-green + 新自交 case | self-int 被检出，不假绿 |
| P2.1 | E5, E3 | 归 overflow（notch/loop），非笼统 NotDone |
| P2.2 | 新 4 边顶点 case | 定位到 S4 |
| P3.1 | 新 B-spline 面 case | 识别 bsurf 类 |

### 4.4 一句话结论

> **Agent 的骨架（S0–S6 本体 + 三腿验证 + 诚实机制）是对的、可迁移的；短板在"可执行覆盖面"——只做了等半径滚球在正交解析面上的 overlap/curvature/near-tangent 一小格。** Parasolid 手册给出的完整失效表显示，最该补的三件事依次是：**① Overflow 现象维（含 loop 溢出）；② S4 顶点复杂度；③ 崩溃/自交的鲁棒兜底（免假绿）。** 本次已交付 6 个实跑验证的 STEP 资产作为这些补足步的真值锚点。

---

## 第五部分 · 补足计划执行进展（2026-07，每步可复现）

按第四部分计划推进，每步给**可复现验证命令**。全部从 repo 根运行。

### 基线（推进前）
```bash
bash agent/eval/eval.sh          # 7 case：全集定位 0.82 / 失效分类 1.00 / false_commit 0
```

### ✅ P0.1 — 6 个 STEP 落地为回归 case（含边号/结果修正）
- **产物**：`agent/cases/models/*.step` + `manifest.json`（读回边号 + 隔离实跑结果）；`cases/E2-thinbar-overlap.json`、`E3-thinplate-face-overflow.json`、`E5-boss-face-overflow.json`、`E4-groove-false-green.json`（含 GT 四元组）。
- **修正**：STEP 重读后边号变（E4 7→8、E5 7→6），已在 manifest 用读回边号；E4 从"崩溃"改判"假绿"（见第二部分诚实备注）。
- **接线**：`eval/runner.py` 补 `edges=run.get("edges")`（原来漏传，step case 无法指定边）。
- **复现**：`bash agent/eval/eval.sh` → 现 **11 case**，全集定位 **0.82→0.90**，false_commit 仍 **0**，box-r5 **0.70 不回归**。

### ✅ P2.1 — 新增 `face_overflow` 失效类（最大缺口 G1/G2）
- **改动**：`playbook/fillet-failures.json` 加 `face_overflow` 类；`loop/investigate.py::_classify_s2_failure` 的 else 分支按 blend 边数二分——**单边=`face_overflow`（单带 overflow，Parasolid loop_c）**，**≥2 边=`algorithmic_overflow`（两带重叠 StripeEdgeInter）**。
- **修的 bug**：改动前 E3/E5/E6（单边）被误判 `algorithmic_overflow` 并谎称"两相邻圆角面重叠"——单条 blend 边**不存在**相邻带，机制描述是假的。
- **复现**：`python -m agent.loop.test_investigate_overflow` → **ALL PASS**（box-r5/E2 保持 algorithmic，E3/E5/E6 转 face_overflow 且 cause 不再含"两相邻…重叠"）。

### ✅ P1.2 — 假绿在真实模型上被 check_valid 拦住（G7 部分）
- **发现**：E4 边#8 r=15 → reproduce `status=ok / is_done=true`（裸 IsDone 判成功），但 `check_valid` → `valid=false`（1 invalid_subshape）。**现有 BRepCheck 即抓到，无需 BOP**——G7 的 BOP-self-int 缺口比原判更窄（仅剩 BRepCheck 漏、BOP 才抓的面面自交）。
- **复现**：`bash agent/eval/eval.sh --case E4-groove-false-green` → 根 **S6** 定位 **1.00**（✓结论）。

### ✅ P1.1 — reproduce 区分内核崩溃 vs harness 无输出（G6）
- **改动**：`tools/reproduce.py` 把进程被信号打死（rc<0 或 ≥128）归 `phase="kernel_crash"`（→ investigate 分支 C infrastructure 兜底弃权），不再与"harness 逻辑没产出"混为 `phase="harness"`。
- **诚实边界**：OCCT 圆角自然崩溃**非隔离可复现**（同进程累积假象），故用**合成信号退出**验收，不碰运气触发真崩溃。
- **复现**：`python -m agent.tools.test_reproduce_crash` → **ALL PASS**（rc=-11/139→kernel_crash，rc=1→harness）。

### 回归
```bash
python -m agent.loop.test_investigate_cf      # ALL PASS
python -m agent.tools.test_playbook           # ALL PASS
python -m agent.tools.test_reproduce          # ALL PASS
```

### 尚未做（留后续，均有 fixture 就位）
- **P1.3** triage_input 补凹/凸·短边·容差·输入 BRepCheck（免埋点）。
- **P2.2** S4 顶点复杂度（需造 4 边顶点 case + vertex_probe）。
- **P2.3** loop 溢出细分（face_overflow 已含，可再分 loop vs neighbour）。
- **P3.x** B-surface 支撑面 / chamfer / 变半径 / 深埋点。
- ~~G8 WP5 OCCT 埋点固化~~ ✅ 已解决：改动已在 fork `v7_8_1-fillet-debug` 历史（`c07ae703b7`）且已推送。

---

## 附录 · 文档定位速查（para.pdf 页码）

| 主题 | 页 |
|---|---|
| §10.4.5 Add an edge blend（实操例）| 137 |
| Vol.11 Blending 总入口 | 1241 |
| Ch72 Edge Blending Overview（类型/限制/规则）| 1245 |
| Ch73 Edge Blending Options（横截面/overlap fix/tight corner/self-int repair）| 1257 |
| Ch74 Edge Blend Overflows（smooth/cliff/notch，internal/external）| 1321 |
| Ch75 Face-Face Blending | 1347 |
| Ch76 Three-Face Blending | 1431 |
| **Ch77 Interpreting Edge Blending Error Codes（失效分类学核心）** | 1451 |
| **Ch78 Interpreting Face-Face Blending Error Codes** | 1461 |

抽取的章节纯文本存于会话 scratchpad（`blend_*` / `error_codes_*` / `facef_*` / `threef_*`.txt），可按需回查。
