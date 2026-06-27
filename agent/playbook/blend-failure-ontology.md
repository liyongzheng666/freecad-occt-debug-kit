# 圆角/blend 失效本体（Blend Failure Ontology）

> 状态：本体基线（Ontology Baseline）<br>
> 用途：根因寻找的**骨架真源**——`agent/playbook/fillet-failures.yaml` 的每个节点都挂在本表的某个阶段上。<br>
> 关联：[../README.md](../README.md)（路线图）、[../docs/root-cause-verification.md](../docs/root-cause-verification.md)（验证方法学）、[../../docs/occ-fillet-debug-agent-architecture.md](../../docs/occ-fillet-debug-agent-architecture.md) §23（OCC 调用链）。

---

## 0. 为什么需要本体

本项目的最终目标是**根因寻找（root-cause finding）**，不是"把圆角修好"。根因寻找的第一性问题是：**一个圆角失败，是流水线的哪一阶段先崩、为什么崩。**

圆角几何建模的失效在内核之间**高度同构**（滚球容纳、面面求交、顶点收敛、拓扑缝合），所以本体分两层：

- **本体层（内核无关）**：S0–S6 的失效阶段——通用 blend 真理，换 Parasolid/ACIS 也成立。
- **适配层（内核相关）**：把 OCC ChFi3d 的具体症状（异常串、phase）映射到本体阶段。

agent 在本体层做推理，在适配层接 OCC 的可观测信号。

---

## 1. 核心原则：症状 ≠ 根因

OCC 抛出的异常串（如 `StripeEdgeInter: too big radiuses`）是**proximate cause（近端症状）**，属于它被抛出的那一阶段；真正的 **distal cause（远端病根）**经常在更上游。

> 例：`too big radiuses` 属于 **S3（stripe-stripe 面面求交）**，但病根可能在 **S0**（两支撑面近切/sliver）或 **S2**（半径 > 局部凹曲率，滚球塞不进）。

**异常串只用于触发调研、缩小搜索，绝不等于结论。** agent 必须把链倒推回最早先崩的阶段。

---

## 2. 本体层：按几何算法阶段（S0–S6）

| 阶段 | 几何本质 | OCC 落点（§23） | 典型根因 | 可观测证据 | 独立复现方式 |
|---|---|---|---|---|---|
| **S0 输入质量** | blend 的前置条件 | 输入 `BRepCheck_Analyzer` | sliver 面 / 短于容差的边 / 容差不一致 / 该 G1 处不 G1 / 自交 wire | 二面角、边长 vs 容差、tolerance 分布、自交对 | 单独 check 输入形状（**免埋点**） |
| **S1 spine / 链抽取** | 边链 + 切向传播 + 凹/凸分类 | `ExtentAnalyse` / Spine | 链断裂 / 退化 spine / 凹凸判错 / 切向连接歧义 | spine 参数范围、切向连续性、链起止 | 抽 spine 单独检查 |
| **S2 blend 面构造** | 滚球 / spring curve 沿 spine 扫掠成面 | `PerformSetOfSurf` → `CallPerformSurf` → `PerformSurf`（建 `SurfData`） | **r > 局部凹曲率（球塞不进）** / 构面数值失败 / twist | `SurfData`、`TwistOnS1/S2`、生成面 index | 给定截面单独构 blend 面 |
| **S3 面面求交（SSI）** | blend 面 ∩ 支撑面（spring/contact 曲线）、blend ∩ blend | `PerformSurf` 内的求交 + **`ChFi3d_StripeEdgeInter`**（底层 IntPatch/GeomInt/IntTools） | **SSI 无解 / 部分解 / 近切不稳** / contact 曲线缺失 / 杂散交线 | 交线条数 vs 期望、交线质量、`FaceInterference` | **抽两张面跑独立 `IntTools`/`GeomInt` 求交** |
| **S4 顶点收敛** | 2/3/N 边 corner、setback、mitre | `PerformIntersectionAtEnd`、`PerformTwoCorner`/`ThreeCorner`/`MoreThreeCorner` | corner 拓扑无法闭合 / 端部求交失败 / setback 区域不一致 | corner 交点、`CommonPoint`、端部区间 | 抽局部顶点子问题单算 |
| **S5 拓扑缝合** | 裁剪 + sewing + pcurve + 成体 | `ChFi3d_FilDS` / `CompleteDS` / reconstruction / `SetRegul` | 缝隙 / 缺 pcurve / 结果自交 / 非流形 | 缺面/缝隙、pcurve 存在性、shell 闭合 | `BRepCheck` 结果体 |
| **S6 输出有效性** | 最终合法性（**真目标，非 `IsDone()`**） | 结果 `BRepCheck_Analyzer` + 自交检测 | 自交 / 非法面 / 切向丢失 / 拓扑错误 | 自交对、无效子形状、G1 检查 | 你已有的 `occ-debug-mesh` defects（**免埋点**） |

### 关键备忘

- **`IsDone()` ≠ S6 通过**：两个内核都会返回"`IsDone()=true` 但几何破损"的结果。**成功判据必须是 S6 有效性，不是 `IsDone()`**（详见验证文档的"代理奖励"警告）。
- **凹 vs 凸**：blend 滚过凹区时 `r ≤ 局部凹曲率半径`（球必须容纳得下），凸边(round)是另一套失效；两者不能用同一根"半径单调"曲线描述。
- **可行性非单调**：小半径也会失败（容差/退化），且存在非单调可行窗口；勿假设"半径越小越容易成功"。

---

## 3. 适配层：ChFi3d 症状 → 候选阶段

| OCC 症状 / 信号 | 近端阶段 | 需排查的远端阶段 |
|---|---|---|
| `StripeEdgeInter : fillets have too big radiuses` | S3 | S0（近切/sliver）、S2（球塞不进） |
| `PerformTwoCorner/ThreeCorner` 失败 | S4 | S3（端部求交）、S0（顶点处输入） |
| `HasResult()=true` 但 `IsDone()=false`（部分结果） | S5 | 触发它的 S2/S3/S4 |
| `BadShape()` 存在 | S5/S6 | 看 BadShape 落在哪一阶段产物 |
| 结果 `IsDone()=true` 但自交/非法 | **S6** | 上游任意——这是最危险的"假成功" |
| 通用 `StdFail_NotDone`（无更多信息） | 未知 | **必须靠定位**，不能从异常串猜 |

> 适配表是**触发器**，不是判定器。命中后进入根因验证的三腿流程（定位 → 机制 → 反事实）。

---

## 4. 攻克顺序（成本/收益）

根因覆盖应**从两头往中间推**：

1. **先 S0 + S6**（输入质量 + 输出有效性）——**免埋点**，用 `occ-debug-mesh` + `BRepCheck` 就能做，命中率最高（大量"blend bug"其实是 input bug）。
2. **再 S3（SSI）**——**轻埋点**：只需 capture 两张面 + 跑一次独立求交，远小于全套深埋点；性价比最高的第一个深度根因类。
3. **最后 S2 / S4**——**深埋点**：需要 `SurfData` / `CommonPoint` 级中间态采集（依赖 occdbg/LLDB 前半管线）。

---

## 5. playbook 节点如何挂到本体（schema 约定）

`fillet-failures.yaml` 每个节点：

```yaml
- id: <signature-id>
  symptom:                      # 适配层：触发条件（不是结论）
    exception: "<substr>"
    phase: <occ-phase>
  proximate_stage: S3           # 近端阶段（本体层）
  root_cause_candidates:        # 远端候选，按"该用哪条腿区分"组织
    - stage: S0
      cause: "两支撑面近切 / sliver"
      localize:  { tool: triage_input,   check: dihedral_angle }
      mechanism: { evidence: "二面角 < ε" }
      counterfactual: { fix: heal_input, must_not_change: radius }
    - stage: S2
      cause: "半径 > 局部凹曲率（球塞不进）"
      localize:  { tool: curvature_at_spine }
      counterfactual: { fix: lower_radius, discriminates_from: S3 }
    - stage: S3
      cause: "SSI 数值失败 / 近切不稳"
      localize:  { tool: ssi_probe, check: intersection_curve_count }
      mechanism: { evidence: "期望 1 条 contact 曲线，实得 0" }
      counterfactual: { fix: perturb_tolerance, must_not_change: radius }
```

> 注意 `discriminates_from` / `must_not_change`：**不同候选用互斥的靶向修法相互判别**（降半径修好→S2；调容差修好且半径不动→S3）。这是根因验证的核心，详见 [../docs/root-cause-verification.md](../docs/root-cause-verification.md)。
