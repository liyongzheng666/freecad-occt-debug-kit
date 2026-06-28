# 圆角缺陷调研 Agent —— 推进路线图与欠缺项清单

> 状态：路线图基线（Roadmap Baseline）<br>
> **最终目标：根因寻找（root-cause finding）**——不是"把圆角修好"，而是定位"圆角失败是流水线哪一阶段先崩、为什么崩"，并给出可验证的因果结论供人 review。<br>
> 面试对标：DeepSeek **Harness 工程师**（agent 脚手架 + eval 基础设施）。<br>
> 关联真源：[playbook/blend-failure-ontology.md](playbook/blend-failure-ontology.md)（失效本体）、[docs/root-cause-verification.md](docs/root-cause-verification.md)（根因验证方法学）、[../docs/occ-fillet-debug-agent-architecture.md](../docs/occ-fillet-debug-agent-architecture.md)（架构）、[../docs/occ-mesh-daemon-plan.md](../docs/occ-mesh-daemon-plan.md)。

---

## 0. 一句话定位

现有仓库已经把 **harness 的"环境层 + 观测层"** 做得很扎实（可复现构建、同 ABI mesher、append-only 事件日志、幂等恢复、离线回放、可视化 review 面）。
**缺的是中间两层：**

1. **Agent（根因调研决策回路）**——会定位失效阶段、给出带证据的因果假设；
2. **Eval（根因质量的自动量化）**——按定位/机制/反事实/校准打分。

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
| G17 | **几何有效性 verifier**（BRepCheck + 自交 + G1 + 拓扑增量，替代 `IsDone()`） | 🟡 BRepCheck 级**已实做**（`check_valid` 走 occ-debug-mesh，真几何自测 `tools/test_check_valid.py`，14 个真实 BREP 零误报）；⏳ 面面自交（BOPAlgo_CheckerSI）+ G1/切向 + 拓扑增量待补 | 🔴 | A2 |
| G19 | **失效本体 + 症状/阶段适配层**（playbook 骨架） | 🟡 适配层已代码化（symptom→近端阶段节点 + distal 候选 + 判别器映射）；本体多签名待扩 | 🔴 | A2 |
| G20 | **根因三腿验证**（定位 / 机制 / 反事实，含互斥靶向修法判别） | 方法学已写（见 docs/），未实现 | 🔴 | A3 |
| G18 | **输入预检 triage（S0 输入质量）**——agent 首发诊断 | 🟡 `triage_input` 已落地近切+凹曲率判别（驱动失效三态分类）；凹凸/短边/容差待补 | 🟠 | A2 |
| G5 | **根因 Eval harness**（scorer 按定位/机制/反事实/校准打分 + runner + 回归基线） | 只有"测试"harness，无"评估"harness | 🟠 | A4 |
| G6 | **Case 数据集 + ground truth（四元组）** | 只有 mesher fixtures，无标注缺陷集 | 🟠 | A1 |
| G21 | **case 分层**（凹/凸 × 单边/链/顶点 × 定/变半径 × clean/overflow） | 无；现有思路是玩具 box | 🟠 | A1 |
| G22 | **instrumented truth-run GT**（埋点版跑出"真崩阶段+实体"作标签） | 无 | 🟠 | A1 |
| G24 | **因果链 GT + 部分得分**（真实根因常是 S0→S3 链，单一 `true_stage` 不够） | ✅ 契约（`CausalHypothesis.chain`/`GroundTruth.true_chain`）+ `cases/schema` + **scorer 定位部分得分已实现并离线自测**（`eval/test_scorer.py`）；机制/反事实维待运行时（truth-run/OCCT） | 🟠 | A1/A4 |
| G7 | **决策确定性**（temp=0 / seed / record-replay 工具输出） | 环境确定性有，决策确定性无 | 🟠 | A1/A5 |
| G8 | **LLM 集成**（model + prompt + 决策点） | 完全没有 | 🟠 | A5 |
| G9 | **Agent 轨迹日志**（决策 + tool-call 可离线评分/重放） | 只有几何事件日志，无决策轨迹 | 🟠 | A6 |
| G10 | **review → 标注写回 + 一致率指标** | review 面有，标注回路无 | 🟠 | A6 |
| G25 | **结论→viewer 事件桥 / 发射缝**（`Conclusion`/`Evidence` 的 artifact_id/source → viewer 可渲染事件） | ✅ `session.py` 全实做：`emit_tool_result`→note / `emit_conclusion`→run_end，过 `event.schema.json` 校验 + 离线自测（`test_session.py`） | 🟠 | A3/A6 |
| G11 | **成本度量**（tool-call 数 / wall-clock / 重跑成本） | 无 | 🟠 | A4 |
| G23 | **SSI 靶向探针（S3）**：capture 两面 + 跑独立 `IntTools` 复现 | 🟡 探针**已实做**（`ssi_probe` 真跑面面求交→S3 签名，4 夹具判别自测）；capture 两面（occdbg/LLDB）仍欠 | 🟡 | A7 |
| G12 | **置信度 / 主动弃权 + abstention precision** | 设计有（"人工兜底"），机制无 | 🟡 | A8 |
| G13 | **真实 capture 前半管线**（occdbg / LLDB 动态命令 / FCStd baseline / instrumentation patch） | 🟡 LLDB capture 链路已通（断点绑定 + occ_emit_shape→BREP，`capture.py` 桥真跑验证）；FCStd baseline / instrumentation patch 待 | 🟡 | A7/A8 |
| G14 | **SurfData/corner 深探针（S2/S4）** | 依赖 G13 | 🟡 | A8 |
| G15 | **沙箱 / 资源上限 / per-case 隔离 / 并发** | daemon 有单点 timeout，未泛化 | 🟡 | A8 |
| G16 | **泛化 adapter**（chamfer / boolean / offset；本体已内核无关） | 仅 fillet | 🟡 | A8 |

---

## 3. 推进顺序（Agent 轨道 A0–A8）

> 设计原则：**每阶段都产出可 demo、可被 eval 打分的东西**；根因覆盖**从两头往中间推**——先 S0/S6（免埋点）→ 再 S3 SSI（轻埋点）→ 最后 S2/S4（深埋点）。
> 与架构文档的关系：A 轨道复用基础设施，但**刻意不阻塞**在架构 M3（instrumentation）/M4（agent runner）；那两块在 A7/A8 才折叠进来。

### 目标目录结构（本路线图建成后）

```text
agent/
├── README.md                       # 本文件（路线图）
├── __init__.py                     # 使 agent 成为 package：python -m agent.loop.investigate
├── contracts.py                    # 跨层 typed 数据契约（G2）：RunEnd / Conclusion / GroundTruth / Stage …
├── session.py                      # 工具/结论 → 既有事件协议的发射缝（G25，agent↔kit 唯一接缝）
├── playbook/
│   ├── blend-failure-ontology.md   # 失效本体（S0–S6 + ChFi3d 适配）✅ 已建
│   └── fillet-failures.yaml        # 结构化决策表（挂在本体上）（G4/G19）
├── docs/
│   └── root-cause-verification.md  # 根因三腿验证方法学 ✅ 已建
├── cases/                          # case 定义 + 四元组 GT（G6/G21/G22）
│   └── schema.md
├── tools/                          # agent-native typed 工具（G2/G3/G17/G18）
│   ├── reproduce.py                # FreeCADCmd recompute；real + replay 双后端
│   ├── _fillet_harness.py          # FreeCAD 进程内 fillet harness（env 驱动，非 agent 包）
│   ├── check_valid.py              # 几何有效性判据（替代 IsDone）
│   ├── triage_input.py             # S0 输入预检（二面角/短边/sliver/容差）
│   ├── ssi_probe.py                # S3 靶向子复现（面面求交+近切角→S3签名）（A7）
│   ├── _ssi_harness.py             # FreeCAD 进程内 SSI harness（env 驱动，非 agent 包）
│   ├── capture.py                  # LLDB 活几何 capture 桥（occ_capture→BREP→ssi_probe）（A7）
│   └── playbook.py                 # query_playbook 检索
├── loop/                           # agent 决策回路（G1/G20）
│   ├── decide_rule.py              # 规则版 policy（eval 下限基线）
│   ├── decide_llm.py               # LLM 版 policy（A5）
│   └── investigate.py              # observe→定位→机制→反事实→结论
├── eval/                           # 根因评估 harness（G5/G11）
│   ├── scorer.py                   # 定位/机制/反事实/校准
│   ├── eval.sh
│   └── baselines.md
├── demo/                           # 可视 demo：真失败几何 + 结论 → Print viewer（wedge_demo.py / view.sh）
└── trajectories/                   # 运行轨迹（G9，gitignore）
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

- [ ] `cases/schema.md`：输入（FCStd / 脚本化 BREP + 半径 + 选中边）+ **四元组 GT**（真崩阶段、涉及实体、期望中间态、与因对齐的靶向修法）。
- [ ] **分层** case（每层 ≥2 个）：凹/凸 × 单边/链/顶点 × 定/变半径 × clean/overflow。先覆盖：`box-concave-r-large`(S3/S2)、`near-tangent-faces`(S0→S3)、`vertex-3corner`(S4)、`short-edge`(S0/S1)。
- [x] `tools/reproduce.py`：跑 FreeCADCmd recompute → 结构化 `RunEnd{status, exception, phase, …, bad_shape, is_done}`（§24）。✅ 真跑 FreeCADCmd（env 驱动 `_fillet_harness.py`，box/box-flat case + 任意半径/边）；**status=跑完产形状 ≠ 有效**（有效性归 check_valid），自测 `test_reproduce.py`。
- [x] **record/replay 双后端**：real 跑真 FreeCADCmd；replay 读已录制 `RunEnd`（brep 一并录入 → 自洽）→ eval 不必每次拉重型栈。
- [ ] **instrumented truth run**：埋点版跑出每个 case 的"真崩阶段+实体"，作为 GT 标签来源。

**验收**：分层 case 各能产出结构化 `RunEnd`；GT 四元组齐备；replay 后端离线复现一致。
**面试价值**：领域正确的 labeled task suite + 可执行 GT + record/replay = 根因 eval 的地基。

---

### A2 —— 确定性工具层 + 有效性判据 + 输入预检 + Playbook（**免埋点**）

补齐：G2、G3、G4、G17、G18、G19。

- [~] `tools/check_valid.py`：**几何有效性判据**——`BRepCheck_Analyzer` + 自交 + G1/切向 + 拓扑增量。**全项目以此为成功判据，禁用裸 `IsDone()`。** 它是 **reward signal + 一等几何活**（自交用 `BOPAlgo_CheckerSI`、G1 单独检测），配自己的测试集，非 wrapper。✅ BRepCheck 级已落地（shell out occ-debug-mesh `<base>.defects.json`，真几何自测）；⏳ 待补：BOPAlgo_CheckerSI 面面自交、G1/切向、拓扑增量。
- [~] `tools/triage_input.py`：S0 输入预检 + **失效分类判别**。✅ 已落地 `min_dihedral`(近切) + 支撑面凹曲率半径——驱动 investigate 把 S2 失败分成 geometric(近切/曲率) vs algorithmic(overflow) **三态**，真测 `test_triage_input.py`；⏳ 凹凸分类/短边/sliver/容差/输入 BRepCheck 待补。
- [x] `tools/playbook.py`：`query_playbook(signature)` 检索决策表节点（symptom→节点，子串/全等匹配，单测覆盖）。
- [x] `playbook/fillet-failures.json`：按 §5 schema 写签名 `fillet-notdone-overflow`（`proximate_stage` + distal→proximate 排序的 `root_cause_candidates` S0/S2/S3 + 互斥 `counterfactual`）。环境无 PyYAML → 表用 JSON，`.yaml` 留作人读 schema。
- [ ] 工具统一规范：typed I/O、结构化错误、**每次调用落 session**（进 viewer + 进轨迹）、带 timeout。

**验收**：`check_valid` 能把"`IsDone()=true` 但自交"的 case 判为无效；`triage_input` 能在 `near-tangent-faces` 上报出近切；3 条 playbook 过格式校验。
**面试价值**：体现"知识下沉到确定性工具、堵住代理奖励、输入预检前置"的领域+harness 双重品味。

---

### A3 —— Agent loop v0（规则版，首攻 S0/S6 根因类）★里程碑 1：会做根因定位的 Agent v0

补齐：G1、G20。

- [ ] `loop/decide_rule.py`：规则版 policy。
- [~] `loop/investigate.py`：编排 **observe(`reproduce`) → query_playbook → 定位(`triage_input`/`check_valid`) → 反事实(靶向修法重跑) → emit_conclusion**。✅ 规则版 v0 **端到端真跑**（reproduce + check_valid + 反事实半径探测）：`box r=1000` → S2 定位 + 可行上界 ∈[2,5) + S0 排除 + 未解机制如实标注；✅ query_playbook 已接（决策表驱动逐候选判别 + 互斥反事实，每候选裁定 命中/排除/未测）；✅ triage_input 已接：S2 失败细分 **geometric / algorithmic 三态**，对症修法（overflow→SSI 互裁、近切/曲率→降半径），与 box-r5/wedge-sliver 真值一致；⏳ 规则策略暂内联（未拆 `decide_rule.py`）。
- [x] **三腿里免埋点的两腿**（定位 + 反事实）已落：定位=输入有效性 + 失败现场；反事实=互斥靶向半径探测（判据 S6 几何有效，非 IsDone）。机制腿（S2/S3/S5 区分）留 A7/A8。
- [x] `emit_conclusion`：输出**分级因果假设**（阶段链 + 定位深度 + 证据`source` + 置信度），经 `session.py` 落 `events.ndjson`（note/run_end）供 viewer review。

**验收**：对 `near-tangent-faces` 端到端跑出"S0 近切→（诱发 S3）；证据：二面角 <ε + 求交 0 线；靶向修法：heal 输入有效、降半径无效"，并在 viewer 可点开 review。
**面试价值**：项目从"管线"翻成"会做根因调研"的拐点；规则版同时是 eval 下限基线。

---

### A4 —— 根因 Eval harness ★里程碑 2：可量化

补齐：G5、G11。

- [ ] `eval/scorer.py`：按 [docs/root-cause-verification.md](docs/root-cause-verification.md) §6 的四维度打分——**定位准确率 / 机制正确性 / 反事实有效性 / 校准弃权**；用四元组 GT；**无人在环**。
- [ ] 指标另含 **tool-call 次数（成本）**、wall-clock；**按 case 分层分别报**（别让 box 的绿盖住顶点 blend 的红）。
- [ ] `eval/eval.sh` + `eval/baselines.md`：一条命令跑全集、存轨迹、记录规则版基线。

**验收**：`eval.sh` 跑出分层指标表，可复现。
**面试价值**：Harness 岗**核心交付物**；换 prompt/模型涨没涨有客观、分层的答案。

---

### A5 —— LLM decide ★里程碑 3：真 Agent + A/B

补齐：G8、G7（另一半）。

- [ ] `loop/decide_llm.py`：决策点换 LLM。prompt **只含**：角色 + 当前结构化证据 + 命中的 playbook 节点 + 可用工具 + "选下一个动作或下结论"。**不含**算法细节/算术/几何提取逻辑。
- [ ] 确定性：temperature=0 + 固定 seed + 记录工具输出（可重放）。
- [ ] 同一 case 集、同一组工具上 A/B：规则版 vs LLM 版两条曲线。

**验收**：LLM 版在根因 eval 上 ≥ 规则版基线；A/B 报告成文。
**面试价值**：证明你懂"模型只在决策点出现、其余确定性"的分层，且用数据说话。

---

### A6 —— 轨迹日志 + review→标注闭环

补齐：G9、G10。

- [ ] `trajectories/`：记录 Agent 的**决策 + tool-call**，可离线评分/重放（复用 append-only/幂等纪律）。
- [ ] viewer 加轻量 review 动作：confirm / 纠正定位 / 标根因阶段 → 写回 session。
- [ ] 把人工 review 沉淀为 **GT 标注**（喂 A1 数据集）+ **一致率指标**（进 A4）。

**验收**：一次 run 轨迹可离线重放并打分；人工 review 一次即新增一条标注。
**面试价值**：证明你理解 review（O(1) 定性）与 eval（O(N) 定量）分工，并用一套底座同时喂两者。

---

### A7 —— SSI 根因类（S3，轻埋点）★里程碑 4：第一个深度根因类

补齐：G23、G13（一部分）。

- [~] capture 失败现场相撞的两张面（occdbg / LLDB）——✅ **capture 桥已建并真跑验证**：`tools/capture.py` 驱动 `lldb -b` + `scripts/occ_capture.py`，断点处 `BRepTools::Write` 真写出活几何 BREP（断点绑定 OK，OSO 调试映射在）；顺带**修了 occ_capture 的 OCCT 7.8 `BRepTools::Write` 三参签名 bug**。⏳ 待 pin：失败现场 ChFi3d 断点 + 两面表达式（如 `S1.Face()`/`S2.Face()`），即可 `capture_ssi` → 真案子上的 S3 判别。
- [x] `tools/ssi_probe.py`：**靶向子复现**——脱离 ChFi3d 单独跑面面求交（`intersectSS` + `section` + 近切角），**S3 机制证据落地**：近切 + 期望接触却 0 → S3 签名。✅ 4 夹具判别自测（横切/割→否、切→否、近切离开→是），`test_ssi_probe.py`。
- [ ] playbook 补 S3 节点的 `localize`/`mechanism`/`counterfactual`（容差扰动 vs 降半径互斥判别 S3/S2）。
- [ ] eval 加 SSI 分层 case。

**验收**：能对 `near-tangent-faces` 完成三腿验证（定位面A×面B + 0 交线机制 + 容差/半径互斥判别），并在 eval 上量化定位/机制准确率。
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

## 5. 本周可立即开工（不依赖任何尚未实现的东西）

1. 建空壳目录（A0 末项）。
2. 写 2 个分层 case（`near-tangent-faces`、`vertex-3corner`）+ 四元组 GT + `tools/reproduce.py`（real+replay）（A1）。
3. 写 `tools/check_valid.py`（有效性判据）+ `tools/triage_input.py`（S0 预检）+ `playbook/fillet-failures.yaml` 3 条签名（A2）。
4. 写 `loop/decide_rule.py` + `investigate.py`，跑通 `near-tangent-faces` → 定位 S0/(S3) + 互斥靶向修法判别 → 分级因果结论（A3 ★里程碑 1）。

做完这 4 步，你就有一个**会做根因定位、能被 eval 打分、能在 viewer 里 review 的"圆角根因调研 Agent v0"**，且不依赖任何还没建的埋点。

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

> 维护约定：本路线图是 Agent 轨道的工作基线。完成一项勾掉一项；新增欠缺项进第 2 节 Gap Register 并标级别与阶段。任何改变工具契约、case schema、eval 维度或失效本体的改动，先更新对应真源文档（本文件 / `playbook/blend-failure-ontology.md` / `docs/root-cause-verification.md`）。
