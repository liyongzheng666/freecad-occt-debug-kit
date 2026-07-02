# 圆角缺陷调研 Agent —— 推进路线图与欠缺项清单

> 状态：**Agent v0 + 根因 Eval + rule/LLM A/B + 轨迹/标注闭环（含 viewer review 写回）+ G26 真实模型输入(v1) + Parasolid 对照补足第一轮（失效四态 + STEP 真值资产 + kernel_crash 兜底）已投产**（A0–A7 工具层 ✅，A6 全闭环 ✅，G26 BREP/STEP+指定边 ✅，P0.1/P1.1/P1.2/P2.1 ✅；下一站 P1.3 triage 补全 / P2.2 S4 顶点 / A8 深探针 / FCStd 直读）<br>
> **最终目标：根因寻找（root-cause finding）**——不是"把圆角修好"，而是定位"圆角失败是流水线哪一阶段先崩、为什么崩"，并给出可验证的因果结论供人 review。<br>
> 面试对标：DeepSeek **Harness 工程师**（agent 脚手架 + eval 基础设施）。<br>
> 关联真源：[playbook/blend-failure-ontology.md](playbook/blend-failure-ontology.md)（失效本体）、[docs/root-cause-verification.md](docs/root-cause-verification.md)（根因验证方法学）、[../docs/occ-fillet-debug-agent-architecture.md](../docs/occ-fillet-debug-agent-architecture.md)（架构）、[../docs/fillet-para-study-and-agent-gap-plan.md](../docs/fillet-para-study-and-agent-gap-plan.md)（Parasolid 失效分类学对照 + 补足计划 + 执行进展）、[../docs/occ-mesh-daemon-plan.md](../docs/occ-mesh-daemon-plan.md)。

---

## 进度快照（最近更新 2026-07-02）

**已投产（真跑 + 自测，17 个 test 模块全绿：scorer / session / check_valid / reproduce / reproduce_crash / ssi_probe / playbook / triage_input / capture / decide_llm / trajectory / review / investigate_ssi / investigate_cf / investigate_overflow / **investigate_vertex** / g26_realmodel）**：

- **工具层**：`reproduce`(FreeCADCmd, real+replay，**信号退出归 `kernel_crash`**——P1.1/G28) · `check_valid`(occ-debug-mesh BRepCheck) · `ssi_probe`(面面求交→S3签名) · `capture`(LLDB 活几何→BREP) · `triage_input`(近切+凹曲率判别) · `playbook`(决策表)。
- **回路 ★里程碑1**：`loop/investigate.py` 决策表驱动 v0——observe(`reproduce`) → **`decide(state)` 接缝**逐候选判别(check_valid_input / radius_probe / ssi_probe) → **失效三态分类** → 对症反事实 → `emit_conclusion`。决策走 policy 接缝（`decide_rule` / `decide_llm` 同签名 A/B），模型只在此点、其余确定性。
- **A5 rule/LLM A/B ★里程碑3**：`decide_llm` 三后端可插拔（`claude_cli` 走本地 `claude -p` 复用 Claude Code 鉴权、无 key / `replay` 离线复现 / `api` 留接缝）；**确定性=record/replay**（非 temp0——opus-4-8 无 sampling 参数）。实测 **LLM 各质量维 + tool-call 与规则版逐位持平**（定位 0.78/失效分类 1.00/abstention 0.50/tool 4.83），只慢在决策延迟——印证"模型只在决策点、其余确定性"，剩余差距诚实归因到工具层（探针分辨率）非决策层。详见 `eval/baselines.md`。
- **发射缝**：`session.py`（emit→`events.ndjson`，过 `event.schema.json` 校验）。
- **A6 轨迹/标注闭环（全闭环 ✅）**：`trajectory.py` 收 run 有序轨迹（observe/decide/verdict/conclude）→ ndjson → **离线重放重打分与 live 同分**；`review.py` 把人工裁定(confirm/correct/reject)接成 **GT 标注 + 人-agent 一致率**——review(O(1)) 与 eval(O(N)) 同底座。**viewer 写回已接**：`ReviewPanel.tsx` → `reviewClient.postReview` → Bridge `/review`（viewer-review 命名空间 + 字段白名单）追加 `op=review` → agent `ingest_session_reviews` 配对结论离线算一致率（红线：Bridge 不算分）。
- **eval ★里程碑2**：`eval/eval.sh`→`runner.py` 一条命令真跑全集 → `scorer` 五维打分（定位 / **失效分类** / 机制\* / 反事实\* / 校准）+ **弃权四态裁定（abstention precision / false_commit，与定位分账）** + tool-call 成本 + wall-clock，**分层报**；基线登记 `baselines.md`（**2026-07-02，11 case**：四态全中（失效分类 1.00）、**定位全集 0.90**（face_overflow 层 1.00×2 / algorithmic_overflow 0.90×3 / geometric 两态 1.00×3 / box-r5 0.70 不回归）、abstention precision 0.50、false_commit=0；**LLM replay 臂 11 case 质量维逐位持平**——新 case 决策轨迹命中已录签名，无需重录）。机制\*/反事实\* 为代理/携带，真分待 truth-run/OCCT（A8）。runner 已接 `agent_run.edges`（原漏传，step case 指定边必需）。
- **真值 GT（11 case = 7 合成 + 4 真实 STEP，P0.1 新增）**：原 7 个——三态 `cases/box-r5.json`（LLDB overflow，S3 现经 WP5 源码插桩真实抓到）·`cases/wedge-sliver.json`（LLDB 近切 1.72°）·`cases/pocket-blind-hole.json`（几何第一性曲率）；区分度 `cases/box-clean.json`（clean 弃权 → 测不幻觉）·`cases/thinplate-false-green.json`（**false-green/代理奖励陷阱**）·`cases/wedge-thin-abstain.json`（**loop 内过度弃权** → wrong_abstain）·`cases/s3-fixture.json`（**合成** S3 fixture）。**新 4 个（真实 STEP 资产，Parasolid Blending 卷例子逐一实跑验证，`cases/models/` + manifest）**：`E2-thinbar-overlap`（最小两带重叠）·`E3-thinplate-face-overflow`（单带盖过 edge loop，Parasolid §77.3.4 loop_c）·`E5-boss-face-overflow`（溢出到 boss，Ch74/Fig74-9；OCCT 内部处理到 r≤~15）·`E4-groove-false-green`（**真实模型假绿**：凹槽 r=15 IsDone=true 但 invalid，BRepCheck 拦住）。
- **失效四态（P2.1 从三态扩展，Parasolid Ch74/§77.3.4 对照）**：`algorithmic_overflow`(≥2 边两带重叠，可 SSI 互裁) / **`face_overflow`(单边单带溢出——离开支撑面/盖过 edge loop，无第二条带可裁，新增)** / `geometric_near_tangent` / `geometric_curvature`——investigate 用 triage + **blend 边数二分**判别 → 对症修法 + **实体级定位**（近切边 `edge#0` / 凹曲率面 `face#6`）。修的真 bug：改动前单边 case 被误判 algorithmic_overflow 并谎称"两相邻圆角面重叠"——单条边**不存在**相邻带。overflow 中间面句柄埋匿名 `DStr`、capture 未必救得了，entity 维可能止于 stage（非待兑现的 ~1.00，见 §A4 残留 / WP4②）。
- **P1.3+P2.2（路径 A 免埋点广度收尾，2026-07-02②）**：triage 四字段收口（凹凸=角占率探针/短边/sliver/容差离群，只报告不进判别）+ **S4 顶点判别器投产**（`vertex_probe`+`_vertex_verdict`+playbook 第 4 候选，每 playbook case 真跑 tool+1，质量维逐位不变）；**S4 现场诚实负结果**：8 族简单构型未获 S4-proximate（Parasolid 禁止的金字塔 apex 2-of-4 构型 OCCT 全收敛——正向能力发现），不造假 GT。LLM replay 忠实重放旧轨迹（不跑 S4），质量维一致、tool 维待重录后可比（见 baselines 2026-07-02②）。
- **可视 demo**：`demo/convex_concave/`（凸/凹/可裁剪/几何不可能 四态对照 + `DISPLAY_RULES.md` 显示约束）。

**铁律落地**：全程禁用裸 `IsDone()`，成功判据 = `check_valid` 几何有效性。

**下一站（候选，新窗口接手）**：① ~~P1.3 triage_input 补全~~ ✅ **已收口（2026-07-02②）**；② ~~P2.2 S4 顶点复杂度~~ 🟡 **判别器已落地、case 诚实负结果（2026-07-02②）**：`vertex_probe` + playbook S4 候选投产（每 playbook case 真跑，tool+1）；但 S4-proximate 现场 8 族简单构型未获（金字塔 apex 2-of-4 等 Parasolid 禁止构型 OCCT 全收敛；双边 box LLDB 实测死于 StartSol:944 非 corner）→ 不造假 GT，S4 eval 正例留待复杂/导入几何；③ **FCStd 直读**（openDocument + Part::Feature）+ 多边 triage 消歧（G26 剩余）；④ **扩"决策空间大"的 case**（多候选/需早停/需领域推理选探针，让 A5 的 LLM 臂显价值——当前决策表 rule 已近最优）；⑤ ~~G8/WP5 埋点固化~~ ✅ **已解决（2026-07-02 核实）**：OCCT env_emit 改动已提交并推送 fork `v7_8_1-fillet-debug`（`c07ae703b7`），bootstrap 可再生。Parasolid 对照的完整补足计划与执行进展见 [../docs/fillet-para-study-and-agent-gap-plan.md](../docs/fillet-para-study-and-agent-gap-plan.md) §4/§5。

---

## 0. 一句话定位

现有仓库已经把 **harness 的"环境层 + 观测层"** 做得很扎实（可复现构建、同 ABI mesher、append-only 事件日志、幂等恢复、离线回放、可视化 review 面）。
**中间两层（本路线图主攻）：**

1. **Agent（根因调研决策回路）**——✅ **v0 已投产**：定位失效阶段 + 带证据因果假设 + 失效四态对症修法（见进度快照）；
2. **Eval（根因质量的自动量化）**——✅ **A4+A5 已投产**：`eval.sh`→`runner.py` 一条命令真跑全集，按定位 / 失效分类 / 机制\* / 反事实\* / 校准五维 + 弃权四态 + tool-call/wall-clock **分层打分**；**rule vs LLM A/B**（`--policy llm`，decide_llm 三后端 + record/replay）登记 `baselines.md`（机制\*/反事实\* 为代理，真分待 A8）。

两条铁律贯穿全程（详见 [docs/root-cause-verification.md](docs/root-cause-verification.md)）：

- **成功判据 = 几何有效性（S6），不是 `IsDone()`**（否则掉进代理奖励陷阱）。
- **根因 ≠ 修法**：repair 仅在"只针对所宣称的因"时才算反事实验证。

本路线图刻意**先用"已建好的能力"把 Agent + Eval 跑通**（首攻 S0/S6 这类免埋点根因类），再增量接入 SSI（轻埋点）与 SurfData/corner（深埋点）。

---

## 1. 现状盘点（已具备，面试要主动讲）

| 能力 | 落点 | harness 术语 |
| --- | --- | --- |
| 可复现执行环境（pinned forks + pixi + 幂等 bootstrap） | `scripts/bootstrap.sh` | reproducible env |
| 同 ABI 几何工具（BREP→mesh/geom/defects） | `tools/occ-debug-mesh/` | version-skew 控制 |
| append-only 事件日志 + flock + 多写者 run 命名空间 | `scripts/occ-mesh-daemon.py` | trajectory log |
| 幂等 + 崩溃恢复 | `occ-mesh-daemon.py` | re-entrant run |
| 离线回放底座（不接 LLDB/FreeCAD 可全链路回归） | `scripts/fake-occ-session.py` / `validate-events.py` / `verify-occ-mesh-daemon.sh` | offline replay |
| 可视化 review 面（SSE + Three.js + 分组/拾取/UV） | `tools/Print/` | grounding / 人工 review |
| BRepCheck 缺陷遍历（S0/S6 验证的雏形） | `tools/occ-debug-mesh/`（`--diagnose`） | validity verifier 雏形 |
| 高质量设计文档（范围/非目标/风险表/调用链 §23） | `docs/` | 设计基线 |

---

## 2. 欠缺项完整清单（Gap Register）

> 级别：🔴 = 没有它就"根本不算根因 Agent"；🟠 = 没有它"无法量化 / 对 Harness 岗不可信"；🟡 = 深度/泛化/打磨。

| # | 欠缺项 | 现状 | 级别 | 阶段 |
| --- | --- | --- | --- | --- |
| G1 | **Agent 决策回路**（observe→定位→机制→反事实→结论） | 完全没有；流程是给人看的一次性管线 | 🔴 | A3 |
| G2 | **Agent-native 工具接口**（typed in/out、结构化错误、统一 action surface） | 只有给人用的 CLI + shell + README | 🔴 | A2 |
| G3 | **可执行验证**（靶向子复现 + 互斥反事实，**非 `IsDone()` 二分**） | 没有；结论无法自证 | 🔴 | A2/A3 |
| G4 | **结构化 playbook**（症状→候选根因→区分观测的决策表） | ✅ `fillet-failures.json` 决策表 + `query_playbook`；investigate 据此逐候选跑判别器 | 🔴 | A2 |
| G17 | **几何有效性 verifier**（BRepCheck + 自交 + G1 + 拓扑增量，替代 `IsDone()`） | 🟡 BRepCheck 级**已实做**（`check_valid` 走 occ-debug-mesh，真几何自测 `tools/test_check_valid.py`，14 个真实 BREP 零误报）；**P1.2 实证缺口比原判窄**：真实模型假绿（`E4-groove-false-green` r=15，IsDone=true）被现有 BRepCheck 直接拦住（1 invalid_subshape），无需 BOP；⏳ 面面自交（BOPAlgo_CheckerSI）+ G1/切向 + 拓扑增量待补 | 🔴 | A2 |
| G19 | **失效本体 + 症状/阶段适配层**（playbook 骨架） | 🟡 适配层已代码化（symptom→近端阶段节点 + distal 候选 + 判别器映射）；本体多签名待扩 | 🔴 | A2 |
| G20 | **根因三腿验证**（定位 / 机制 / 反事实，含互斥靶向修法判别） | 方法学已写（见 docs/），未实现 | 🔴 | A3 |
| G18 | **输入预检 triage（S0 输入质量）**——agent 首发诊断 | ✅ **P1.3 收口（2026-07-02②）**：近切+凹曲率判别（驱动四态）+ 四字段补全——`convexity`（角占率探针：边中点垂直面 16 点小圆 isInside 占率≈材料楔角/360，方向无关；pocket 盲孔底缘=唯一凹边实证）/`short_edges`/`sliver_faces`/`tolerance_outliers`（薄片 fixture 正例）。**只报告不进判别**（判别量逐位不变）。输入 BRepCheck 由既有 check_valid_input 判别器覆盖 | 🟠 | A2 |
| G5 | **根因 Eval harness**（scorer 按定位/机制/反事实/校准打分 + runner + 回归基线） | ✅ `eval/runner.py` + `eval.sh` 一条命令真跑全集 → `scorer` 五维（加**失效分类**）分层打分，规则版基线登记 `baselines.md`；机制/反事实为代理/携带，真分待 A8 | 🟠 | A4 |
| G6 | **Case 数据集 + ground truth（四元组）** | 只有 mesher fixtures，无标注缺陷集 | 🟠 | A1 |
| G21 | **case 分层**（凹/凸 × 单边/链/顶点 × 定/变半径 × clean/overflow） | 无；现有思路是玩具 box | 🟠 | A1 |
| G22 | **instrumented truth-run GT**（埋点版跑出"真崩阶段+实体"作标签） | 无 | 🟠 | A1 |
| G24 | **因果链 GT + 部分得分**（真实根因常是 S0→S3 链，单一 `true_stage` 不够） | ✅ 契约（`CausalHypothesis.chain`/`GroundTruth.true_chain`）+ `cases/schema` + **scorer 定位部分得分已实现并离线自测**（`eval/test_scorer.py`）；机制/反事实维待运行时（truth-run/OCCT） | 🟠 | A1/A4 |
| G7 | **决策确定性**（~~temp=0/seed~~ → record/replay 决策） | ✅ A5 决策走 **record/replay**（`decide_llm` 录 `eval/llm_decisions/`，replay 离线逐位复现）；⚠️ temp=0 对 `opus-4-8` 失效（sampling 参数已移除）；工具输出确定性走 reproduce replay | 🟠 | A1/A5 |
| G8 | **LLM 集成**（model + prompt + 决策点） | ✅ `decide_llm` 三后端（claude_cli/replay/api），决策点接 `claude-opus-4-8`（claude_cli 复用 Claude Code 鉴权、无 key），rule vs LLM A/B 成文 | 🟠 | A5 |
| G9 | **Agent 轨迹日志**（决策 + tool-call 可离线评分/重放） | ✅ `trajectory.py`：investigate 收集有序轨迹（observe/decide/verdict/conclude），`TrajectoryWriter` 落 ndjson，`replay_conclusion` **离线重建结论 → 重打分与 live 同分**（`test_trajectory.py`） | 🟠 | A6 |
| G10 | **review → 标注写回 + 一致率指标** | ✅ **全闭环，零测试缺口**：`review.py apply_review`（confirm/correct/reject → GT 标注 + per-dim 一致）+ `agreement_rate`；`session.py emit_review` 写回 `op=review`；`ingest_session_reviews` 配对 run_end 离线算；**viewer `ReviewPanel`→`postReview`→Bridge `POST /review`→events.ndjson** 已通。五侧全测：`test_review.py`/`test_session.py`/`reducer.test.ts`/`bridge/test_bridge_review.py`（真起 HTTP server 测盖戳/校验/伪造头拒绝/seq 单调）/ viewer `tsc` | 🟠 | A6 |
| G25 | **结论→viewer 事件桥 / 发射缝**（`Conclusion`/`Evidence` 的 artifact_id/source → viewer 可渲染事件） | ✅ `session.py` 全实做：`emit_tool_result`→note / `emit_conclusion`→run_end，过 `event.schema.json` 校验 + 离线自测（`test_session.py`） | 🟠 | A3/A6 |
| G11 | **成本度量**（tool-call 数 / wall-clock / 重跑成本） | ✅ runner 经 `investigate(trace=…)` 数 tool-call + perf_counter 量 wall-clock，分层报（重跑成本随 replay 后端） | 🟠 | A4 |
| G23 | **SSI 靶向探针（S3）**：capture 两面 + 跑独立 `IntTools` 复现 | 🟡 探针**已实做**（`ssi_probe` 真跑面面求交→S3 签名，4 夹具判别自测）；capture 两面（occdbg/LLDB）仍欠 | 🟡 | A7 |
| G12 | **置信度 / 主动弃权 + abstention precision** | 🟡 **弃权度量已落地**：scorer 判弃权四态（correct_abstain / false_commit / wrong_abstain / correct_commit），runner 汇总 abstention precision + false_commit 安全指标（`box-clean` 区分度 case 验证）；⏳ 置信度阈值驱动的主动弃权（停在能站住的层）待 A8 | 🟡 | A4/A8 |
| G13 | **真实 capture 前半管线**（occdbg / LLDB 动态命令 / FCStd baseline / instrumentation patch） | 🟡 LLDB capture 链路已通（断点绑定 + occ_emit_shape→BREP，`capture.py` 桥真跑验证）；FCStd baseline / instrumentation patch 待 | 🟡 | A7/A8 |
| G14 | **SurfData/corner 深探针（S2/S4）** | 依赖 G13 | 🟡 | A8 |
| G15 | **沙箱 / 资源上限 / per-case 隔离 / 并发** | daemon 有单点 timeout，未泛化 | 🟡 | A8 |
| G16 | **泛化 adapter**（chamfer / boolean / offset；本体已内核无关） | 仅 fillet | 🟡 | A8 |
| G26 | **真实模型输入 adapter**（载入用户 FCStd/STEP/BREP + 指定边 + 单边 triage）——从合成 case 跨到真实失败诊断 | 🟡 **v1 已投产**（2026-07-01）：`build_shape` 认 `brep:/step:/file:` 前缀载真几何（BREP+STEP，走 `Part.Shape().read()`）；`edges` 穿透 reproduce(`REPRO_EDGES`) 全诊断链；`triage_input(edge_index=)` 单边聚焦（`TRIAGE_EDGE_INDEX`）；CLI `investigate "brep:/abs.brep" <r> --edges N`。自测 `tools/test_g26_realmodel.py`（自足 round-trip，缺 FreeCADCmd SKIP）。⚠️ **坑（P0.1 实证）**：STEP 导出+重读会**重编号边**（`Part.Shape().read()` 边序 ≠ 内存构建序，E4 7→8、E5 7→6）——边号必须对**读回后**的 shape 复核。⏳ 待补：FCStd 直读（需 openDocument + Part::Feature 遍历）、多边 triage 消歧 | 🟠 | A6 |
| G27 | **overflow 现象维**（单带溢出 vs 两带重叠二分；Parasolid Ch74 overflow + §77.3.4 loop_c 对照） | ✅ **P2.1 已落地**（2026-07-02）：playbook 加 `face_overflow` 四态；`_classify_s2_failure` else 分支按 **blend 边数二分**（单边=单带溢出 / ≥2 边=两带重叠）——修掉"单边 case 谎称两相邻带重叠"的假机制。自测 `loop/test_investigate_overflow.py`（box-r5/E2 回归 + E3/E5/E6 转类 + cause 文案断言）。⏳ 细分 loop vs neighbour 溢出（P2.3）、smooth/cliff/notch 现象识别留后 | 🟠 | P2 |
| G28 | **内核崩溃归类**（进程被信号打死 ≠ harness 逻辑无输出） | ✅ **P1.1 已落地**（2026-07-02）：`reproduce` 把 rc<0 / ≥128 归 `phase="kernel_crash"`（→ investigate 分支 C 兜底弃权）。**诚实边界**：OCCT 圆角自然崩溃**非隔离可复现**（同进程多半径累积假象，E4 实测修正），故验收用合成信号退出 `tools/test_reproduce_crash.py`，不碰运气触发真崩溃 | 🟡 | P1 |
| G29 | **Parasolid 失效分类学对照 + STEP 真值资产**（~25 fault token ↔ S0–S6 映射；文档例子 → 实跑验证的 STEP） | ✅ **P0.1 已落地**（2026-07-02）：`cases/models/` 6 个 STEP + manifest（每个经隔离 FreeCADCmd 实跑验证 + 读回边号核定）；4 个进 eval（E2/E3/E4/E5）。完整对照表 + 补足计划见 `../docs/fillet-para-study-and-agent-gap-plan.md` §3/§4。⏳ 未覆盖：S4 顶点（P2.2）、B-surface（P3.1）、chamfer/变半径（P3.2） | 🟠 | P0 |

---

## 3. 推进顺序（Agent 轨道 A0–A8）

> 设计原则：**每阶段都产出可 demo、可被 eval 打分的东西**；根因覆盖**从两头往中间推**——先 S0/S6（免埋点）→ 再 S3 SSI（轻埋点）→ 最后 S2/S4（深埋点）。
> 与架构文档的关系：A 轨道复用基础设施，但**刻意不阻塞**在架构 M3（instrumentation）/M4（agent runner）；那两块在 A7/A8 才折叠进来。

### 目标目录结构（本路线图建成后）

```text
agent/
├── README.md                       # 本文件（路线图）
├── __init__.py                     # 使 agent 成为 package：python -m agent.loop.investigate
├── contracts.py                    # 跨层 typed 数据契约（G2）：RunEnd / Conclusion / GroundTruth / Review / Stage …
├── session.py                      # 工具/结论 → 既有事件协议的发射缝（G25，agent↔kit 唯一接缝）
├── trajectory.py                   # ✅ A6/G9：运行轨迹（决策+tool+结论）ndjson + 离线重放重打分
├── review.py                       # ✅ A6/G10：人工 review → GT 标注 + 人-agent 一致率（离线数据核）
├── playbook/
│   ├── blend-failure-ontology.md   # 失效本体（S0–S6 + ChFi3d 适配）✅ 已建
│   ├── fillet-failures.json        # ✅ 可执行决策表（symptom→候选+判别器+失效四态，P2.1 加 face_overflow）
│   └── fillet-failures.yaml        # 人读 schema 参考（环境无 PyYAML，表用 json）
├── docs/
│   └── root-cause-verification.md  # 根因三腿验证方法学 ✅ 已建
├── cases/                          # case 定义 + 四元组 GT（G6/G21/G22）
│   ├── schema.md
│   ├── box-r5.json                 # ✅ LLDB GT：StripeEdgeInter overflow（algorithmic）
│   ├── wedge-sliver.json           # ✅ LLDB GT：StartSol 近切（geometric_near_tangent，capture 1.72°）
│   ├── pocket-blind-hole.json      # ✅ 几何第一性 GT：盲孔 r4>凹曲率 r3（geometric_curvature，face#6）
│   ├── box-clean.json              # ✅ 区分度/clean 弃权：良性 r2 无缺陷 → 正确弃权（测不幻觉）
│   ├── thinplate-false-green.json  # ✅ 区分度/false-green：IsDone=true 但自交（代理奖励陷阱 + 症状-only 部分分）
│   ├── wedge-thin-abstain.json     # ✅ 区分度/过度弃权：可行半径 <探针下限 → wrong_abstain（loop 内弃权）
│   ├── E2-thinbar-overlap.json     # ✅ P0.1 真实 STEP：最小两带重叠（algorithmic_overflow）
│   ├── E3-thinplate-face-overflow.json # ✅ P0.1+P2.1：单带盖过 edge loop（face_overflow，Parasolid loop_c）
│   ├── E4-groove-false-green.json  # ✅ P1.2 真实模型假绿：凹槽 r15 IsDone-but-invalid → S6
│   ├── E5-boss-face-overflow.json  # ✅ P0.1+P2.1：溢出到 boss（face_overflow，Ch74/Fig74-9）
│   └── models/                     # ✅ P0.1 STEP 真值资产（6 个 + manifest.json，逐一隔离实跑验证）
├── tools/                          # agent-native typed 工具（G2/G3/G17/G18）
│   ├── reproduce.py                # FreeCADCmd recompute；real + replay 双后端
│   ├── _fillet_harness.py          # FreeCAD 进程内 fillet harness（env 驱动，非 agent 包）
│   ├── check_valid.py              # 几何有效性判据（替代 IsDone）
│   ├── triage_input.py             # S0 输入预检 + 失效分类判别（近切/凹曲率）
│   ├── _triage_harness.py          # FreeCAD 进程内 triage harness（env 驱动，非 agent 包）
│   ├── ssi_probe.py                # S3 靶向子复现（面面求交+近切角→S3签名）（A7）
│   ├── _ssi_harness.py             # FreeCAD 进程内 SSI harness（env 驱动，非 agent 包）
│   ├── capture.py                  # LLDB 活几何 capture 桥（occ_capture→BREP→ssi_probe）（A7）
│   └── playbook.py                 # query_playbook 检索
├── loop/                           # agent 决策回路（G1/G20）
│   ├── decide_rule.py              # ✅ 规则版 policy decide(state)→action（eval 下限基线 + A/B rule 臂）
│   ├── decide_llm.py               # ✅ LLM 版 policy decide(state)（A5）：claude_cli/replay/api 三后端 + 录制
│   ├── test_decide_llm.py          # ✅ 纯函数单测（prompt 构造 / action 解析，不碰网络）
│   └── investigate.py              # observe→定位→机制→反事实→结论
├── eval/                           # 根因评估 harness（G5/G11）✅ A4/A5
│   ├── scorer.py                   # 定位/失效分类/机制*/反事实*/校准 五维 + 弃权四态打分
│   ├── runner.py                   # 跑全集 → investigate(--policy) → score → 分层表（tool-call/wall-clock）
│   ├── eval.sh                     # 一条命令入口（→ runner，透传 --case/--json/--policy）
│   ├── baselines.md                # rule（A3）+ LLM（A5）基线 + A/B 结论
│   └── llm_decisions/              # ✅ A5 录制决策（replay 后端读 → 离线确定复现 A/B、零计费）
├── demo/                           # 可视 demo（真失败几何 + 结论 → Print viewer）
│   ├── wedge_demo.py               # capture HS1/HS2(活失败现场) + investigate → session
│   ├── view.sh                     # 起 daemon+bridge+viewer
│   └── convex_concave/             # 凸/凹/可裁剪/几何不可能 四态对照 + DISPLAY_RULES.md
└── trajectories/                   # 运行轨迹（G9，gitignore）

> 注：每个 tool 配同名 `test_*.py`（真跑自测，FreeCADCmd/LLDB 不在则 SKIP）；包根模块 `session.py`/`trajectory.py`/`review.py` 各自测 `test_session.py`/`test_trajectory.py`/`test_review.py`（离线，无 OCCT）。
```

---

### A0 —— 盘点与目标对齐 ✅

- [x] 现状盘点 / 欠缺项清单 / 分阶段路线图（本文件）
- [x] 失效本体（`playbook/blend-failure-ontology.md`）
- [x] 根因验证方法学（`docs/root-cause-verification.md`）
- [x] 建项目骨架（package + 跨层契约 + 各层 stub），`.gitignore` 掉 `agent/trajectories/`

**面试价值**：把模糊目标拆成有依赖、可验收、且**领域正确**的工程计划。

---

### A1 —— 分层 Case 集 + 四元组 GT + reproduce（地基）

补齐：G6、G21、G22、G7（一半）。

- [x] `cases/schema.md`：输入 + **四元组 GT**（真崩阶段、涉及实体、期望中间态、靶向修法）+ `true_chain` + `failure_class`。
- [~] **分层** case：**11 个真值 case（2026-07-02 起）**——原 7 个：**失效三态各 1**（`box-r5` algorithmic_overflow / `wedge-sliver` geometric_near_tangent，LLDB；`pocket-blind-hole` geometric_curvature，几何第一性）+ **3 区分度 case**（`box-clean` clean 弃权 / `thinplate-false-green` 代理奖励陷阱 / `wedge-thin-abstain` loop 内过度弃权）+ **1 合成 fixture**（`s3-fixture`）；**P0.1 新增 4 个真实 STEP case**（`E2-thinbar-overlap` 最小两带重叠 / `E3-thinplate-face-overflow`+`E5-boss-face-overflow` **face_overflow 新态各 1** / `E4-groove-false-green` 真实模型假绿），资产 `cases/models/`（Parasolid Blending 卷例子，逐一隔离实跑验证）。eval 按 failure_class + clean + 其它分层，弃权四态与定位分账。⏳ 待扩：S4 顶点（P2.2）、B-surface（P3.1）、链/变半径完整分层（S0→S3 链仍缺真实正例）。
- [x] `tools/reproduce.py`：跑 FreeCADCmd recompute → 结构化 `RunEnd{status, exception, phase, …, bad_shape, is_done}`（§24）。✅ 真跑 FreeCADCmd（env 驱动 `_fillet_harness.py`，box/box-flat case + 任意半径/边）；**status=跑完产形状 ≠ 有效**（有效性归 check_valid），自测 `test_reproduce.py`。
- [x] **record/replay 双后端**：real 跑真 FreeCADCmd；replay 读已录制 `RunEnd`（brep 一并录入 → 自洽）→ eval 不必每次拉重型栈。
- [x] **instrumented truth run**：LLDB `br set -E c++` 跑出真崩点——box-r5→`ChFi3d_StripeEdgeInter`(overflow)、wedge→`StartSol echec`(近切)，作为 GT 标签来源（见两 case 的 `truth_run` 段 + 记忆 `fillet-*-crash-site`）。

**验收**：分层 case 各能产出结构化 `RunEnd`；GT 四元组齐备；replay 后端离线复现一致。
**面试价值**：领域正确的 labeled task suite + 可执行 GT + record/replay = 根因 eval 的地基。

---

### A2 —— 确定性工具层 + 有效性判据 + 输入预检 + Playbook（**免埋点**）

补齐：G2、G3、G4、G17、G18、G19。

- [~] `tools/check_valid.py`：**几何有效性判据**——`BRepCheck_Analyzer` + 自交 + G1/切向 + 拓扑增量。**全项目以此为成功判据，禁用裸 `IsDone()`。** 它是 **reward signal + 一等几何活**（自交用 `BOPAlgo_CheckerSI`、G1 单独检测），配自己的测试集，非 wrapper。✅ BRepCheck 级已落地（shell out occ-debug-mesh `<base>.defects.json`，真几何自测）；⏳ 待补：BOPAlgo_CheckerSI 面面自交、G1/切向、拓扑增量。
- [x] `tools/triage_input.py`：S0 输入预检 + **失效分类判别**。✅ `min_dihedral`(近切) + 支撑面凹曲率半径——驱动四态判别（P2.1 边数二分）；✅ **P1.3 四字段补全（2026-07-02②）**：convexity（角占率探针）/short_edges/sliver_faces/tolerance_outliers + `vertex_report`（TRIAGE_EDGES 多边共享顶点构型，P2.2）——只报告不进判别，真测 `test_triage_input.py`（21 断言）。输入 BRepCheck 由 check_valid_input 判别器覆盖。
- [x] `tools/playbook.py`：`query_playbook(signature)` 检索决策表节点（symptom→节点，子串/全等匹配，单测覆盖）。
- [x] `playbook/fillet-failures.json`：按 §5 schema 写签名 `fillet-notdone-overflow`（`proximate_stage` + distal→proximate 排序的 `root_cause_candidates` S0/S2/S3 + 互斥 `counterfactual`）。环境无 PyYAML → 表用 JSON，`.yaml` 留作人读 schema。
- [ ] 工具统一规范：typed I/O、结构化错误、**每次调用落 session**（进 viewer + 进轨迹）、带 timeout。

**验收**：`check_valid` 能把"`IsDone()=true` 但自交"的 case 判为无效；`triage_input` 能在 `near-tangent-faces` 上报出近切；3 条 playbook 过格式校验。
**面试价值**：体现"知识下沉到确定性工具、堵住代理奖励、输入预检前置"的领域+harness 双重品味。

---

### A3 —— Agent loop v0（规则版，首攻 S0/S6 根因类）★里程碑 1：会做根因定位的 Agent v0

补齐：G1、G20。

- [x] `loop/decide_rule.py`：规则版 policy **已抽出**——`decide(state)->{"run":cand}|{"conclude":True}` 是 investigate 回路唯一决策接缝（rule 臂=顺序穷尽候选）；A5 的 `decide_llm.py` 同签名直换（已落地 A/B）。改造后 eval 数字不变（回归通过）。
- [x] `loop/investigate.py`：编排 **observe(`reproduce`) → query_playbook → `decide` 接缝逐候选定位 → 失效四态分类 + 实体级定位 → 反事实(靶向修法重跑) → emit_conclusion**。✅ 端到端真跑 3 case：S2 定位 + radius_probe 可行上界 + S0 排除 + S3 诚实标 untestable；✅ triage 三态细分 + 实体级定位（近切边/凹曲率面）；决策走 policy 接缝（rule/llm 可 A/B）。
- [x] **三腿里免埋点的两腿**（定位 + 反事实）已落：定位=输入有效性 + 失败现场；反事实=互斥靶向半径探测（判据 S6 几何有效，非 IsDone）。机制腿（S2/S3/S5 区分）留 A7/A8。
- [x] `emit_conclusion`：输出**分级因果假设**（阶段链 + 定位深度 + 证据`source` + 置信度），经 `session.py` 落 `events.ndjson`（note/run_end）供 viewer review。

**验收**：对 `near-tangent-faces` 端到端跑出"S0 近切→（诱发 S3）；证据：二面角 <ε + 求交 0 线；靶向修法：heal 输入有效、降半径无效"，并在 viewer 可点开 review。
**面试价值**：项目从"管线"翻成"会做根因调研"的拐点；规则版同时是 eval 下限基线。

---

### A4 —— 根因 Eval harness ★里程碑 2：可量化 ✅

补齐：G5、G11。

- [x] `eval/scorer.py`：按 [docs/root-cause-verification.md](docs/root-cause-verification.md) §6 的维度打分——**定位准确率 / 失效分类准确率 / 机制\* / 反事实\* / 校准**；用四元组 GT（+ `failure_class`）；**无人在环**。机制\*/反事实\* 此刻为深度代理/仅判携带，真分待 truth-run 中间态 / OCCT 执行（A8），表里照实标 basis 不假绿。
- [x] 指标另含 **tool-call 次数（成本）**（runner 经 `investigate(trace=…)` 数）、**wall-clock**（perf_counter）；**按失效类别分层分别报**（别让 box 的绿盖住 wedge 的红）+ 全集汇总。
- [x] `eval/eval.sh`（→ `eval/runner.py`）+ `eval/baselines.md`：一条命令真跑全集、可 `--json` 存结构化结果、登记规则版基线。缺 FreeCADCmd → 相关 case 标 SKIP（不假绿）。

- [x] **定位 entity 维落地（canonical token 召回）**：GT 实体改用可匹配 token（`edge#0` / `stripe@S2`），investigate 在近切类把 triage 量出的近切边作实体级定位回填。结果分层不均是**真实信号**：`wedge` 近切定位 **1.00**（triage 命名 edge#0，与 LLDB 1.72° 同处）、`box` overflow 定位 **0.70**（S2 中间面免埋点命名不了；句柄埋 `StripeEdgeInter` 匿名 `DStr`、capture 未必救得了 → entity 维可能止于 stage）——0.70 是诚实下限，不保证 A7 能升到 ~1.00；wedge 1↔box 0.70 的差至少照出"近切类 capture 可命名 vs overflow 匿名 DStr"的真实分野。

**验收**：✅ `bash agent/eval/eval.sh` 跑出分层指标表，可复现——`box-r5`/`wedge-sliver` 根阶段 + 失效三态全中（失效分类 1.00）；定位 box 0.70 / wedge 1.00 / 全集 0.85，机制\*/反事实\* 诚实标代理。
**面试价值**：Harness 岗**核心交付物**；换 prompt/模型涨没涨有客观、分层的答案，且分层能照出"免埋点 vs capture"的实体定位差。
**残留（不阻塞）**：box overflow 的 entity 维 0.70 是诚实下限——两 fillet 带句柄埋在 `StripeEdgeInter` 匿名 `DStr`（见 `cases/box-r5.json` truth_run），capture 取不到具名面，**该格可能止于 stage 级、不保证升到 ~1.00**（WP4② 已诚实化此前的"待 capture→~1.00"支票）；机制/反事实真分待 A8。

---

### A5 —— LLM decide ★里程碑 3：真 Agent + A/B

补齐：G8、G7（另一半）。

- [x] `loop/decide_llm.py`：决策点换 LLM。prompt **只含**：角色 + 当前结构化证据 + 命中的 playbook 节点 + 可用工具 + "选下一个动作或下结论"。**不含**算法细节/算术/几何提取逻辑。✅ 三后端可插拔（`claude_cli` 默认走本地 `claude -p` 用现有 Claude Code 鉴权，无需 API key / `replay` 读录制决策 / `api` 留给他人接 anthropic SDK+key），与 reproduce 的 real/replay 同纪律；纯函数（prompt 构造/action 解析）单测 `test_decide_llm.py`。
- [x] **确定性 = record/replay**（⚠️ 不是 temperature=0：默认模型 `claude-opus-4-8` 已移除 sampling 参数，传 temperature/top_p/top_k 直接 400 —— adaptive-thinking-only）。决策录 `eval/llm_decisions/`，replay 后端离线确定复现 A/B 表、零计费、可进 CI（实测逐位一致）。
- [x] 同一 case 集、同一组工具、同一 `decide(state)` 接缝上 A/B：规则版 vs LLM 版（`eval.sh --policy llm`），结果登记 `baselines.md`。

**验收**：✅ A/B 成文——**LLM 各质量维 + tool-call 与规则版逐位持平（定位 0.78 / 失效分类 1.00 / abstention 0.50 / false_commit 0 / tool 4.83）**，只慢在决策延迟（~26s vs 1.1s，replay 后回到 1.1s）。
**面试价值**：印证"模型只在决策点出现、其余确定性"——换决策臂正确性一字不变，质量由确定性工具扛住；且诚实归因了剩余差距（wedge-thin wrong_abstain 是探针分辨率极限、非决策层，任何 policy 都救不了）。
**残留（A5 后续）**：本 case 集决策表小（3 候选、合成 order-independent）→ rule 已近最优、A/B 难拉开；要让 LLM 显出价值需更大决策空间的 case（多候选/需早停省成本/需领域推理选探针）。

---

### A6 —— 轨迹日志 + review→标注闭环

补齐：G9、G10。

- [x] **轨迹日志（G9）**：`agent/trajectory.py`——investigate 经 `trajectory=[]` 收集**有序步**（observe → 每个 decide 动作 → 判别裁定 → conclude）；`TrajectoryWriter` 落 append-only ndjson（`trajectories/`，gitignore）；`replay_conclusion(path)` **离线重建结论不拉 OCCT** → 喂 scorer **与 live 同分**（`test_trajectory.py` + 真跑 wedge 集成验证）。
- [x] **review→标注 + 一致率（G10 离线数据核）**：`agent/review.py`——`apply_review(conclusion, review)`（confirm/correct/reject）产 **GT 标注**（`GroundTruth`，可直接喂 scorer / 沉淀成 case）+ **per-dim 一致**（root/failure_class/overall）；`agreement_rate` 跨多条 review 汇总**人-agent 一致率**（喂 A4）。`test_review.py` 覆盖三态语义 + 汇总。
- [x] **viewer 写回已接**：`features/review/ReviewPanel.tsx`（confirm/纠正根阶段/纠正失效类/纠正实体）→ `reviewClient.postReview` → Bridge `POST /review`（独立 `viewer-review` run_id 命名空间 + 字段白名单，**只追加协议事件、不算一致率**）→ `op=review` 进 events.ndjson → agent `ingest_session_reviews` 离线配对结论算一致率/标注。**五侧全测**：`reducer.test.ts`（viewer 收 review 事件）+ `bridge/test_bridge_review.py`（真起 HTTP server：POST /review → 服务端盖戳、字段白名单、伪造 run_id/seq 拒绝、seq 单调、非法输入 400 不落盘、过 schema）+ `test_session.py`/`test_review.py`（emit_review + ingest 往返）+ viewer `tsc`。

**验收**：✅ 一次 run 轨迹可离线重放并**重打分与 live 同分**；人工 review 一次即产一条 GT 标注 + 一条一致率样本。
**面试价值**：证明你理解 review（O(1) 定性）与 eval（O(N) 定量）分工，并用**一套底座**（轨迹 + 标注 + scorer）同时喂两者——review 不替代 eval，它是打标流水线。

---

### A7 —— SSI 根因类（S3，轻埋点）★里程碑 4：第一个深度根因类

补齐：G23、G13（一部分）。

**已落地的两块工具底座**：

- [x] **capture 桥（S2 现场已 pin & 真跑验证）**：`tools/capture.py` 驱动 `lldb -b` + `scripts/occ_capture.py`，断点处 `BRepTools::Write` 真写出活几何 BREP（断点绑定 OK，OSO 调试映射在）；顺带**修了 occ_capture 的 OCCT 7.8 `BRepTools::Write` 三参签名 bug**。**S2-StartSol 近切现场已 pin**：`ChFi3d_Builder_2.cxx:944`，`HS1->Face()`/`HS2->Face()` 具名可抓，`capture_ssi` 真跑通过（2026-06-27，见 `cases/wedge-sliver.json` 的 `truth_run`）——产物 `min_dihedral=1.72° / near_tangent=true / s3_signature=**false**`，即"近切 → 排除 S3、坐实 S2"。⚠️ 这是 S2 现场；**WP2 悬赏的"StartSol 成功后接触曲线退化"型 S3 仍未在真 fillet 上获到**（见下 WP2）——但另一子型（overlap 型 S3，`StripeEdgeInter` 两 blend 带 2D pcurve 重叠）已在 box-r5 **真实几何**上经源码插桩获到 `s3_signature=true`，见下 WP5。
- [x] `tools/ssi_probe.py`：**靶向子复现**——脱离 ChFi3d 单独跑面面求交（`intersectSS` + `section` + 近切角），**S3 机制证据落地**：近切 + 期望接触却 0 → S3 签名。✅ 4 夹具判别自测（横切/割→否、切→否、近切离开→是），`test_ssi_probe.py`。

**剩余工作（5 个工作包，WP1/WP3 纯 agent 侧无新几何、可先做；WP2 是长杆可并行；WP4 收口；WP5 是 WP2 负结果后的源码插桩突破）**：

- [x] **WP1 — capture_ssi 接进 investigate loop（解除 S3 永久弃权）✅**：`ssi_probe` 判别器不再硬编 `untestable`，经 capture 桥真跑面面求交。落地三件：① `tools/capture.py` 加 `CAPTURE_SPECS` 现场注册表（按 agent case 串键控，wedge→StartSol `ChFi3d_Builder_2.cxx:944` + `HS1/HS2->Face()`；box overflow 匿名 DStr 不登记）+ `capture_spec_for`/`prereqs_ok`；② `make_fail_script` 从 case+radius 生成 fail_script，**复用 `_fillet_harness.build_shape` 单一几何真源**（顺带把 harness 的 `main()` 自调用 guard 成 `if REPRO_OUT_JSON`，使其可 import 而不自跑）；③ `loop/investigate.py` 加纯函数 `_ssi_verdict`（`SSIReport`→fired/ruled_out/untestable，`n_curves_ss=-1` 哨兵→untestable 不误判 S3 排除）+ `_ssi_discriminate`（无现场/缺 LLDB 前置→照实 untestable，**不伪绿**）。**端到端实测**：`investigate wedge 1.0` 的 S3 候选从"永久 untestable"→`ruled_out`（capture StartSol HS1/HS2 真支撑面跑 ssi_probe，得近切 **1.7184°** + section 1 条 contact 边 → 失败属 S2 非 S3），结论仍 geometric_near_tangent/S2 不变。自测：`loop/test_investigate_ssi.py`（_ssi_verdict 纯映射 + 无前置弃权）+ `tools/test_capture.py`（wedge capture_ssi 真跑，缺前置 SKIP）。**CI 无 LLDB 时 S3 仍 untestable → eval 数字不变**；有 LLDB 时 tool-call +1（capture_ssi）。⚠️ **本 WP 的"box overflow 匿名 DStr 不登记 → 照实 untestable"已被 WP5 超越**：WP5 用源码插桩把 box overflow 登记成 `env_emit` 现场（免 LLDB），box 的 S3 从 untestable → fired、tool-call 8→9（详见下 WP5）；wedge 近切仍走本 WP 的 LLDB 路径不变。
- [~] **WP2 — 找一个真 S3 失效现场（长杆，2026-06-30 timebox 两轮 7 几何族 → 诚实负结果 + taxonomy）**：目标是 fillet **StartSol 成功**但其后接触曲线求交退化（期望 1 条 contact 实得 0）→ 真 `s3_signature=true`、两面具名可抓。**两轮真机 LLDB truth-run 未获**：① 凸/近切族（cone/cyl 凸台/wedge/flatcone）失败一律先死在 **S2 `StartSol`**（`Builder_2:944`，滚球座不进，到不了 S3）；② overlap 族——单边 box-r5 = **S3 `StripeEdgeInter`**(`Builder_0:2766` "too big radiuses")、双边 box = **S4 `PerformOneCorner`**(`Builder_C1:999` 同 "too big radiuses")，**两者几何都埋匿名 `DStr`、面不具名 → 纯 LLDB 表达式路线不可抓**（⚠️ 但可换源码插桩路线抓，box-r5 的 S3 已由 WP5 证实，见文末澄清）；③ 凹/鞍状族（cross-cyl 鞍缝 fillet 成功 / torus 缝边 = **S4 `PerformOneCorner`** `Builder_C1:873` "bouchon non ecrit" 未实现分支、DStr 埋）。**taxonomy 洞察（硬交付）：OCCT "too big radiuses" overlap 失败无论边(S3)还是角(S4)都把几何埋进匿名 `DStr` —— box-r5 的"DStr（纯 LLDB）取不到具名面"是 overlap 失败族的通性，非孤例（直接增强 WP4②）；纯 LLDB 路线唯一可抓的深现场是 S2 `StartSol`(HS1/HS2，wedge 已用）——WP5 后 overlap 型 S3 也可经源码插桩抓到（DStr 具名化）。** 真 S3 窄窗口（StartSol 返回后、PerformSurf 内 spring/contact 求交失败且 HS1/HS2 仍在 scope）理论存在但 7 族未踩中、低概率，留作后续长杆。全程证据见 scratchpad `WP2_findings.md`（未改任何已提交文件）。**范围澄清（2026-07-01，见 WP5）**：本 WP 悬赏的是"StartSol 成功后接触曲线退化"这一 S3 子型，纯 LLDB 表达式求值路线下仍未获、结论不变；但 taxonomy 里点名的另一子型——overlap 型 S3（`StripeEdgeInter` 匿名 `DStr`）——已改走**源码插桩**（而非纯 LLDB 探查）在 box-r5 真实几何上正面解决，两者是不同技术路线对同一"匿名 DStr"症状的应对，不构成对本 WP 负结果的推翻。
- [x] **WP3 — S3/S2 互斥反事实可执行 + s3-fixture eval case ✅**：两个子任务均完成。① 反事实从"声明修法字符串"升级为**真跑两个互斥修法出判别**（root-cause-verification.md §4 腿3）：`reproduce.py` 加 `tolerance` 入参 + `_fillet_harness.py` 加 `REPRO_TOLERANCE`；`loop/investigate.py` 加 `_counterfactual_verdict`（降半径✓/容差✓ 四组合→S2/S3/S2→S3/inconclusive）+ `_probe_tolerance_fix`（升序容差阶梯 [0.001,0.01,0.1]）；S2 分类后跑 perturb_tolerance，两修法组合判别折进结论 `counterfactual`+evidence。**实测**：三态 S2 case（wedge/pocket/box）扰容差(≤0.1)均无效 → 判 [S2]，排除 S3 容差敏感，与真值一致。② **s3-fixture eval case（2026-06-30）**：`_ssi_verdict fired` 分支在 eval 路径正式覆盖——真实 S3 接触退化现场两轮 7 族未获（WP2），以合成 near-tangent fixture 诚实替代；`investigate()` 加 `ssi_fixture` 参数，直接跑 `ssi_probe(fixture='near-tangent')` → s3_signature=true → fired → root=S3；新 case `cases/s3-fixture.json` 进 runner 集，eval 7 case 全 OK，13 单测全 PASS。scorer 的"反事实\*"维仍是代理（只判携带，不打分互斥判别正确性），真分待 A8。详见 `eval/baselines.md`。
- [~] **WP4 — eval 接 SSI 分层 + entity 维收口**：① ✅ **s3-fixture 已进 eval 集**（WP3 完成，S3 分层有 1 个正例）——真实 S3 接触退化现场仍悬挂（WP2 诚实负结果），entity 维 fixture 路径跳过 LLDB capture，N/A；② ✅ **诚实修正 A4 残留（2026-06-30）**——box-r5 entity 0.70 的"待 A7 capture 命名中间面（→~1.00）"支票已全处重述：两 fillet 带句柄埋 `StripeEdgeInter` 匿名 `DStr`、capture 未必救得了，entity 维可能止于 stage 级，0.70 是诚实下限非待兑支票（落 README §进度快照/§A4 残留/§5 + `eval/baselines.md` + `loop/investigate.py` 注释）；③ **entity 维评估维持不变（2026-07-01 追加，见 WP5）**：WP5 把 box-r5 的 S3 机制证据从"untestable"升到"fired"（真实非 fixture），但捕到的两面是通用名 `blend1`/`blend2`（`Geom_Surface` 直接落盘），不匹配 GT 的 `stripe1/2@S2` token——entity 维仍止于 0（0.70 stage 分不变），印证②"capture 未必救得了 entity"的判断，机制维证据质量提升与 entity 维打分是两件事。
- [x] **WP5 — 源码插桩解 overlap 型 S3 匿名 DStr（box-r5 真实现场）✅（2026-06-30~07-01）**：WP2 两轮 LLDB truth-run 负结果的根因是"匿名 DStr 参数、无法用 LLDB 表达式点出具名面"——WP5 换一条技术路线：直接改 OCCT 源码。`ChFi3d_Builder_0.cxx::ChFi3d_StripeEdgeInter` 把入参 `TopOpeBRepDS_DataStructure& /*DStr*/`（原匿名、编译期告诉你"用不到"）改具名 `DStr`，在原 `throw StdFail_NotDone` 之前插入：`DStr.Surface(aDat1->Surf())`/`DStr.Surface(aDat2->Surf())` 取出两条 blend 带的 `Geom_Surface`、`BRep_Builder::MakeFace` 建面、经 `OCCT_DEBUG_SSI_OUT` 环境变量门控 `BRepTools::Write` 落盘 `blend1.brep`/`blend2.brep`（**不改变无该环境变量时的行为**，纯加法、TKFillet 已重编译验证）。落地三件：① `tools/capture.py` 加 `capture_ssi_env(case, radius)`（`reproduce()` 时置 `OCCT_DEBUG_SSI_OUT` → 读回两 brep → `ssi_probe`，免 LLDB）+ `CAPTURE_SPECS["box"] = {"method": "env_emit"}`；② `loop/investigate.py::_ssi_discriminate` 按 `spec["method"]` 分派 `env_emit`/`lldb` 两路径；③ `tools/test_capture.py` 补真跑断言（FreeCADCmd 缺位 SKIP，不伪绿）。**端到端实测（box-r5, r=5）**：捕到两 blend 面 = **同一条** R5 圆柱面（同轴 Z、同径、origin 均≈(5,5,0)，BREP 原值仅差 ~1e-15/ULP 级、u 参数方向翻转）→ `ssi_probe` 得 `min_dihedral=0.0° near_tangent=true section_edges=0` → `s3_signature=true`——即 `StripeEdgeInter` "too big radiuses" 在 3D 面层的真实表现：两条 blend 带落在同一张面上、几何重合、有界接触曲线为零（非"轴平行相切"，是重叠退化）。根因判定不变（`counterfactual` 仍判 [S2]：降半径有效/扰容差无效，S3 是传播端 proximate 非根因）；entity 维不受益（见 WP4③）。**构建前置（reproducibility 缺口，需知）**：env_emit 需重编译含此改造的 debug TKFillet。改动在独立仓 `freecad/occt`（`src/ChFi3d/ChFi3d_Builder_0.cxx`），**截至 2026-07-01 仍是未提交的工作树修改、不在 pinned `v7_8_1-fillet-debug` 历史里** → 全新 `bootstrap.sh` 克隆 / 任何 `occt/` reset 都会丢它，box S3 静默退回 `untestable`（不伪绿）。要固化须把该 edit 提交到 `v7_8_1-fillet-debug`（与其它 debug 改动同处，现行约定；`.patch` 文件已是 legacy）。缺改造时 `capture_ssi_env` 抛 RuntimeError（"blend face 未写出…TKFillet 是否含 OCCT_DEBUG_SSI_OUT 改造？"）→ `_ssi_discriminate` 照实 untestable。排错行见 `docs/occt-debugging.md` Troubleshooting 表。详见 `cases/box-r5.json::capture_result` + `eval/baselines.md`。

**验收**：能对近切 case 完成三腿验证（WP1 定位面A×面B + WP3 容差/半径互斥判别）已达；**S3 eval 分层现有 s3-fixture 合成正例 ✅ + box-r5 真实 overlap 型正例 ✅（WP5）**；**WP2 悬赏的"StartSol 成功后接触曲线退化"型 S3 因真实现场两轮未获而未达（诚实负结果，见 WP2）**——这一子型 fixture 覆盖了 eval 分支，但机制保真度仍低于真实 capture；overlap 型 S3 已不再依赖 fixture。
**面试价值**：你点名的 SSI——可定位、可独立复现、机制可观测、埋点便宜，是性价比最高的深度根因类。

---

### A8 —— 深度采集 + 弃权 + 沙箱 + 泛化

补齐：G12、G14、G15、G16、G13（其余）。

- [ ] **S2/S4 深探针**：occdbg `get_surfdata`/`capture`/`set_probe`，吃滚球容纳(S2)、corner/twist(S4)；Agent 自主决定"下次在哪埋点"。
- [ ] **置信度 / 主动弃权**：证据不足停在能站住的层并交人；度量 **abstention precision**。
- [ ] **沙箱**：每 tool-call timeout + 资源上限 + per-case 隔离（worktree-per-case）+ 并发；OCCT 跨平台非确定性 → eval 比对容差归一化（临界值给容差带，不硬编码）。
- [ ] **泛化**：本体已内核无关，抽出 domain-agnostic harness 层（protocol/session/eval/轨迹/本体），fillet 之外用 adapter 接 chamfer/boolean/offset。

**验收**：能完成至少 1 类需 SurfData 的局部根因；弃权有指标；eval 可并发且单 case 失败不拖垮整轮。
**面试价值**：深度（算法内部采集）+ 成熟度（沙箱/弃权）+ 通用性（本体/adapter 解耦）。

---

## 4. 依赖关系（什么阻塞什么）

```text
A0 ─► A1(分层case+四元组GT+reproduce) ─► A2(工具+有效性判据+输入预检+playbook)
                                              │
                                              ▼
                                      A3(loop v0 规则版, 攻S0/S6)★1
                                              │
                                              ▼
                                      A4(根因eval)★2 ─► A5(LLM decide)★3
                                              │
                                              ▼
                                      A6(轨迹+review标注)
                                              │
                                              ▼
                                      A7(SSI/S3 轻埋点)★4 ─► A8(S2/S4深采集+弃权+沙箱+泛化)
```

- **A1→A2→A3→A4 是关键路径，全程免 occdbg/LLDB**（只用 reproduce + check_valid + triage_input + occ-debug-mesh + 靶向重跑）。
- **A7（SSI）只要轻埋点**；**A8（S2/S4）才需架构 M2/M3 的深埋点**——刻意排最后，不阻塞 Agent+Eval 成型。

---

## 5. 进度 & 下一步开工项

**已完成（A0–A5 + A7 工具层 + 失效四态 + P0.1/P1.1/P1.2/P2.1）**：reproduce / check_valid / ssi_probe / capture / triage_input / playbook 全落地真测；`investigate` 回路投产（★里程碑1），决策抽成 `decide(state)` 接缝（**rule + LLM 两臂**）；**11 个真值 case**（失效四态全覆盖 + 3 区分度 + 1 合成 s3-fixture + 4 真实 STEP）；**根因 Eval harness 投产（★里程碑2）** + **rule/LLM A/B（★里程碑3）**——`eval.sh --policy` 一条命令、五维 + 弃权四态分层打分、`baselines.md` 登记；**A7 WP1–WP5 SSI 深根因类落地**（capture 桥接进 loop / 反事实互斥判别 / s3-fixture eval 正例 / 源码插桩解 box-r5 overlap 型 S3）。**会做根因定位 + 可量化 + 可换 policy A/B、能在 viewer review 的 Agent v0 已成型，全程免裸 `IsDone()`。**

**实跑结论（2026-07-02，11 case，rule 版；LLM replay 臂质量维逐位持平）**：失效四态全中（失效分类 1.00）；定位全集 **0.90**（geometric 两态 1.00 = triage 实体级命名 edge#0/face#6 / **face_overflow 新层 1.00×2** / algorithmic_overflow 层 0.90（box-r5 0.70 不回归——命名受限、entity 维可能止于 stage，非待兑 ~1.00；E2 1.00）/ false-green 真实模型 E4 1.00、合成 thinplate 0.40 症状-only / s3-fixture 1.00）；弃权 **abstention precision 0.50、false_commit 0**。LLM 臂：新 case 决策轨迹命中已录签名（录制按 state 签名非 case 键控）→ replay 直接跑通 11 case、质量维逐位持平，无需重录——再次印证"模型只在决策点、其余确定性"。详见 `eval/baselines.md`。

**下一步开工项（不依赖未实现的东西）**：

1. ~~P1.3 triage_input 补全~~ ✅ **已收口（2026-07-02②）**：四字段全落地（角占率凹凸探针 / 短边 / sliver / 容差离群），21 断言真测；只报告不进判别，eval 质量维逐位不变。
2. ~~P2.2 S4 顶点复杂度~~ 🟡 **判别器落地 + case 诚实负结果（2026-07-02②）**：`vertex_probe`（TRIAGE_EDGES 共享顶点构型）+ `_vertex_verdict` 纯函数 + playbook S4 第 4 候选投产（`test_investigate_vertex` 19 断言）；**S4-proximate 现场 8 族未获**（含 Parasolid 明文禁止的金字塔 apex 2-of-4——OCCT 全收敛；WP2 的 PerformOneCorner anchor 未复现，今日双边 box 实测 StartSol:944/S2）→ 不造假 GT；后续换复杂曲面/导入模型再猎。
3. **G26 剩余**：FCStd 直读（openDocument + Part::Feature 遍历 + 多实体消歧）、多边 triage 消歧。
4. **扩"决策空间大"的 case**：决策表 rule 已近最优、A/B 难拉开；补多候选 / 需早停省成本 / 需领域推理选探针的 case，让 LLM 臂显出价值。
5. **WP2 长杆仍悬挂**：真实"StartSol 成功后接触曲线退化"型 S3 现场两轮 7 几何族未获（诚实负结果），可把 WP5 的源码插桩技巧搬到 `PerformSurf`/`PerformOneCorner` 试一次。
6. ~~G8/WP5 埋点固化~~ ✅ **已解决（2026-07-02 核实）**：`ChFi3d_Builder_0.cxx` env_emit 改动已提交并推送 fork `v7_8_1-fillet-debug`（`c07ae703b7`，`occt/` 工作树干净、与远端同步）——bootstrap 全新克隆即含埋点，box S3 复现可再生。

### 操作备忘（新窗口接手必读）

- **跑测试 / eval 一律从 repo 根** `python -m agent.xxx`——**别 `cd agent`**，否则 `import agent` 包导入失败（`ModuleNotFoundError: No module named 'agent'`）。
- **全 test 一把过（17 模块）**：`for m in test_session test_trajectory test_review loop.test_decide_llm loop.test_investigate_ssi loop.test_investigate_cf loop.test_investigate_overflow loop.test_investigate_vertex eval.test_scorer tools.test_{reproduce,reproduce_crash,check_valid,triage_input,playbook,ssi_probe,capture,g26_realmodel}; do python -m agent.$m; done`（FreeCADCmd/LLDB 不在则相关项 SKIP，不算错）。
- **eval 跑法**：`bash agent/eval/eval.sh`（rule）；LLM 离线零计费复现 `AGENT_DECIDE_BACKEND=replay AGENT_DECIDE_RECORD=$PWD/agent/eval/llm_decisions bash agent/eval/eval.sh --policy llm`；重录真决策＝去掉 `AGENT_DECIDE_BACKEND=replay`（走 `claude_cli`，需 Claude Code 鉴权、产生计费）。
- **改动未提交**（按约定 commit 等显式指示）；交接先 `git status` 看改动面。改工具契约 / case schema / eval 维度 / 失效本体，先更对应真源文档（本文件 / `playbook/blend-failure-ontology.md` / `docs/root-cause-verification.md`）。
- **本文件即索引**：真实模型诊断输入看 §8(G26)；A/B 完整数据 + 复现命令看 `eval/baselines.md`；当前 11 case GT 看 `cases/*.json`（真实 STEP 资产在 `cases/models/`）。

---

## 6. 面试叙事映射（每阶段对应一句话证据）

| 阶段 | 面试可说的一句话 |
| --- | --- |
| A1 | "我建了**分层**的 task suite，GT 是**可执行四元组**而非根因名，并用 record/replay 让 eval 不必拉重型栈。" |
| A2 | "我把成功判据从 `IsDone()` 换成几何有效性、堵住代理奖励，并把输入预检前置为首发诊断。" |
| A3 | "我的 agent 输出**分级因果假设**，靠靶向子复现 + 互斥反事实定位根因，不是 LLM 编故事。" |
| A4 | "我有根因 eval：定位/机制/反事实/校准四维、按难度分层报，换模型涨没涨有客观答案。" |
| A5 | "模型只在决策点出现，其余确定性；规则版 vs LLM 版我有 A/B 数据。" |
| A6 | "人工 review 不替代 eval，它是我的打标流水线，沉淀成一致率指标。" |
| A7 | "面面求交是我第一个深度根因类——可定位、可独立复现、机制可观测、埋点便宜。" |
| A8 | "深层缺陷靠 agent 自主埋点采 SurfData；不确定就弃权交人，并度量弃权精度；本体内核无关，换内核只换 adapter。" |

---

## 7. 已知边界与跨仓依赖（report 时必须讲明）

- **B1 — GT 自举是"合成优先"**：四元组 GT 多由 instrumented truth run 产出，而 truth run 依赖 A8 的前半埋点。因此 **A1–A4 的早期 eval 跑在合成 case 上**（人为注入已知根因，见 `cases/schema.md`）。报数字时必须讲清：早期验证的是**合成分布**，不是真实世界 fillet bug 分布；真实分布覆盖随 A8 的 truth-run GT 才打开。
- **B2 — 深层 S2/S4 采集是跨仓依赖**：`get_surfdata` / `capture` / `set_probe`（S2 滚球容纳 / S4 corner）依赖既有 kit（`scripts/` + OCCT fork）的 occdbg/LLDB 埋点（架构 M2/M3），**不在 `agent/` 内**。职责边界：**`agent/` 负责诊断逻辑与验证；前半采集在 A8 从 kit 消费**；二者唯一物理接缝是 `session.py`（事件追加）与这些采集工具的调用约定。

---

## 8. 真实模型诊断：如何完善输入（G26）

> 现状：agent 诊断的是一个 **(几何, 边, 半径)** 三元组，但输入目前只来自**硬编合成 builder**（`_fillet_harness.py` 的 box/wedge/pocket）。要诊断「我自己的模型里选某条边做圆角失败了」，需把合成几何换成**你的几何 + 那条边**。

**① 你需要提供的三样（输入契约）**

| 项 | 怎么拿 | 说明 |
| --- | --- | --- |
| **几何** | FreeCAD 里 `选中体 → Part 导出 → .brep`（或 `shape.exportBrep("m.brep")`） | **BREP 最稳**：保留 OCCT 边序；STEP 也行；FCStd 需先取出 Part::Feature 的 Shape |
| **边号** | GUI 选中边，状态栏/元素名显示 `EdgeN` | 那个 **N 就是 1-based 边序**（= `shape.Edges[N-1]`）。导出后用 `Part.Shape().read("m.brep").Edges` 复核 |
| **半径** | 失败时用的那个值 | — |

**② G26 v1 已投产（2026-07-01，BREP+STEP）**——原三处缺口已补：

- ✅ `_fillet_harness.py` / `_triage_harness.py` 的 `build_shape()` 认 `brep:/step:/file:` 前缀 → `Part.Shape().read()` 载真几何（两 harness 各留一份分支）。
- ✅ `reproduce(edges=)` 透传 `REPRO_EDGES`，且 `edges` 穿**整条诊断链**（初始 observe + radius_probe 可行上界 + WP3 容差反事实），真实多边模型不再"降半径时却 fillet 全部边"而失真。
- ✅ `triage_input(edge_index=)` → `TRIAGE_EDGE_INDEX` 单边聚焦（只报选中边的二面角/曲率，越界/无 2 支撑面 → 诚实空报告）；恰一条边时聚焦，多边回落聚合。
- ⏳ 仍缺：**FCStd 直读**（需 `App.openDocument` + 遍历 `Part::Feature` 取 Shape、多实体消歧）——v1 请先在 GUI 里把体导出成 `.brep`/`.step`；多边 triage 消歧亦留后。

**③ 现在就能跑**

```bash
# 载入你的 brep/step + 指定边 + 半径，直接出诊断（不需要 GT）；边号 N = GUI 里的 EdgeN（1-based）
python -m agent.loop.investigate "brep:/abs/path/to/m.brep" <radius> --edges <N>
python -m agent.loop.investigate "step:/abs/path/to/m.step" <radius> --edges <N>
```

得到的是**诊断结论**（根阶段 + 失效四态 + 对症修法 + 证据），**不是 eval 分数**——eval 要 GT（标准答案），真实 bug 你没有；`investigate` 直接产出根因结论，这正是你要的「定位失败在哪崩、为什么崩」。自测见 `tools/test_g26_realmodel.py`（合成 wedge 导出 brep/step → 前缀载回 → 诊断，自足 round-trip）。

**④ 两个必须讲明的坑**

- **边序稳定性**：导出**你正在圆角的那个 shape**，导出后别再 rebuild，否则 `EdgeN` 可能漂移。
- **Part vs PartDesign 圆角**：GUI 的 PartDesign Fillet 与 `Part.makeFillet` **底层同一个 OCCT `BRepFilletAPI`**——失败照样复现，根因在 OCCT 的 ChFi3d，与用哪个 workbench 无关。

---

## 9. 全面检查快照（2026-07-02，本节即检查报告）

> 触发：Parasolid 对照补足计划第一轮（P0.1/P1.1/P1.2/P2.1）落地后的全项目核对。每条都给复现命令。

### 9.1 测试与 eval 实测（全绿）

| 检查项 | 结果 | 复现 |
| --- | --- | --- |
| 全量测试 **16/16 模块 ALL PASS**（含新增 `loop.test_investigate_overflow`、`tools.test_reproduce_crash`） | ✅ | §操作备忘 的 for 循环 |
| eval rule 臂：**11 case 全 OK**，定位全集 **0.90**、失效分类 **1.00**、false_commit **0**、box-r5 0.70 不回归 | ✅ | `bash agent/eval/eval.sh` |
| eval **LLM replay 臂：11 case 质量维与 rule 逐位持平**——新 case 决策轨迹命中已录签名（录制按 state 签名非 case 键控），零重录零计费 | ✅ | `AGENT_DECIDE_BACKEND=replay AGENT_DECIDE_RECORD=$PWD/agent/eval/llm_decisions bash agent/eval/eval.sh --policy llm`（首跑冷启动 >2min 正常） |
| 6 个 STEP 资产逐一经**隔离** FreeCADCmd 实跑复核（agent 读回路径，读回边号） | ✅ | `cases/models/manifest.json` 的 `verified_fillet` |

### 9.2 本轮修掉的真 bug / 诚实修正（对齐已写入正文）

1. **假机制文案（P2.1 / G27）**：单边 case 被误判 `algorithmic_overflow` 并谎称"两相邻圆角面重叠"——单条 blend 边不存在相邻带。已按 blend 边数二分出 `face_overflow` 第四态。
2. **runner 漏传 `edges`**：`eval/runner.py` 原不把 `agent_run.edges` 传给 investigate → step case 无法指定边（会 fillet 全部边失真）。已接。
3. **E4"崩溃"是假象**：exit-139 只在同进程多半径累积时出现；隔离进程里 r=15/20 是**假绿**（IsDone=true 但 invalid）、r≥30 干净 NotDone。E4 从"崩溃 fixture"改判"P1.2 假绿 fixture"；P1.1 kernel_crash 兜底改用合成信号验收（`test_reproduce_crash.py`）。
4. **STEP 重读边号漂移**：`Part.Shape().read()` 边序 ≠ 内存构建序（E4 7→8、E5 7→6）——manifest 已用读回边号，G26 表格已加坑位说明。
5. **G17 缺口比原判窄**：真实模型假绿被现有 BRepCheck 拦住（1 invalid_subshape，无需 BOPAlgo_CheckerSI）——BOP 仅剩"BRepCheck 漏、BOP 才抓"的面面自交残余。

### 9.3 文档一致性核对（本次对齐修掉的漂移）

| 漂移 | 原值 → 现值 | 已改处 |
| --- | --- | --- |
| test 模块数 | 14 → **16** | 进度快照、操作备忘 |
| case 数 | 7 → **11** | 进度快照、A1、§5 |
| 失效分类枚举 | 三态 → **四态**（+`face_overflow`） | 进度快照、G18、A1、`cases/schema.md`、`playbook/fillet-failures.json` |
| eval 基线 | 0.82/7case → **0.90/11case** | 进度快照、§5、`eval/baselines.md` |
| 目录结构 | 缺 4 个新 case json + `cases/models/` | §3 目录树 |
| Gap Register | 无 overflow/崩溃/Parasolid 条目 | 新增 **G27/G28/G29** |

### 9.4 残留风险（诚实清单，未解决勿删）

- ~~G8/WP5 reproducibility 缺口~~ ✅ **已解决（2026-07-02 提交前核实）**：`occt/` 工作树干净，env_emit 改动已在 fork `v7_8_1-fillet-debug` 历史里（`c07ae703b7 feat(ChFi3d): env-gated blend-face dump at StripeEdgeInter for SSI capture`）且与远端同步——早前「未提交、bootstrap 即丢」的告警（写于 2026-07-01）已过时。
- scorer 的机制\*/反事实\*仍是代理/携带（真分待 A8 truth-run），`thinplate-false-green` 定位 0.40（症状-only）与 `wedge-thin-abstain` wrong_abstain（探针分辨率极限）为已知未解，非本轮回归。
- `s3-fixture` 的 GT `failure_class` 标 `algorithmic_overflow` 是合成 fixture 的近似标注（fixture 无真实边数语义），四态二分不适用于 fixture 路径——不影响打分（fixture 路径跳过 `_classify_s2_failure`）。
- 新 4 case 的 LLM 臂 wall_s 略高于 rule（冷启动+STEP 读盘），质量维无差。

---

> 维护约定：本路线图是 Agent 轨道的工作基线。完成一项勾掉一项；新增欠缺项进第 2 节 Gap Register 并标级别与阶段。任何改变工具契约、case schema、eval 维度或失效本体的改动，先更新对应真源文档（本文件 / `playbook/blend-failure-ontology.md` / `docs/root-cause-verification.md`）。
