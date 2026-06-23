# occ-debug-mesh — 设计说明书 / 交接文档

> 状态：M2 阶段 2 进行中（面网格 + 缺陷遍历已完成并验证；边离散待做）<br>
> 用途：BREP → `print-mesh` JSON（逐面世界坐标三角网格）+ 缺陷 sidecar；供 daemon 转成事件喂 Print viewer<br>
> 本文件是**给新窗口/新会话接手用的自包含说明**。上层背景见
> [print-linkage-tech-decisions.md](../../docs/print-linkage-tech-decisions.md)、
> [m2-research-notes.md](../../docs/m2-research-notes.md)（§7 清单 / §9 缺陷层 / §10 N1-N8）、
> [change-log.md](../../docs/change-log.md)（§7-8 决策与进度）。

## 1. 在系统里的位置

```
occdbg(断点内) ─写 BREP─► assets/*.brep ─► [occ-debug-mesh] ─► *.mesh.json + *.defects.json
                                            （链本地 debug OCCT V7_8_1，与被调试进程同 ABI）
                                                    │
                                       daemon 读 → 追加 update/defect 事件 → Bridge → viewer
```
occ-debug-mesh 是**纯 CLI 工具**：吃一个 BREP，吐网格 + 缺陷。不碰 LLDB、不发事件（那是 daemon 的活，M2-3 方案 A）。

## 2. 构建与运行

```bash
scripts/build-occ-debug-mesh.sh          # pixi clang 18，OpenCASCADE_DIR=安装树配置
export DYLD_LIBRARY_PATH="$PWD/occt/install/debug/lib"
BIN=tools/occ-debug-mesh/build/occ-debug-mesh

$BIN <in.brep> [out.mesh.json]           # 转换：out 默认 in+".mesh.json"，缺陷写 <base>.defects.json
$BIN --diagnose <in.brep>                # 打印 BRepCheck 对每个子形状的报告（调试用）
$BIN --make-test-box  <out.brep>         # 夹具：10x20x30 盒子（有效）
$BIN --make-test-bad  <out.brep>         # 夹具：开口壳当 solid（NotClosed）
$BIN --make-test-located <out.brep>      # 夹具：带 Location 的盒子（旋转90°Z+平移）
$BIN --make-test-selfx <out.brep>        # 夹具：自交(bowtie)面
$BIN --make-test-edge  <out.brep>        # 夹具：裸边（边离散验收用）
```
**构建关键点**：`OpenCASCADE_DIR` 必须指**安装树** `occt/install/debug/lib/cmake/opencascade`——构建树 `occt/build/debug` 的 config 引用了没生成的模块 Targets，会报错。

## 3. 当前架构（`src/main.cxx`）

- **`convert()`**：读 BREP → `BRepMesh_IncrementalMesh`（带参构造即网格化）→ `TopExp::MapShapes(FACE/EDGE)` → 逐面 `meshFace()` → `collectDefects()` → 写 mesh JSON（`faces[]` + `edges:[]` 当前空）+ defects sidecar。
- **`meshFace()`**：`BRep_Tool::Triangulation(face, loc)` 取面局部三角网格 → **应用 `loc.Transformation()` 得世界坐标**（M2-4）；缺法线时 `BRepLib_ToolTriangulatedShape::ComputeNormals`；`REVERSED` 面翻绕序+翻法线；非有限节点 → 整面计入 `failed_faces`。
- **`collectDefects()` / `collectInto()`**：`BRepCheck_Analyzer`；**遍历 standalone `Status()` + context 状态**（关键坑：NotClosed 等存在"子形状在父语境下"的 context 里，且 `IsValid(sub)` 单独看可能是 valid）；wire 缺陷用 `MapShapesAndAncestors` 挂到**父面 face_id**；`statusName` 全 36 枚举命名（不丢信息），`statusCategory` 映射到 `defect.category`（未映射→other 但保留真名）。
- **`diagnose()`**：枚举所有子形状的 valid + 状态（含 context），调试神器。
- **夹具** `makeTest*()`：离线造各种 BREP 验收，无需 LLDB。

## 4. 已固化的设计决策（改动前先读）

| 决策 | 取值/做法 | 出处 |
| --- | --- | --- |
| deflection | 相对挠度系数 **0.002**、角 **0.5 rad** | OCCT 默认 0.001/0.5，放粗一档求调试快 |
| 法线 | `BRepLib_ToolTriangulatedShape::ComputeNormals`（同 AIS）；`REVERSED` 翻 | 不手搓、跨光滑边平滑 |
| 世界坐标 | 读 `Poly_Triangulation` 后**应用累积 `TopLoc_Location`** | M2-4；已验证非 identity 也对 |
| face_id/edge_id | `= TopExp::MapShapes` 索引（`F1`/`E1`…） | M2-5；mesh 与 defect ref 共用同一索引 |
| 缺陷映射 | `BRepCheck_Status` → category；未映射 `other` 但保留真名 | §9；BRepCheck ~36 码 |
| 坏面 | 非有限节点/无三角化 → `failed_faces`，`partial=true` | V2/D4；坏 shape 不崩 |

**7.8 API 教训**：`Poly_Triangulation` 用 1-based `Node(i)`/`Triangle(i)`/`Normal(i)`（不是旧 `Nodes()` 数组）。**改 OCCT 调用前先 `grep` 头文件确认 7.8.1 签名**（我们就是这么避坑的）。

## 5. 输出格式

- **`<base>.mesh.json`**：见 [Print/protocol/print-mesh.schema.json](../Print/protocol/print-mesh.schema.json)。`faces[]`（face_id/orientation/positions/indices/normals，世界 double）、`edges[]`（**当前空**）、`partial`/`failed_faces`。**无 per-asset origin**（会话级 origin 由 viewer 减）。
- **`<base>.defects.json`**：`defect` 对象数组 `{category, source:"brepcheck", severity, status:"BRepCheck_*", ref?:{face_id/edge_id}}`，对齐 [event.schema.json](../Print/protocol/event.schema.json) 的 `$defs.defect`（`entity_id` 由 daemon 填）。

## 6. 已验证（测试矩阵，可一键回归）

| 夹具 | 期望 | 状态 |
| --- | --- | --- |
| box | 6 面、12 三角、世界 bbox [0,10]×[0,20]×[0,30]、法线外向 | ✅ |
| located（旋转+平移） | 世界 bbox X[80,100] Y[200,210] Z[300,330]、法线外向单位长 | ✅ M2-4 命脉 |
| bad（开口壳） | `NotClosed → open_boundary` | ✅ |
| selfx（自交面） | `SelfIntersectingWire → self_intersection`（ref=父面 F1）+ `UnorientableShape` | ✅ |
| edge（裸边） | 优雅退化：0 面 0 边不崩 | ✅（待边离散后变 1 边） |

## 7. ★ 遗留需求 #1（下一个任务）：边离散

**目标**：填上 `print-mesh` 的 `edges[]`（现在硬编码为 `[]`）。

**已定方案（Q4，见 change-log §7）**：按输入分派——
- **面上的边**：复用 `Poly_PolygonOnTriangulation`（已网格化、与面网格边界严丝合缝、免费）。
- **裸 Edge/Wire**：`GCPnts_QuasiUniformDeflection` 直接离散曲线（无需网格）。

**实现算法**：
```
edges_map = TopExp::MapShapes(shape, EDGE)         // 自动去重共享边；edge_id = "E"+i
edgeFaces = TopExp::MapShapesAndAncestors(shape, EDGE, FACE)
for each edge E_i:
    if 有祖先面 F 且 F 已三角化:
        tri, loc = BRep_Tool::Triangulation(F, loc)
        poly = BRep_Tool::PolygonOnTriangulation(E_i, tri, loc)   // 节点是 tri 节点的索引
        points = [ tri.Node(poly.Node(k)).Transformed(loc) ]      // 世界坐标
    else:   // 裸边 / 面没三角化
        adaptor = BRepAdaptor_Curve(E_i)                          // 含 edge location → 世界
        GCPnts_QuasiUniformDeflection d(adaptor, deflection)
        points = [ d.Value(k) for k in 1..d.NbPoints() ]
    if points 有效（>=2，全有限）: edges[].push({edge_id:"E"+i, points})
```

**要点 / 坑**：
- **世界坐标**：两条路径都要落到世界系（PolygonOnTriangulation 用 tri 的 loc；BRepAdaptor_Curve 自带 edge location）。
- **7.8 API**：`Poly_PolygonOnTriangulation` 的节点访问（`Node(k)`/`Nodes()`）先 grep 头文件确认；`BRep_Tool::PolygonOnTriangulation(edge, tri, loc)` 签名同上确认。
- **退化边**：`BRep_Tool::Degenerated(edge)` 为真则跳过（无 3D 曲线）。
- **NaN 守卫**：同 `meshFace`，非有限点丢弃该边。
- **deflection**：与面网格一致（相对系数或由 bbox 推一个绝对值；GCPnts 用绝对挠度）。

**验收**（夹具已就位）：
- `box` → **12 条边**（每条直线 2 点左右）。
- `--make-test-edge` 裸边 → **1 条 polyline**（现在是 0）。
- 加一个 verify 脚本，照 §6 的风格断言边数/世界坐标。

**涉及头文件**：`BRep_Tool.hxx`（`PolygonOnTriangulation`/`Degenerated`/`Curve`）、`Poly_PolygonOnTriangulation.hxx`、`BRepAdaptor_Curve.hxx`、`GCPnts_QuasiUniformDeflection.hxx`（CMake 链接已够：TKMesh/TKGeomBase/TKBRep；如缺符号补 toolkit）。

## 8. 其它遗留 / 延后（backlog）

| 项 | 说明 | 关联 |
| --- | --- | --- |
| 超时看门狗 | 病态 shape 上 BRepMesh 可能卡死，需超时中断 | V2 |
| 镜像翻绕序 | 现仅处理 `REVERSED`；Location 含镜像(det<0)未翻 | V9 |
| `sha256` | mesh/defect 资产算 sha256 供 viewer 缓存 | V7 |
| non_manifold | BRepCheck 不报，需 `BRepAlgoAPI_Check`(bopcheck) | §9 |
| ChFi3d 算法状态 | WalkingFailure/TwistedSurface，需 TKFillet 适配层 | M3 |
| shell 缺陷 ref | NotClosed 现为场景级，可挂到自由边 | R3 |
| bootstrap 接入 | 把 build-occ-debug-mesh 加进 bootstrap.sh | M2-10 |

## 9. 给新窗口的上下文地图

1. 读 [m2-research-notes.md](../../docs/m2-research-notes.md)：§3 锁定的 M2-1/2/3、§7 文件清单、§9 缺陷层、§10 N1-N8。
2. 读 [print-linkage-tech-decisions.md](../../docs/print-linkage-tech-decisions.md)：接缝契约、print-mesh 格式、§8 风险表。
3. 协议真源：[Print/protocol/*.schema.json](../Print/protocol/)。
4. 本工具代码：`src/main.cxx`（单文件）；构建：`scripts/build-occ-debug-mesh.sh`。
5. 验收习惯：每加一块就造夹具、离线断言（见 §6/§7），别依赖 LLDB。
