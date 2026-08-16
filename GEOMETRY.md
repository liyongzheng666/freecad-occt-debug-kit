# 几何建模开发者轨道（Geometry Track）

> **For kernel / geometry developers**: this repo turns an OCCT fillet failure into a *stage-localized root cause with evidence* — failure ontology (S0–S6), geometric-validity verifier, debugger-driven capture, and a Parasolid cross-reference. If you know B-rep, ChFi3d, and `BRepCheck`, start here.
> **面向几何建模 / 内核开发者**：这个仓库把一次圆角失败变成「定位到流水线阶段 + 带证据的根因结论」。如果你熟悉 B-rep、ChFi3d、`BRepCheck`，从这里开始。

## 一句话背景

圆角（blend）失败不是黑箱：它发生在一条 S0–S6 流水线的**某一阶段**（输入质量 → spine 抽取 → blend 面构造 → 面面求交 → 顶点收敛 → 缝合 → 输出有效性）。本仓库做三件事：

1. **定位**失败先崩在哪一阶段、涉及哪个面/边；
2. 用**几何有效性**（BRepCheck + 面面自交）而非 `IsDone()` 当判据——`IsDone()=true` 但自交的「假绿」是真实存在的陷阱（真实案例：凹槽 r=15）；
3. 用**互斥反事实**（降半径 vs 只扰容差）区分「球塞不进（S2）」和「求交数值病态（S3）」。

## 阅读路径（按这个顺序）

| 顺序 | 读什么 | 为什么读 |
| --- | --- | --- |
| 1 | [agent/playbook/blend-failure-ontology.md](agent/playbook/blend-failure-ontology.md) | **失效本体**：S0–S6 六阶段 + ChFi3d 落点 + 失效四态分类学（algorithmic_overflow / face_overflow / geometric_near_tangent / geometric_curvature） |
| 2 | [docs/fillet-para-study-and-agent-gap-plan.md](docs/fillet-para-study-and-agent-gap-plan.md) | **Parasolid 对照**：Parasolid Ch74 / §77.3.4 的故障分类 ↔ OCCT 行为 ↔ 本仓库 S 阶段，含 6 个实跑验证的 STEP 例子 |
| 3 | [tools/occ-debug-mesh/README.md](tools/occ-debug-mesh/README.md) + [docs/occ-debug-mesh-export-design.md](docs/occ-debug-mesh-export-design.md) | **缺陷导出**：BREP → mesh/geom/defects，BRepCheck 全量遍历 + BOPAlgo 面面自交 |
| 4 | [docs/lldb-dynamic-geometry-capture.md](docs/lldb-dynamic-geometry-capture.md) | **活几何捕获**：断点内把失败现场的面/曲线写成 BREP（如 StartSol 处 HS1/HS2） |
| 5 | [agent/cases/models/](agent/cases/models/)（+ manifest.json） | **真实失败资产**：每个 STEP 都经隔离 FreeCADCmd 实跑验证，读回边号已核定 |
| 6 | [agent/docs/root-cause-verification.md](agent/docs/root-cause-verification.md) | 三腿验证方法学（定位/机制/反事实）——即使不关心 agent，这也是可复用的调试纪律 |

## 核心概念速览

**失效四态**（agent 的分类学，来自 Parasolid 对照 + 实测）：

| 类别 | 症状 | 判别量 |
| --- | --- | --- |
| algorithmic_overflow | ≥2 边两 blend 带重叠（`StripeEdgeInter: too big radiuses`） | blend 边数 ≥2 + 平面/非近切 |
| face_overflow | 单边单带溢出——离开支撑面/盖过 edge loop | 单边 + 无第二条带可裁 |
| geometric_near_tangent | 两支撑面近切（二面角 <10°），滚球塞不进，半径无关 | min_dihedral_deg |
| geometric_curvature | r > 凹壁曲率半径，偏移面无解 | min_support_curv_radius |

**两个真实发现（可直接对照你的经验）**：
- STEP 导出重读会**重编号边**（E4 边 7→8、E5 7→6）——边号必须以读回后的 shape 复核；
- OCCT「too big radiuses」失败族把中间几何埋进**匿名 DStr**——纯 LLDB 表达式取不到具名面，需源码插桩（`OCCT_DEBUG_SSI_OUT`，见 [docs/dependencies.md](docs/dependencies.md)）。

## 快速命令

```bash
scripts/build-occ-debug-mesh.sh            # 编译 occ-debug-mesh（link occt/install/debug）
scripts/verify-occ-debug-mesh.sh           # 60 项离线夹具回归
BIN=tools/occ-debug-mesh/build/occ-debug-mesh
$BIN in.brep out.mesh.json                 # BREP → mesh/geom/defects
$BIN --diagnose in.brep                    # BRepCheck 逐子形状报告
python -m agent.loop.investigate "brep:/abs/m.brep" 5 --edges 3   # 对该模型直接出根因诊断
```

> 环境仅维护 **macOS Apple Silicon**；依赖/构建链见 [docs/dependencies.md](docs/dependencies.md)。提问题请带复现包（[.github/ISSUE_TEMPLATE.md](.github/ISSUE_TEMPLATE.md)）。
